# core/theme/theme_registry.py
import json
import logging
from pathlib import Path

from msl_tools.msl.core.theme.theme import Theme


class ThemeRegistry:
    """Resolves theme names to Theme instances."""

    _FALLBACK_THEMES: dict[str, Theme] = {
        "light": Theme(name="light",
                       text_primary="#0a0a0a",
                       text_secondary="#878787",
                       border="#3a3a3a",
                       surface="#e0e0e0",
                       accent="#2f7dd1",
                       success="#4caf50",
                       warning="#ff9800",
                       error="#f44336"),

        "dark" : Theme(name="dark",
                       text_primary="#e8e8e8",
                       text_secondary="#9a9a9a",
                       border="#4a4a4a",
                       surface="#2b2b2b",
                       accent="#4d96ff",
                       success="#5fbf6b",
                       warning="#ffab40",
                       error="#ff5c4d"),
    }

    DEFAULT_THEME_NAME = "light"

    def __init__(self, themes_dir: str | Path, logger: logging.Logger | None = None):
        """
        Args:
            themes_dir: Folder expected to contain "themes.json". The folder
                itself is not required to exist — a missing folder/file just
                means "no user themes", not an error.
            logger: Optional logger; a module-level logger is used if omitted.
        """
        self._themes_dir = Path(themes_dir)
        self._logger = logger or logging.getLogger(__name__)
        self._loaded_themes: dict[str, Theme] | None = None  # populated lazily, see _ensure_loaded()

    @classmethod
    def fallback(cls, name: str = DEFAULT_THEME_NAME) -> Theme:
        """Returns a hardcoded fallback Theme directly, with no file I/O and
        no instance required."""
        return cls._FALLBACK_THEMES.get(name, cls._FALLBACK_THEMES[cls.DEFAULT_THEME_NAME])

    def get(self, name: str) -> Theme:
        """Returns the Theme registered under `name`.
        Args:
            name: Theme name to resolve, e.g. "light", "dark", or a custom name.

        Returns:
            The matching Theme, or the hardcoded default theme
            (`DEFAULT_THEME_NAME`) if `name` isn't known anywhere.
        """
        self._ensure_loaded()

        theme = self._loaded_themes.get(name) or self._FALLBACK_THEMES.get(name)
        if theme is not None:
            return theme

        self._logger.warning(f'Unknown theme "{name}". Falling back to "{self.DEFAULT_THEME_NAME}".')
        return self._FALLBACK_THEMES[self.DEFAULT_THEME_NAME]

    def list_themes(self) -> list[str]:
        """Returns every known theme name: hardcoded fallbacks plus whatever
        was loaded from themes.json, sorted alphabetically."""
        self._ensure_loaded()
        return sorted(set(self._FALLBACK_THEMES) | set(self._loaded_themes))

    def _ensure_loaded(self) -> None:
        """Lazily loads and caches themes.json on first use."""

        if self._loaded_themes is not None:
            return
        self._loaded_themes = {}

        themes_path = self._themes_dir / "themes.json"
        if not themes_path.is_file():
            self._logger.debug(f'No themes.json found at "{themes_path}". Using fallback themes only.')
            return

        try:
            raw = json.loads(themes_path.read_text(encoding="utf-8"))
        except Exception as e:
            self._logger.warning(f'Unable to parse "{themes_path}". Issue: {e}')
            return

        if not isinstance(raw, dict):
            self._logger.warning(f'"{themes_path}" must contain a JSON object of {{theme_name: tokens}}.')
            return

        for name, tokens in raw.items():
            theme = self._build_theme(name, tokens)
            if theme is not None:
                self._loaded_themes[name] = theme

    def _build_theme(self, name: str, tokens: dict) -> Theme | None:
        """Builds one Theme from a themes.json entry.
        Args:
            name: Theme name (the JSON key).
            tokens: The JSON value for that key — expected to be a dict of
                token-name -> hex-color-string.

        Returns:
            A Theme, or None if `tokens` isn't a dict (logged as a warning).
        """
        if not isinstance(tokens, dict):
            self._logger.warning(f'Skipping malformed theme "{name}" in themes.json: expected an object.')
            return None

        base = self._FALLBACK_THEMES[self.DEFAULT_THEME_NAME]
        return Theme(name=name,
                     text_primary=tokens.get("text_primary", base.text_primary),
                     text_secondary=tokens.get("text_secondary", base.text_secondary),
                     border=tokens.get("border", base.border),
                     surface=tokens.get("surface", base.surface),
                     accent=tokens.get("accent", base.accent),
                     success=tokens.get("success", base.success),
                     warning=tokens.get("warning", base.warning),
                     error=tokens.get("error", base.error))


if __name__ == "__main__":
    registry = ThemeRegistry(Path(__file__).resolve().parents[2] / "assets" / "themes")

    print(registry.list_themes())
    print(registry.get("light"))
    print(registry.get("does_not_exist"))  # falls back to "light" with a warning