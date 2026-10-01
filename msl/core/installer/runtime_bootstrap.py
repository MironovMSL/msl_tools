"""The Python environment the desktop hub runs in — creating it and finding it.

The hub needs Python 3.10+ and the packages in `requirements.txt` (PySide6).
A user's machine has neither set up for it, so setup creates ONE virtual
environment for msl_tools in a fixed per-user place:

    %LOCALAPPDATA%\\MSL\\runtime\\.venv        (MSL_RUNTIME_DIR overrides the folder)

It is deliberately NOT inside the install folder: reinstalling, moving or
updating the tool then never re-downloads the packages.

STANDARD LIBRARY ONLY, and no imports from this package: this file is run by
path with whatever Python the machine has, before the environment exists —
and from a folder that may not even be named `msl_tools` (a GitHub archive
unpacks as "msl_tools-<tag>"), so the package isn't importable yet.

As a script (what setup_express_launcher.bat does):

    python runtime_bootstrap.py --run <script.py> [args...]

makes sure the environment is ready, then starts <script.py> with ITS Python
(windowed, detached) and exits.
"""
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

RUNTIME_ENV_VAR = "MSL_RUNTIME_DIR"
MINIMUM_PYTHON = (3, 10)
_MARKER_NAME = "requirements.sha256"


def runtime_dir() -> Path:
    """Folder that holds the environment (see the module docstring)."""
    override = os.environ.get(RUNTIME_ENV_VAR)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "MSL" / "runtime"


def venv_dir() -> Path:
    return runtime_dir() / ".venv"


def python_executable(windowed: bool = False) -> Path:
    """The environment's interpreter; `windowed` = the one without a console
    window (pythonw.exe), for starting GUI programs."""
    if os.name == "nt":
        return venv_dir() / "Scripts" / ("pythonw.exe" if windowed else "python.exe")
    return venv_dir() / "bin" / "python"


def default_requirements_file() -> Path:
    """requirements.txt of the checkout / archive this file belongs to
    (<root>/msl/core/installer/runtime_bootstrap.py -> <root>/requirements.txt)."""
    return Path(__file__).resolve().parents[3] / "requirements.txt"


def _requirements_hash(requirements_file: Path) -> str:
    return hashlib.sha256(requirements_file.read_bytes()).hexdigest()


def is_ready(requirements_file: Path | None = None) -> bool:
    """True when the environment exists and was built from these exact
    requirements (a changed requirements.txt means "install again")."""
    requirements_file = Path(requirements_file or default_requirements_file())
    marker = runtime_dir() / _MARKER_NAME
    if not python_executable().is_file() or not marker.is_file() or not requirements_file.is_file():
        return False
    return marker.read_text(encoding="utf-8").strip() == _requirements_hash(requirements_file)


def ensure(requirements_file: Path | None = None, log=print) -> bool:
    """Creates the environment and installs the requirements, unless that's
    already done for this requirements.txt. `log` gets progress lines.
    Returns False (after logging why) if it couldn't be made ready."""
    requirements_file = Path(requirements_file or default_requirements_file())
    if not requirements_file.is_file():
        log(f"Missing requirements file: {requirements_file}")
        return False
    if is_ready(requirements_file):
        return True

    try:
        if not python_executable().is_file():
            log(f"Creating the Python environment in {venv_dir()} ...")
            venv_dir().parent.mkdir(parents=True, exist_ok=True)
            venv.EnvBuilder(with_pip=True, clear=False).create(str(venv_dir()))
        log("Installing packages (PySide6) - the first time this downloads about 100 MB ...")
        result = subprocess.run([str(python_executable()), "-m", "pip", "install", "--disable-pip-version-check",
                                 "-r", str(requirements_file)])
        if result.returncode != 0:
            log("Package installation failed (see the messages above). Check the internet connection and try again.")
            return False
        (runtime_dir() / _MARKER_NAME).write_text(_requirements_hash(requirements_file), encoding="utf-8")
    except Exception as error:  # a failed venv / missing ensurepip / no permission
        log(f"Could not prepare the Python environment: {error}")
        return False
    log("The Python environment is ready.")
    return True


def start(script: Path, arguments: list[str] | None = None, working_dir: Path | None = None) -> None:
    """Starts `script` with the environment's windowed interpreter, detached
    from this process (it keeps running after we exit)."""
    command = [str(python_executable(windowed=True)), str(script), *(arguments or [])]
    options = {"cwd": str(working_dir) if working_dir else None, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def main(argv: list[str]) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        print("MSL Tools needs Python %d.%d or newer. This is Python %s." % (*MINIMUM_PYTHON, sys.version.split()[0]))
        return 1
    if len(argv) < 2 or argv[0] != "--run":
        print("usage: runtime_bootstrap.py --run <script.py> [args...]")
        return 2
    script = Path(argv[1])
    if not ensure():
        return 1
    start(script, argv[2:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
