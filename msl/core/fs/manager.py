# msl/core/fs/manager.py
import logging
from pathlib import Path

from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.fs.system_info import SystemInfo
from msl_tools.msl.core.fs.qt_paths import QtPaths
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.core.fs.files import Files


class FileSystemManager:
    """Единая точка входа в fs/."""

    ROOT_DIR = Path(__file__).resolve().parents[3]
    msl      = ROOT_DIR / 'msl'
    configs  = ROOT_DIR / 'configs'
    logs     = ROOT_DIR / 'logs'

    core     = msl / 'core'
    tools    = msl / 'tools'
    assets   = msl / 'assets'

    icons    = assets / 'icons'

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)

        self.paths     = Paths
        self.system    = SystemInfo
        self.qtPaths   = QtPaths
        self.mayaPaths = MayaPaths
        self.files     = Files(logger=self._logger)

    def __call__(self, path: str | Path, encoding: str = 'utf-8'):
        return self.files(path, encoding=encoding)


if __name__ == "__main__":
    fs = FileSystemManager()
    print(fs.icons)