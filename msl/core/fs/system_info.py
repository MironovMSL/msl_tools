# msl/core/fs/system.py
import sys


class SystemInfo:
    """OS detection. Stateless and independent of everything else in fs/ —
    a separate module precisely to avoid a circular import between
    FileSystemManager and MayaPaths."""

    OS_MAC        = "darwin"
    OS_LINUX      = "linux"
    OS_WINDOWS    = "win32"
    KNOWN_SYSTEMS = (OS_WINDOWS, OS_MAC, OS_LINUX)

    @classmethod
    def get_system(cls) -> str:
        return sys.platform

    @classmethod
    def is_windows(cls) -> bool:
        return cls.get_system() == cls.OS_WINDOWS

    @classmethod
    def is_macos(cls) -> bool:
        return cls.get_system() == cls.OS_MAC

    @classmethod
    def is_linux(cls) -> bool:
        return cls.get_system() == cls.OS_LINUX