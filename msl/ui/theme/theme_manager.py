# ui/theme/theme_manager.py
from msl_tools.msl.core.theme import Theme, ThemeRegistry

import msl_tools.msl.ui.qt_bindings as qt


class ThemeManager(qt.QtCore.QObject):
    """Holds the application's current Theme and notifies subscribers when it
    changes.

    Thin Qt wrapper around a (Qt-free) ThemeRegistry: the registry resolves
    names to Theme instances, this class tracks *which one is currently
    active* and turns that into a signal widgets can connect to. It does not
    build stylesheets itself — see StylesheetBuilder for that — and it does
    not persist the chosen theme name to disk; that's the caller's
    responsibility (e.g. the composition root that owns this instance),
    keeping this class's job to a single thing.

    Usage:
        theme_manager = ThemeManager(resources.themeRegistry, initial_theme="dark")
        theme_manager.theme_changed.connect(self._on_theme_changed)
        ...
        theme_manager.set_theme("light")
    """

    theme_changed = qt.QtCore.Signal(Theme)

    def __init__(self, registry: ThemeRegistry, initial_theme: str = ThemeRegistry.DEFAULT_THEME_NAME, parent=None):
        super().__init__(parent)

        self._registry = registry
        self._current_theme = self._registry.get(initial_theme)

    @property
    def current_theme(self) -> Theme:
        return self._current_theme

    def set_theme(self, name: str) -> None:
        theme = self._registry.get(name)
        if theme.name == self._current_theme.name:
            return
        self._current_theme = theme
        self.theme_changed.emit(theme)

    def available_themes(self) -> list[str]:
        return self._registry.list_themes()


if __name__ == "__main__":
    from pathlib import Path
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        registry = ThemeRegistry(Path(__file__).resolve().parents[3] / "assets" / "themes")
        manager = ThemeManager(registry)

        manager.theme_changed.connect(lambda theme: print(f"theme_changed -> {theme.name}"))

        manager.set_theme("dark")   # prints
        manager.set_theme("dark")   # no-op, no print
        manager.set_theme("light")  # prints