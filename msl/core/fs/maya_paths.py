import logging
import re
from pathlib import Path

from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.fs.system_info import SystemInfo

logger = logging.getLogger(__name__)


class MayaPaths:
    """Installation discovery layer for Autodesk Maya.
    Чистый query-слой: только поиск путей, без побочных эффектов и без кэша
    (кэш/персистентность — забота отдельного компонента, см. MayaInstallConfig)."""

    @classmethod
    def get_install_root(cls, *, system: str | None = None) -> Path | None:
        """Папка Autodesk, где лежат все установленные версии Maya.
        e.g. C:/Program Files/Autodesk"""
        system = system or SystemInfo.get_system()
        install_roots = {
            SystemInfo.OS_LINUX: "/usr/autodesk",  # TODO: не проверено на реальной Linux-установке
            SystemInfo.OS_MAC: "/Applications/Autodesk",
            SystemInfo.OS_WINDOWS: r"C:\Program Files\Autodesk",
        }
        root = install_roots.get(system)
        if root is None:
            logger.warning(f'Unable to resolve Maya install root. Unknown system: "{system}"')
            return None
        return Path(root)

    @classmethod
    def get_executable_path(cls, version: str, *, system: str | None = None, python_executable: bool = False) -> Path | None:
        """Путь к конкретному maya.exe / mayapy.exe для указанной версии."""
        if not version:
            logger.warning("Unable to resolve Maya executable path. No version provided.")
            return None

        system = system or SystemInfo.get_system()
        install_root = cls.get_install_root(system=system)
        if install_root is None:
            return None

        executable_name = "mayapy" if python_executable else "maya"
        executable_paths = {
            SystemInfo.OS_LINUX: install_root / f"maya{version}" / "bin" / executable_name,
            SystemInfo.OS_MAC: install_root / f"maya{version}" / "Maya.app" / "Contents" / "bin" / executable_name,
            SystemInfo.OS_WINDOWS: install_root / f"Maya{version}" / "bin" / f"{executable_name}.exe",
        }
        path = executable_paths.get(system)
        if path is None:
            logger.warning(f'Unable to resolve Maya executable path. Unknown system: "{system}"')
        return path

    @classmethod
    def get_preferences_root(cls, *, system: str | None = None, use_maya_commands: bool = False) -> Path | None:
        """Родительская папка препочтений Maya (папка, где лежат версии, e.g. .../maya/2024)."""
        system = system or SystemInfo.get_system()

        if use_maya_commands:
            try:
                import maya.cmds as cmds
                return Path(cmds.about(preferences=True)).parent
            except Exception as e:
                logger.debug(
                    f"Unable to retrieve preferences using Maya commands. Issue: {e}. "
                    f"Falling back to system-based resolution."
                )

        if system == SystemInfo.OS_WINDOWS:
            try:
                import maya.cmds as cmds
                if cmds.about(batch=True):
                    raise RuntimeError("batch mode, prefer filesystem fallback")
                return Path(cmds.internalVar(userAppDir=True))
            except Exception as e:
                logger.debug(f"Got Maya preferences path from outside Maya. Reason: {e}")
                return Paths.get_home_dir() / "Documents" / "maya"
        elif system == SystemInfo.OS_MAC:
            return Paths.get_home_dir() / "Library" / "Preferences" / "Autodesk" / "maya"
        elif system == SystemInfo.OS_LINUX:
            logger.warning("Maya preferences root resolution is not implemented for Linux yet.")
            return None
        else:
            logger.warning(f'Unable to resolve Maya preferences root. Unknown system: "{system}"')
            return None

    @classmethod
    def get_available_installs(cls, *, system: str | None = None) -> dict[str, Path]:
        """{"2024": Path(".../Maya2024")} — все найденные установки Maya."""
        system = system or SystemInfo.get_system()
        install_root = cls.get_install_root(system=system)
        if install_root is None or not install_root.exists():
            logger.warning(f'Unable to find Maya installs. Missing or invalid path: "{install_root}"')
            return {}

        found = {}
        for entry in install_root.iterdir():
            if entry.is_dir() and re.match(r"^maya[0-9]{4}$", entry.name.lower()):
                version = re.sub(r"[^0-9]", "", entry.name)
                found[version] = entry
        return found

    @classmethod
    def get_available_preferences(cls, *, system: str | None = None,
                                   use_maya_commands: bool = False) -> dict[str, Path]:
        """{"2024": Path(".../maya/2024")} — все найденные папки препочтений по версиям."""
        preferences_root = cls.get_preferences_root(system=system, use_maya_commands=use_maya_commands)
        if preferences_root is None or not preferences_root.exists():
            logger.warning(f'Unable to find Maya preferences. Missing or invalid path: "{preferences_root}"')
            return {}

        found = {}
        for entry in preferences_root.iterdir():
            if entry.is_dir() and re.match(r"^[0-9]{4}$", entry.name):
                found[entry.name] = entry
        return found

    @classmethod
    def get_latest_executable(cls, preferred_version: str | None = None, *, system: str | None = None, python_executable: bool = False) -> Path | None:
        """Последняя обнаруженная версия, либо preferred_version, если она доступна."""
        system = system or SystemInfo.get_system()
        installs = cls.get_available_installs(system=system)
        if not installs:
            logger.warning("Unable to find latest Maya executable. No Maya installation detected.")
            return None

        version = preferred_version if preferred_version in installs else max(installs)
        executable = cls.get_executable_path(version, system=system, python_executable=python_executable)
        if executable is None or not executable.exists():
            logger.warning(f'Unable to find Maya executable. Missing path: "{executable}"')
            return None
        return executable

if __name__ == "__main__":
    version = '2026'
    print(f"Instal root {MayaPaths.get_install_root()}")
    print(f"executable path maya.exe    exemple {version} {MayaPaths.get_executable_path(version)}")
    print(f"executable path mayapy.exe  exemple {version} {MayaPaths.get_executable_path(version, python_executable=True)}")
    print(f"available installs maya {MayaPaths.get_available_installs()}")
    print(f"preferences root {MayaPaths.get_preferences_root(use_maya_commands=True)}")
    print(f"available preferences maya {MayaPaths.get_available_preferences()}")
    print(f"latest_executable maya {MayaPaths.get_latest_executable()}")
    print(f"latest_executable mayapy {MayaPaths.get_latest_executable(python_executable=True)}")