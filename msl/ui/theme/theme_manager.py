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

    # Emits the new Theme every time set_theme() actually changes it.
    theme_changed = qt.QtCore.Signal(Theme)

    def __init__(self,
                 registry: ThemeRegistry,
                 initial_theme: str = ThemeRegistry.DEFAULT_THEME_NAME,
                 parent=None):
        """
        Args:
            registry: ThemeRegistry used to resolve theme names to Theme
                instances. Injected rather than constructed here so tests can
                pass a stub/fake registry.
            initial_theme: Name of the theme to start with. Resolved through
                `registry`, so an unknown name safely falls back to
                ThemeRegistry.DEFAULT_THEME_NAME rather than raising.
            parent: Optional QObject parent.
        """
        super().__init__(parent)
        self._registry = registry
        self._current_theme = self._registry.get(initial_theme)

    @property
    def current_theme(self) -> Theme:
        """The currently active Theme."""
        return self._current_theme

    def set_theme(self, name: str) -> None:
        """Switches the active theme by name and emits `theme_changed`.

        A no-op (no signal emitted) if `name` resolves to the theme that's
        already active, so connected widgets never repaint for nothing.

        Args:
            name: Theme name to switch to. An unknown name resolves to
                ThemeRegistry.DEFAULT_THEME_NAME (see ThemeRegistry.get).
        """
        theme = self._registry.get(name)
        if theme.name == self._current_theme.name:
            return
        self._current_theme = theme
        self.theme_changed.emit(theme)

    def available_themes(self) -> list[str]:
        """Names of every theme the underlying registry currently knows
        about (hardcoded fallbacks plus anything loaded from themes.json)."""
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