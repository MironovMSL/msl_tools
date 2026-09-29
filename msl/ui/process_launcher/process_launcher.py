import logging
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.core.fs.system_info import SystemInfo

logger = logging.getLogger(__name__)


class ProcessLauncher:
    """Starts external programs (Maya, mayapy, the file explorer, a browser).

    Lives in ui/, not core/, because it is built on QProcess /
    QDesktopServices. Callers are Qt pages anyway (the hub's tools).
    """

    @classmethod
    def launch_detached(cls, program: str | Path, *, arguments: list[str] | None = None,
                        environment: dict[str, str] | None = None,
                        working_dir: str | Path | None = None) -> bool:
        """Starts `program` as a separate, detached process.

        Args:
            program: Executable path.
            arguments: Command-line arguments.
            environment: Variables added on top of the system environment
                (overriding same-named ones); None = inherit it unchanged.
            working_dir: Working directory for the process.

        Returns:
            True if the process was started.
        """
        program = Path(program)
        if not program.exists():
            logger.warning(f"Unable to launch process. Missing executable: {program}")
            return False

        process = qt.QtCore.QProcess()
        if environment is not None:
            process_env = qt.QtCore.QProcessEnvironment.systemEnvironment()
            for key, value in environment.items():
                process_env.insert(key, value)
            process.setProcessEnvironment(process_env)

        process.setProgram(str(program))
        if arguments:
            process.setArguments(arguments)
        if working_dir:
            process.setWorkingDirectory(str(working_dir))

        started = process.startDetached()
        if not started:
            logger.warning(f"Failed to start detached process: {program}")
        return started

    @classmethod
    def launch_maya(cls, *, version: str | None = None, environment: dict[str, str] | None = None) -> bool:
        """Launches the given (or the latest detected) Maya version."""
        executable = MayaPaths.get_latest_executable(version) if version else MayaPaths.get_latest_executable()
        if executable is None:
            logger.warning("Unable to launch Maya. No installation detected.")
            return False
        return cls.launch_detached(executable, environment=environment)

    @classmethod
    def run_script_with_mayapy(cls, script_path: str | Path, *, version: str | None = None) -> bool:
        """Runs a Python script with headless mayapy."""
        script_path = Path(script_path)
        if not script_path.exists():
            logger.warning(f"Unable to run script. Missing file: {script_path}")
            return False

        mayapy = MayaPaths.get_latest_executable(version, python_executable=True) if version \
            else MayaPaths.get_latest_executable(python_executable=True)
        if mayapy is None:
            logger.warning("Unable to run script. mayapy not found.")
            return False
        return cls.launch_detached(mayapy, arguments=[str(script_path)])

    @classmethod
    def open_file_explorer(cls, path: str | Path) -> bool:
        """Opens the system file explorer / Finder at `path` (a file is selected)."""
        path = Path(path)
        if not path.exists():
            logger.warning(f"Unable to open location. Missing path: {path}")
            return False

        system = SystemInfo.get_system()
        if system == SystemInfo.OS_WINDOWS:
            args = [str(path)] if path.is_dir() else ["/select,", str(path)]
            return cls.launch_detached(r"C:\Windows\explorer.exe", arguments=args)
        elif system == SystemInfo.OS_MAC:
            return cls.launch_detached("/usr/bin/open", arguments=["-R", str(path)])
        else:
            logger.warning(f'Unable to open file explorer. Unsupported system: "{system}"')
            return False

    @classmethod
    def open_url_in_browser(cls, url: str) -> bool:
        """Opens `url` in the default browser."""
        return bool(qt.QtGui.QDesktopServices.openUrl(qt.QtCore.QUrl(url)))
