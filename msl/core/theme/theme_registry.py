import dataclasses
import logging
from pathlib import Path
from types import MappingProxyType

from msl_tools.msl.core.theme.palette import load_palette, token_to_field
from msl_tools.msl.core.theme.theme import Theme

_LOGGER = logging.getLogger(__name__)

# Theme's color fields, in palette naming ("text-primary", ...).
_REQUIRED_TOKENS = tuple(f.name.replace("_", "-") for f in dataclasses.fields(Theme)
                         if f.name not in ("name", "tokens"))


class ThemeRegistry:
    """Resolves theme names to Theme instances, read from palette files.

    Every `<name>.css` in the themes folder is a theme (see core/theme/
    palette.py for the format). The palette files are the ONLY place colors
    live — there's no second copy in code to drift out of sync with them.

    A palette may leave tokens out; those take the "light" palette's value,
    so a new theme can start as a few overrides. Tokens beyond Theme's
    fields are kept too (Theme.tokens) for the QSS template.
    """

    DEFAULT_THEME_NAME = "light"
    PALETTE_SUFFIX = ".css"
    BUNDLED_THEMES_DIR = Path(__file__).resolve().parents[2] / "assets" / "themes"

    # Last resort only — used if the bundled palette files themselves are
    # missing or unreadable (a broken install), so widgets still construct.
    # Deliberately bland: this is not a theme, and not a copy of one.
    _EMERGENCY_TOKENS = {
        "text-primary": "#000000", "text-secondary": "#808080", "border": "#808080",
        "surface": "#ffffff", "chrome-background": "#e0e0e0", "accent": "#3070d0",
        "success": "#40a040", "warning": "#e09020", "error": "#e04040",
    }

    _bundled_cache: dict[str, Theme] = {}

    def __init__(self, themes_dir: str | Path, logger: logging.Logger | None = None):
        self._themes_dir = Path(themes_dir)
        self._logger = logger or _LOGGER
        self._loaded_themes: dict[str, Theme] | None = None

    # --- widget defaults (no registry instance needed) -----------------------

    @classmethod
    def fallback(cls, name: str = DEFAULT_THEME_NAME) -> Theme:
        """Theme `name` from the BUNDLED palettes — the default for widgets
        constructed without an explicit theme. Read once per name, then
        cached; unknown names give the default theme."""
        theme = cls._bundled_cache.get(name)
        if theme is None:
            path = cls.BUNDLED_THEMES_DIR / f"{name}{cls.PALETTE_SUFFIX}"
            if not path.is_file() and name != cls.DEFAULT_THEME_NAME:
                return cls.fallback(cls.DEFAULT_THEME_NAME)
            theme = cls._theme_from_file(name, path, _LOGGER) or cls._build_theme(name, {}, _LOGGER)
            cls._bundled_cache[name] = theme
        return theme

    # --- registry --------------------------------------------------------------

    @property
    def themes_dir(self) -> Path:
        return self._themes_dir

    def reload(self) -> None:
        """Forgets every parsed palette (this registry's and the bundled
        fallback cache), so the next get()/fallback() re-reads the files.
        For live theme editing — see ui/theme/theme_hot_reloader.py."""
        self._loaded_themes = None
        ThemeRegistry._bundled_cache.clear()

    def get(self, name: str) -> Theme:
        self._ensure_loaded()
        theme = self._loaded_themes.get(name)
        if theme is not None:
            return theme
        self._logger.warning(f'Unknown theme "{name}". Falling back to "{self.DEFAULT_THEME_NAME}".')
        return self._loaded_themes.get(self.DEFAULT_THEME_NAME) or self.fallback()

    def list_themes(self) -> list[str]:
        self._ensure_loaded()
        return sorted(self._loaded_themes)

    def _ensure_loaded(self) -> None:
        if self._loaded_themes is not None:
            return
        self._loaded_themes = {}
        paths = sorted(self._themes_dir.glob(f"*{self.PALETTE_SUFFIX}")) if self._themes_dir.is_dir() else []
        if not paths:
            self._logger.warning(f'No theme palettes (*{self.PALETTE_SUFFIX}) in "{self._themes_dir}". '
                                 f"Using the bundled defaults.")
        # The default palette first: the others inherit missing tokens from
        # THIS folder's default, falling back to the bundled one if it has none.
        paths.sort(key=lambda path: path.stem != self.DEFAULT_THEME_NAME)
        base = None
        for path in paths:
            theme = self._theme_from_file(path.stem, path, self._logger, base)
            if theme is not None:
                self._loaded_themes[path.stem] = theme
                if path.stem == self.DEFAULT_THEME_NAME:
                    base = dict(theme.tokens)

    # --- building --------------------------------------------------------------

    @classmethod
    def _theme_from_file(cls, name: str, path: Path, logger: logging.Logger,
                         base: dict[str, str] | None = None) -> Theme | None:
        try:
            tokens = load_palette(path)
        except OSError as e:
            logger.warning(f'Unable to read theme palette "{path}". Issue: {e}')
            return None
        return cls._build_theme(name, tokens, logger, base)

    @classmethod
    def _build_theme(cls, name: str, tokens: dict[str, str], logger: logging.Logger,
                     base: dict[str, str] | None = None) -> Theme:
        """Theme from palette tokens; tokens it lacks come from `base` —
        by default the bundled default palette (or, for the default palette
        itself, the emergency set)."""
        if name == cls.DEFAULT_THEME_NAME:
            base = cls._EMERGENCY_TOKENS
        elif base is None:
            base = dict(cls.fallback(cls.DEFAULT_THEME_NAME).tokens)

        missing = [token for token in _REQUIRED_TOKENS if token not in tokens]
        if missing and name == cls.DEFAULT_THEME_NAME:
            # The base every other theme inherits from — gaps here are a real problem.
            logger.warning(f'Default theme "{name}" is missing {missing}; using emergency values.')
        elif missing:
            # Normal for a theme written as a few overrides.
            logger.debug(f'Theme "{name}" inherits {missing} from "{cls.DEFAULT_THEME_NAME}".')

        merged = {**base, **tokens}
        colors = {token_to_field(token): merged[token] for token in _REQUIRED_TOKENS}
        return Theme(name=name, tokens=MappingProxyType(merged), **colors)
