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
                       chrome_background="#f1f3f5",
                       accent="#2f7dd1",
                       success="#4caf50",
                       warning="#ff9800",
                       error="#f44336"),

        "dark" : Theme(name="dark",
                       text_primary="#e8e8e8",
                       text_secondary="#9a9a9a",
                       border="#4a4a4a",
                       surface="#2b2b2b",
                       chrome_background="#3f4652",
                       accent="#4d96ff",
                       success="#5fbf6b",
                       warning="#ffab40",
                       error="#ff5c4d"),
    }

    DEFAULT_THEME_NAME = "light"

    def __init__(self, themes_dir: str | Path, logger: logging.Logger | None = None):
        self._themes_dir = Path(themes_dir)
        self._logger = logger or logging.getLogger(__name__)
        self._loaded_themes: dict[str, Theme] | None = None

    @classmethod
    def fallback(cls, name: str = DEFAULT_THEME_NAME) -> Theme:
        return cls._FALLBACK_THEMES.get(name, cls._FALLBACK_THEMES[cls.DEFAULT_THEME_NAME])

    def get(self, name: str) -> Theme:
        self._ensure_loaded()
        theme = self._loaded_themes.get(name) or self._FALLBACK_THEMES.get(name)
        if theme is not None:
            return theme
        self._logger.warning(f'Unknown theme "{name}". Falling back to "{self.DEFAULT_THEME_NAME}".')
        return self._FALLBACK_THEMES[self.DEFAULT_THEME_NAME]

    def list_themes(self) -> list[str]:
        self._ensure_loaded()
        return sorted(set(self._FALLBACK_THEMES) | set(self._loaded_themes))

    def _ensure_loaded(self) -> None:
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
        if not isinstance(tokens, dict):
            self._logger.warning(f'Skipping malformed theme "{name}" in themes.json: expected an object.')
            return None

        base = self._FALLBACK_THEMES[self.DEFAULT_THEME_NAME]
        return Theme(name=name,
                     text_primary=tokens.get("text_primary", base.text_primary),
                     text_secondary=tokens.get("text_secondary", base.text_secondary),
                     border=tokens.get("border", base.border),
                     surface=tokens.get("surface", base.surface),
                     chrome_background=tokens.get("chrome_background", base.chrome_background),
                     accent=tokens.get("accent", base.accent),
                     success=tokens.get("success", base.success),
                     warning=tokens.get("warning", base.warning),
                     error=tokens.get("error", base.error))