# ui/theme/theme_hot_reloader.py
import logging
import os
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.theme.theme_manager import ThemeManager

_LOGGER = logging.getLogger(__name__)


class ThemeHotReloader(qt.QtCore.QObject):
    """Dev tool: re-applies the theme live whenever a palette file
    (<themes_dir>/*.css) or a QSS template (base.qss, widgets.qss) is saved — pick a
    color in the editor, save, and every open window repaints.

    Reloading goes through the normal theme-change path
    (ThemeManager.reload() -> theme_changed), so it covers exactly what a
    regular theme switch covers: every window's QSS and every widget that
    listens for theme changes.

    Robust to how editors save:
    - Many save by writing a temp file and renaming it over the original;
      QFileSystemWatcher then silently stops watching that path. The
      containing folders are watched too, and the file list is re-synced
      after every event.
    - One save fires several events, and unrelated files next to the
      watched ones (e.g. __pycache__ beside base.qss) fire folder events.
      Events are debounced, and a reload only happens when the watched
      files' (mtime, size) fingerprint actually changed.

    Parented to the ThemeManager by default, so it lives as long as it does.
    """

    DEBOUNCE_MS = 150

    def __init__(self, theme_manager: ThemeManager, themes_dir: str | Path,
                 template_paths=None, parent=None):
        """
        Args:
            theme_manager: Its reload() is what repaints everything.
            themes_dir: Folder of palette files (*.css).
            template_paths: QSS templates to watch; default (None) follows
                StylesheetBuilder.template_paths(), incl. tool templates
                registered later.
            parent: Defaults to `theme_manager`.
        """
        super().__init__(parent or theme_manager)
        self._theme_manager = theme_manager
        self._themes_dir = Path(themes_dir)
        self._fixed_templates = [Path(path) for path in template_paths] if template_paths is not None else None

        self._watcher = qt.QtCore.QFileSystemWatcher(self)
        self._debounce = qt.QtCore.QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)

        self._watcher.fileChanged.connect(self._schedule)
        self._watcher.directoryChanged.connect(self._schedule)
        self._debounce.timeout.connect(self._reload_if_changed)

        self._sync_watch_list()
        self._fingerprint = self._current_fingerprint()
        names = ", ".join(path.name for path in self._template_paths())
        _LOGGER.info(f'Theme hot reload on: "{self._themes_dir}", {names}.')

    @staticmethod
    def enabled_by_default(package_root: str | Path) -> bool:
        """True in a source checkout (a .git folder next to the package),
        unless the MSL_THEME_HOT_RELOAD env var says otherwise ("0"/"1")."""
        override = os.environ.get("MSL_THEME_HOT_RELOAD")
        print(override)
        if override is not None:
            return override.strip() not in ("", "0", "false", "False")

        return (Path(package_root) / ".git").exists()

    # --- internals -----------------------------------------------------------

    def _template_paths(self) -> list[Path]:
        return self._fixed_templates if self._fixed_templates is not None else StylesheetBuilder.template_paths()

    def _watched_files(self) -> list[Path]:
        palettes = sorted(self._themes_dir.glob("*.css")) if self._themes_dir.is_dir() else []
        return palettes + [path for path in self._template_paths() if path.is_file()]

    def _sync_watch_list(self) -> None:
        wanted = {str(path) for path in self._watched_files()}
        folders = {self._themes_dir} | {path.parent for path in self._template_paths()}
        wanted |= {str(folder) for folder in folders if folder.is_dir()}
        current = set(self._watcher.files()) | set(self._watcher.directories())
        missing = sorted(wanted - current)
        if missing:
            self._watcher.addPaths(missing)

    def _current_fingerprint(self) -> tuple:
        fingerprint = []
        for path in self._watched_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            fingerprint.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(fingerprint)

    def _schedule(self, *_) -> None:
        self._debounce.start()

    def _reload_if_changed(self) -> None:
        self._sync_watch_list()  # re-watch files replaced by an atomic save
        fingerprint = self._current_fingerprint()
        if fingerprint == self._fingerprint:
            return
        changed = sorted({Path(entry[0]).name for entry in set(fingerprint) ^ set(self._fingerprint)})
        self._fingerprint = fingerprint

        StylesheetBuilder.invalidate_template()
        try:
            self._theme_manager.reload()
        except Exception as e:  # a half-written file must never take the app down
            _LOGGER.warning(f"Theme hot reload failed. Issue: {e}", exc_info=True)
            return
        _LOGGER.info(f"Theme reloaded ({', '.join(changed)}).")
        print(f"MSL: theme reloaded ({', '.join(changed)})")  # visible without logging setup
