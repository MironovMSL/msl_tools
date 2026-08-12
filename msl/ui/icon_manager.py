# ui/icon_manager.py
import logging
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry


# Type aliases purely for readability of the cache dict signatures below.
_IconCacheKey = tuple[str, str, str | None]
_PixmapCacheKey = tuple[str, str, int, str | None]


class IconManager:
    """Resolves icon names to theme-aware QIcon/QPixmap instances, with
    file-based theming: an icon can have per-theme variants on disk
    (e.g. "search_light.svg", "search_dark.svg"), falling back to a
    theme-less default file ("search.svg") when no themed variant exists.

    Vector formats are tried before raster ones (see SUPPORTED_EXTENSIONS)
    so a .svg always wins over a .png of the same name.

    Every lookup is cached with a composite key that includes the current
    theme, so switching themes (via set_theme()) never returns a stale
    icon for a name that has a themed variant — the next get_icon() call
    for that name simply misses the cache and resolves the new theme's
    file instead.
    """

    SUPPORTED_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg"]

    def __init__(self,
                 base_dir: str | Path,
                 theme: str = ThemeRegistry.DEFAULT_THEME_NAME,
                 logger: logging.Logger | None = None):
        """
        Args:
            base_dir: Root folder icons are looked up under (e.g. assets/icons).
            theme: Initial theme name used to resolve themed file variants.
                Purely a filename-matching key here — not validated against
                ThemeRegistry, since IconManager doesn't know about Theme
                objects, only theme *names*.
            logger: Optional logger; a module-level logger is used if omitted.
        """
        self._base_dir = Path(base_dir)
        self._theme = theme
        self._logger = logger or logging.getLogger(__name__)
        self._icon_cache: dict[_IconCacheKey, qt.QtGui.QIcon] = {}
        self._pixmap_cache: dict[_PixmapCacheKey, qt.QtGui.QPixmap] = {}

    def set_theme(self, theme: str) -> None:
        """Switches the theme used to resolve icon file variants.

        Doesn't touch the cache: existing entries key on theme already, so
        old-theme icons simply become unreachable (not re-fetched) and
        new-theme icons get resolved lazily on their next get_icon() call.
        """
        self._theme = theme

    def get_icon(self, name: str, sub_folder: str | None = None) -> qt.QtGui.QIcon | None:
        """Returns the QIcon for `name` under the current theme, or None if
        no matching file (themed or fallback) exists.

        Args:
            name: Icon name without extension or theme suffix, e.g. "search".
            sub_folder: Optional sub-folder under base_dir to look in.
        """
        key: _IconCacheKey = (name, self._theme, sub_folder)
        if key not in self._icon_cache:
            path = self._get_icon_path(name, sub_folder=sub_folder)
            if path is None:
                return None
            self._icon_cache[key] = qt.QtGui.QIcon(str(path))
        return self._icon_cache[key]

    def get_pixmap(self, name: str, size: int, sub_folder: str | None = None) -> qt.QtGui.QPixmap | None:
        """Returns a square QPixmap for `name` at `size` px, or None if the
        icon can't be resolved (see get_icon)."""
        key: _PixmapCacheKey = (name, self._theme, size, sub_folder)
        if key not in self._pixmap_cache:
            icon = self.get_icon(name, sub_folder)
            if icon is None:
                return None
            self._pixmap_cache[key] = icon.pixmap(size, size)
        return self._pixmap_cache[key]

    def _get_icon_path(self, name: str, sub_folder: str | None = None) -> Path | None:
        """Resolves `name` to a file path on disk.

        Lookup order: every supported extension with the current theme
        suffix first (e.g. "name_light.svg", then "name_light.png", ...),
        then every supported extension without a theme suffix at all
        ("name.svg", "name.png", ...). A themed match always wins over an
        unthemed one, regardless of extension.

        Returns:
            The resolved Path, or None if nothing matched (logged as a
            warning — a missing icon is a recoverable, expected-to-happen
            situation, not an error).
        """
        base = self._base_dir / (sub_folder or "")

        for ext in self.SUPPORTED_EXTENSIONS:
            themed_path = base / f"{name}_{self._theme}{ext}"
            if themed_path.exists():
                return themed_path

        for ext in self.SUPPORTED_EXTENSIONS:
            fallback_path = base / f"{name}{ext}"
            if fallback_path.exists():
                return fallback_path

        self._logger.warning(
            f"Icon not found: '{name}' in '{base}'. "
            f"Tried extensions {self.SUPPORTED_EXTENSIONS} with theme='{self._theme}' and fallback."
        )
        return None


if __name__ == "__main__":
    manager = IconManager(Path(__file__).resolve().parents[1] / "assets" / "icons")
    print(manager.get_icon("test"))  # None + warning logged — no "test" icon exists yet