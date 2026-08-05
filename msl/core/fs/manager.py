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

    ROOT_DIR   = Path(__file__).resolve().parents[3]
    PARENT_DIR = ROOT_DIR.parent

    msl      = ROOT_DIR / 'msl'
    configs  = ROOT_DIR / 'configs' / 'maya'
    logs     = ROOT_DIR / 'logs' / 'maya'

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


    def _get_icon_path(self, name: str, theme: str = "light", sub_folder: str | None = None) -> Path | None:
        SUPPORTED_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg"]
        base = self.icons / (sub_folder or "")
        theme = theme

        # 1. Сначала ищем файл с учетом темы (например, "search_light.svg", "search_light.png")
        for ext in SUPPORTED_EXTENSIONS:
            themed_path = base / f"{name}_{theme}{ext}"
            if themed_path.exists():
                return themed_path

        # 2. Если тематический файл не найден, ищем дефолтный (fallback) без суффикса темы
        for ext in SUPPORTED_EXTENSIONS:
            fallback_path = base / f"{name}{ext}"
            if fallback_path.exists():
                return fallback_path

        # 3. Если не нашли вообще ничего — логируем ошибку/предупреждение и возвращаем None
        self._logger.error(
            f"Icon not found: '{name}' in '{base}'.\n"
            f"Tried extensions {SUPPORTED_EXTENSIONS} with theme='{theme}' and fallback."
        )
        return None

if __name__ == "__main__":
    fs = FileSystemManager()
    print(fs._get_icon_path("test"))