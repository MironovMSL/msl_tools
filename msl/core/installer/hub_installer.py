"""Installs the desktop hub into a folder of the user's choice.

Only copies files and makes a shortcut — nothing is registered inside Maya
anymore: Maya Gate injects its own userSetup on every launch (see
tools/desktop/maya_gate/user_setup.py), so Maya's own folders stay untouched.

An install looks like this (`install_dir` is what the user picks):

    <install_dir>/
        msl_tools/              the package root (what must be importable from install_dir)
            msl/                code + assets            <- replaced by install / update
            requirements.txt, LICENSE, README.md         <- replaced too
            configs/, logs/     per-user, created on first run  <- never touched

The Python environment lives elsewhere (core/installer/runtime_bootstrap.py).
Qt-free; every public method returns False on failure and logs why.
"""
import logging
import os
import shutil
import subprocess
from pathlib import Path

from msl_tools.msl.core.version.local_version import LocalVersionReader


class HubInstaller:
    """Copies the hub from `source_root` (the checkout / unpacked archive
    running the installer) into an install folder, and removes it again."""

    PACKAGE_NAME = "msl_tools"
    MAIN_MODULE = "msl"
    REQUIRED_DIRS = ("core", "tools", "ui", "assets")       # what a valid msl/ must contain
    ROOT_FILES = ("requirements.txt", "LICENSE", "README.md")
    USER_DATA_DIRS = ("configs", "logs")                    # kept across installs and updates
    HUB_MODULE = "msl_tools.msl.run_hub"
    SHORTCUT_NAME = "MSL Tools"
    ICON_RELATIVE = Path("msl") / "assets" / "icons" / "brand" / "hub.ico"

    def __init__(self, source_root: str | Path, logger: logging.Logger | None = None):
        """
        Args:
            source_root: The package root to install FROM — the folder that
                contains `msl/` (its own name doesn't matter).
        """
        self.source_root = Path(source_root).resolve()
        self._logger = logger or logging.getLogger(__name__)

    # --- locations ---------------------------------------------------------------

    @staticmethod
    def default_install_dir() -> Path:
        """%LOCALAPPDATA%/MSL — per-user, needs no administrator rights."""
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
        return base / "MSL"

    def target_root(self, install_dir: str | Path) -> Path:
        return Path(install_dir) / self.PACKAGE_NAME

    def installed_version(self, install_dir: str | Path) -> str | None:
        """Version of the copy installed in `install_dir`, or None if there is none."""
        main = self.target_root(install_dir) / self.MAIN_MODULE
        return LocalVersionReader().get_version(main) if (main / "__init__.py").is_file() else None

    def is_source(self, install_dir: str | Path) -> bool:
        """True when `install_dir` already IS where we're running from —
        installing there would delete the files being copied."""
        return self.target_root(install_dir).resolve() == self.source_root

    # --- install / uninstall -----------------------------------------------------

    def install(self, install_dir: str | Path) -> bool:
        """Copies msl/ and the root files into <install_dir>/msl_tools,
        replacing a previous install's code. configs/ and logs/ there are
        left alone."""
        target = self.target_root(install_dir)
        source_main = self.source_root / self.MAIN_MODULE
        if not self._is_valid_main(source_main):
            self._logger.warning(f'Unable to install: "{source_main}" is not a complete package.')
            return False
        if self.is_source(install_dir):
            self._logger.warning(f'Unable to install into "{install_dir}": that is the folder the installer runs from.')
            return False

        target_main = target / self.MAIN_MODULE
        try:
            target.mkdir(parents=True, exist_ok=True)
            if target_main.exists():
                shutil.rmtree(target_main)
            shutil.copytree(source_main, target_main, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for name in self.ROOT_FILES:
                if (self.source_root / name).is_file():
                    shutil.copy2(self.source_root / name, target / name)
        except OSError as error:
            self._logger.warning(f'Unable to copy the package to "{target}". Issue: {error}')
            return False

        if not self._is_valid_main(target_main):
            self._logger.warning(f'Installation integrity check failed for "{target_main}".')
            return False
        self._logger.info(f'Installed {self.PACKAGE_NAME} to "{target}".')
        return True

    def uninstall(self, install_dir: str | Path, remove_user_data: bool = False) -> bool:
        """Removes the installed code; with `remove_user_data` also configs/
        and logs/. Leaves no empty folders behind. A missing install is a
        success (nothing to remove)."""
        target = self.target_root(install_dir)
        if not target.exists():
            return True
        if self.is_source(install_dir):
            self._logger.warning(f'Refusing to uninstall "{target}": that is the folder the installer runs from.')
            return False

        doomed = [target / self.MAIN_MODULE, *(target / name for name in self.ROOT_FILES)]
        if remove_user_data:
            doomed += [target / name for name in self.USER_DATA_DIRS]
        try:
            for path in doomed:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            for folder in (target, Path(install_dir)):  # drop them only if now empty
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
        except OSError as error:
            self._logger.warning(f'Unable to remove "{target}". Issue: {error}')
            return False
        self._logger.info(f'Uninstalled {self.PACKAGE_NAME} from "{target}".')
        return True

    def _is_valid_main(self, main: Path) -> bool:
        return (main / "__init__.py").is_file() and all((main / name).is_dir() for name in self.REQUIRED_DIRS)

    # --- launching ----------------------------------------------------------------

    def launch_command(self, python_windowed: str | Path) -> list[str]:
        """Command that starts the installed hub — run it with the install
        folder as the working directory (that's what puts msl_tools on sys.path)."""
        return [str(python_windowed), "-m", self.HUB_MODULE]

    def create_shortcut(self, install_dir: str | Path, python_windowed: str | Path,
                        shortcut_dir: str | Path | None = None) -> bool:
        """Creates "MSL Tools.lnk" that starts the installed hub — on the
        desktop, or in `shortcut_dir`. Windows only (False elsewhere)."""
        if os.name != "nt":
            self._logger.warning("Shortcuts are only created on Windows.")
            return False
        # Values travel as environment variables: no quoting of paths inside the script.
        script = (
            "$dir = if ($env:MSL_LNK_DIR) { $env:MSL_LNK_DIR } else { [Environment]::GetFolderPath('Desktop') };"
            "$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $dir ($env:MSL_LNK_NAME + '.lnk')));"
            "$link.TargetPath = $env:MSL_LNK_TARGET;"
            "$link.Arguments = $env:MSL_LNK_ARGS;"
            "$link.WorkingDirectory = $env:MSL_LNK_CWD;"
            "$link.Description = $env:MSL_LNK_NAME;"
            "if (Test-Path $env:MSL_LNK_ICON) { $link.IconLocation = $env:MSL_LNK_ICON };"
            "$link.Save()"
        )
        command = self.launch_command(python_windowed)
        environment = dict(os.environ,
                           MSL_LNK_DIR=str(shortcut_dir or ""),
                           MSL_LNK_NAME=self.SHORTCUT_NAME,
                           MSL_LNK_TARGET=command[0],
                           MSL_LNK_ARGS=" ".join(command[1:]),
                           MSL_LNK_CWD=str(Path(install_dir)),
                           MSL_LNK_ICON=str(self.target_root(install_dir) / self.ICON_RELATIVE))
        return self._run_powershell(script, environment, "create the shortcut")

    def remove_shortcut(self, shortcut_dir: str | Path | None = None) -> bool:
        """Deletes the shortcut create_shortcut() made (missing = success)."""
        if os.name != "nt":
            return True
        script = (
            "$dir = if ($env:MSL_LNK_DIR) { $env:MSL_LNK_DIR } else { [Environment]::GetFolderPath('Desktop') };"
            "$path = Join-Path $dir ($env:MSL_LNK_NAME + '.lnk');"
            "if (Test-Path $path) { Remove-Item $path }"
        )
        environment = dict(os.environ, MSL_LNK_DIR=str(shortcut_dir or ""), MSL_LNK_NAME=self.SHORTCUT_NAME)
        return self._run_powershell(script, environment, "remove the shortcut")

    def _run_powershell(self, script: str, environment: dict, purpose: str) -> bool:
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                    env=environment, capture_output=True, text=True, timeout=30,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as error:
            self._logger.warning(f"Unable to {purpose}. Issue: {error}")
            return False
        if result.returncode != 0:
            self._logger.warning(f"Unable to {purpose}. PowerShell said: {result.stderr.strip()}")
            return False
        return True
