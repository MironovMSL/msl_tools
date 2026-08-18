# ui/icon_manager.py
import logging
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry


_IconCacheKey = tuple[str, str, str | None]
_ColoredIconCacheKey = tuple[str, str, str | None, str]
_PixmapCacheKey = tuple[str, str, int, str | None, str | None]


class IconManager:
    """Resolves icon names to theme-aware QIcon/QPixmap instances.

    Two independent theming mechanisms, usable together or separately:

    1. File-variant theming: an icon can have per-theme files on disk
       (e.g. "search_dark.svg", "search_light.svg"), falling back to a
       theme-less default ("search.svg"). Use this when the icon's *shape*
       genuinely differs by theme, not just its color.

    2. Runtime color substitution: pass `color=` to get_icon()/get_pixmap()
       to recolor an SVG on the fly. The source SVG must contain a literal
       PLACEHOLDER_COLOR (default "#000000") instead of `currentColor` —
       Qt does not resolve CSS currentColor when rendering SVG to a pixmap,
       so the placeholder is replaced with the requested hex via plain text
       substitution before rendering. This is what lets a single icon file
       track a Theme token (e.g. text_primary) instead of needing a
       pre-exported file per theme, and also covers state-driven colors
       that aren't theme-bound at all (e.g. a fixed hover color).

    Vector formats are tried before raster ones (see SUPPORTED_EXTENSIONS)
    so a .svg always wins over a .png of the same name. Color substitution
    only applies to .svg matches — requesting `color=` for a raster icon
    logs a warning and falls back to the uncolored icon.
    """

    SUPPORTED_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg"]
    PLACEHOLDER_COLOR = "#000000"
    RENDER_SIZE = 64  # master resolution colored SVGs are rendered at; QIcon scales down from this on demand

    def __init__(self,
                 base_dir: str | Path,
                 theme: str = ThemeRegistry.DEFAULT_THEME_NAME,
                 logger: logging.Logger | None = None):
        self._base_dir = Path(base_dir)
        self._theme = theme
        self._logger = logger or logging.getLogger(__name__)
        self._icon_cache: dict[_IconCacheKey, qt.QtGui.QIcon] = {}
        self._colored_icon_cache: dict[_ColoredIconCacheKey, qt.QtGui.QIcon] = {}
        self._pixmap_cache: dict[_PixmapCacheKey, qt.QtGui.QPixmap] = {}

    def set_theme(self, theme: str) -> None:
        """Switches the theme used to resolve icon file variants.

        Doesn't touch the cache: existing entries key on theme already, so
        old-theme icons simply become unreachable (not re-fetched) and
        new-theme icons get resolved lazily on their next get_icon() call.
        """
        self._theme = theme

    def get_icon(self, name: str, sub_folder: str | None = None,
                 color: str | None = None) -> qt.QtGui.QIcon | None:
        """Returns the QIcon for `name` under the current theme, or None if
        no matching file (themed or fallback) exists.

        Args:
            name: Icon name without extension or theme suffix, e.g. "search".
            sub_folder: Optional sub-folder under base_dir to look in.
            color: Optional hex color (e.g. "#e4e9f2"). When given, the
                resolved SVG's PLACEHOLDER_COLOR is substituted with this
                value before rendering. Ignored (with a warning) for
                non-SVG matches.
        """
        if color is None:
            return self._get_uncolored_icon(name, sub_folder)
        return self._get_colored_icon(name, sub_folder, color)

    def get_pixmap(self, name: str, size: int, sub_folder: str | None = None,
                    color: str | None = None) -> qt.QtGui.QPixmap | None:
        """Returns a square QPixmap for `name` at `size` px, or None if the
        icon can't be resolved (see get_icon)."""
        key: _PixmapCacheKey = (name, self._theme, size, sub_folder, color)
        if key not in self._pixmap_cache:
            icon = self.get_icon(name, sub_folder, color=color)
            if icon is None:
                return None
            self._pixmap_cache[key] = icon.pixmap(size, size)
        return self._pixmap_cache[key]

    # --- Uncolored (file-variant only) lookup ---

    def _get_uncolored_icon(self, name: str, sub_folder: str | None) -> qt.QtGui.QIcon | None:
        key: _IconCacheKey = (name, self._theme, sub_folder)
        if key not in self._icon_cache:
            path = self._get_icon_path(name, sub_folder=sub_folder)
            if path is None:
                return None
            self._icon_cache[key] = qt.QtGui.QIcon(str(path))
        return self._icon_cache[key]

    # --- Colored (runtime substitution) lookup ---

    def _get_colored_icon(self, name: str, sub_folder: str | None, color: str) -> qt.QtGui.QIcon | None:
        key: _ColoredIconCacheKey = (name, self._theme, sub_folder, color)
        if key in self._colored_icon_cache:
            return self._colored_icon_cache[key]

        path = self._get_icon_path(name, sub_folder=sub_folder)
        if path is None:
            return None

        if path.suffix.lower() != ".svg":
            self._logger.warning(
                f"Color substitution requested for '{name}' but resolved file "
                f"'{path.name}' isn't an SVG — returning the uncolored icon instead."
            )
            return self._get_uncolored_icon(name, sub_folder)

        svg_text = path.read_text(encoding="utf-8")
        if self.PLACEHOLDER_COLOR not in svg_text:
            self._logger.warning(
                f"Icon '{name}' has no '{self.PLACEHOLDER_COLOR}' placeholder — "
                f"color substitution will have no visible effect."
            )
        recolored_svg = svg_text.replace(self.PLACEHOLDER_COLOR, color)

        pixmap = self._render_svg_to_pixmap(recolored_svg)
        if pixmap is None:
            return None

        icon = qt.QtGui.QIcon(pixmap)
        self._colored_icon_cache[key] = icon
        return icon

    def _render_svg_to_pixmap(self, svg_text: str) -> qt.QtGui.QPixmap | None:
        renderer = qt.QtSvg.QSvgRenderer(qt.QtCore.QByteArray(svg_text.encode("utf-8")))
        if not renderer.isValid():
            self._logger.warning("Failed to render recolored SVG — invalid SVG content after substitution.")
            return None

        pixmap = qt.QtGui.QPixmap(self.RENDER_SIZE, self.RENDER_SIZE)
        pixmap.fill(qt.QtCore.Qt.GlobalColor.transparent)

        painter = qt.QtGui.QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    def _get_icon_path(self, name: str, sub_folder: str | None = None) -> Path | None:
        """Resolves `name` to a file path on disk. Lookup order: themed
        variant per extension, then unthemed fallback per extension."""
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