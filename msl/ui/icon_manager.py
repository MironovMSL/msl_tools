import msl_tools.msl.ui.qt_bindings as qt
import logging
from pathlib import Path


class IconManager:
    # Определяем приоритет форматов: сначала вектор, потом растр
    SUPPORTED_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg"]

    def __init__(self, base_dir: Path, theme: str = "light", logger: logging.Logger | None = None):
        self._base_dir = Path(base_dir)
        self._theme = theme
        self._logger = logger or logging.getLogger(__name__)
        self._icon_cache: dict[tuple, qt.QtGui.QIcon] = {}  # key: (name, theme, sub_folder)
        self._pixmap_cache: dict[tuple, qt.QtGui.QPixmap] = {}  # key: (name, theme, size, sub_folder)

    def set_theme(self, theme: str) -> None:
        self._theme = theme

    def get_icon(self, name: str, sub_folder: str | None = None) -> qt.QtGui.QIcon | None:
        key = (name, self._theme, sub_folder)
        if key not in self._icon_cache:
            path = self._get_icon_path(name, sub_folder=sub_folder)
            if path is None:
                return None
            self._icon_cache[key] = qt.QtGui.QIcon(str(path))
        return self._icon_cache[key]

    def get_pixmap(self, name: str, size: int, sub_folder: str | None = None) -> qt.QtGui.QPixmap | None:
        key = (name, self._theme, size, sub_folder)
        if key not in self._pixmap_cache:
            icon = self.get_icon(name, sub_folder)
            if icon is None:
                return None
            self._pixmap_cache[key] = icon.pixmap(size, size)
        return self._pixmap_cache[key]

    def _get_icon_path(self, name: str, sub_folder: str | None = None) -> Path | None:
        base = self._base_dir / (sub_folder or "")

        # 1. Сначала ищем файл с учетом темы (например, "search_light.svg", "search_light.png")
        for ext in self.SUPPORTED_EXTENSIONS:
            themed_path = base / f"{name}_{self._theme}{ext}"
            if themed_path.exists():
                return themed_path

        # 2. Если тематический файл не найден, ищем дефолтный (fallback) без суффикса темы
        for ext in self.SUPPORTED_EXTENSIONS:
            fallback_path = base / f"{name}{ext}"
            if fallback_path.exists():
                return fallback_path

        # 3. Если не нашли вообще ничего — логируем ошибку/предупреждение и возвращаем None
        self._logger.error(
            f"Icon not found: '{name}' in '{base}'. "
            f"Tried extensions {self.SUPPORTED_EXTENSIONS} with theme='{self._theme}' and fallback."
        )
        return None