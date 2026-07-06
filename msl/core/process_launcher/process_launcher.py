from PySide6 import QtCore, QtGui
from pathlib import Path
import logging

from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.fs.maya_paths import MayaPaths

logger = logging.getLogger(__name__)


class ProcessLauncher:

    @classmethod
    def launch_detached(cls, program: str | Path, *, arguments: list[str] | None = None,
                         environment: dict[str, str] | None = None,
                         working_dir: str | Path | None = None) -> bool:
        """Запускает внешнее приложение отдельным процессом."""
        program = Path(program)
        if not program.exists():
            logger.warning(f"Unable to launch process. Missing executable: {program}")
            return False

        process = QtCore.QProcess()
        if environment is not None:
            process_env = QtCore.QProcessEnvironment.systemEnvironment()
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
        """Запускает последнюю обнаруженную (или указанную) версию Maya."""
        executable = MayaPaths.get_latest_executable(version) if version else MayaPaths.get_latest_executable()
        if executable is None:
            logger.warning("Unable to launch Maya. No installation detected.")
            return False
        return cls.launch_detached(executable, environment=environment)

    @classmethod
    def run_script_with_mayapy(cls, script_path: str | Path, *, version: str | None = None) -> bool:
        """Запускает Python-скрипт через headless mayapy."""
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
        """Открывает системный проводник/Finder на указанном пути."""
        path = Path(path)
        if not path.exists():
            logger.warning(f"Unable to open location. Missing path: {path}")
            return False

        system = Paths.get_system()
        if system == Paths.OS_WINDOWS:
            explorer = Path(QtCore.QDir.toNativeSeparators(str(Path(Paths.get_home_dir().drive) / "Windows" / "explorer.exe")))
            args = [str(path)] if path.is_dir() else ["/select,", str(path)]
            return cls.launch_detached(r"C:\Windows\explorer.exe", arguments=args)
        elif system == Paths.OS_MAC:
            return cls.launch_detached("/usr/bin/open", arguments=["-R", str(path)])
        else:
            logger.warning(f'Unable to open file explorer. Unsupported system: "{system}"')
            return False

    @classmethod
    def open_url_in_browser(cls, url: str) -> bool:
        """Открывает URL в браузере по умолчанию."""
        return bool(QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)))