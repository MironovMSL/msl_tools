# ui/theme/stylesheet_builder.py
import logging
import re
from pathlib import Path

from msl_tools.msl.core.theme import Theme

_LOGGER  = logging.getLogger(__name__)

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_VAR     = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*\)")
_ALPHA   = re.compile(r"alpha\(\s*(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})\s*,\s*(\d+(?:\.\d+)?)\s*%\s*\)")


class StylesheetBuilder:
    """Builds the global Qt stylesheet (QSS) for a Theme from the templates
    ui/theme/base.qss (plain Qt controls) + ui/theme/widgets.qss (custom
    widgets' qproperty colors and state selectors) + any tool templates
    added with register_template().

    The templates hold all rules; colors in them are only `var(--token)`
    references, resolved against `theme.tokens` (the theme's palette file,
    assets/themes/<name>.css). QSS itself has no variables — this is the
    small preprocessor that adds them:
      - /* comments */ are stripped;
      - var(--token) -> the palette value (unknown token: logged, and
        replaced by `transparent` — an unresolved var() would make Qt
        reject the whole stylesheet);
      - alpha(<#hex>, <n>%) -> rgba(r, g, b, a), for translucent variants.

    Stateless by design — a plain namespace (same pattern as core.fs.Paths).
    The template is read once and cached; invalidate_template() drops the
    cache (ThemeHotReloader does that when a template is saved).

    Meant to be applied per top-level window on every theme change, e.g.:
        window.setStyleSheet(StylesheetBuilder.build(theme))
    Never on QApplication: inside Maya that is Maya's own application object,
    and a global stylesheet would restyle Maya's whole UI.
    """

    # Concatenated in this order: plain Qt controls first, then the custom
    # widgets' rules (qproperty-* colors, state selectors) — see ui/theme/qss.py.
    TEMPLATE_PATHS = (
        Path(__file__).resolve().with_name("base.qss"),
        Path(__file__).resolve().with_name("widgets.qss"),
    )
    _extra_templates: list[Path] = []
    _template: str | None = None

    @classmethod
    def register_template(cls, path: str | Path) -> None:
        """Adds a tool's own QSS template (e.g. tools/desktop/maya_gate/
        maya_gate.qss) after the built-in ones — so tool-specific rules
        live with the tool, not in ui/. Register at import time, before the
        first window builds its stylesheet. Idempotent."""
        path = Path(path).resolve()
        if path not in cls._extra_templates:
            cls._extra_templates.append(path)
            cls.invalidate_template()

    @classmethod
    def template_paths(cls) -> list[Path]:
        """Every template build() concatenates, in order."""
        return [*cls.TEMPLATE_PATHS, *cls._extra_templates]

    @classmethod
    def build(cls, theme: Theme) -> str:
        return cls.render(cls._load_template(), theme)

    @staticmethod
    def render(template: str, theme: Theme) -> str:
        """Resolves a QSS template against `theme`."""
        unknown: set[str] = set()

        def resolve_var(match: re.Match) -> str:
            value = theme.tokens.get(match.group(1))
            if value is None:
                unknown.add(match.group(1))
                return "transparent"
            return value

        qss = _VAR.sub(resolve_var, _COMMENT.sub("", template))
        qss = _ALPHA.sub(StylesheetBuilder._resolve_alpha, qss)
        if unknown:
            _LOGGER.warning(f'Theme "{theme.name}" has no token(s) {sorted(unknown)} used in the stylesheet.')
        return qss

    @classmethod
    def invalidate_template(cls) -> None:
        """Drops the cached templates; the next build() re-reads them."""
        cls._template = None

    @classmethod
    def _load_template(cls) -> str:
        if cls._template is None:
            cls._template = "\n".join(path.read_text(encoding="utf-8") for path in cls.template_paths())
        return cls._template

    @staticmethod
    def _resolve_alpha(match: re.Match) -> str:
        hex_digits = match.group(1)[1:]
        if len(hex_digits) == 3:
            hex_digits = "".join(digit * 2 for digit in hex_digits)
        red, green, blue = (int(hex_digits[i:i + 2], 16) for i in (0, 2, 4))
        alpha = round(255 * min(float(match.group(2)), 100.0) / 100.0)
        return f"rgba({red}, {green}, {blue}, {alpha})"


if __name__ == "__main__":
    from msl_tools.msl.core.theme import ThemeRegistry

    print(StylesheetBuilder.build(ThemeRegistry(ThemeRegistry.BUNDLED_THEMES_DIR).get("dark")))
