# ui/theme/stylesheet_builder.py
import logging
import re
from pathlib import Path

from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.theme import Theme

_LOGGER  = logging.getLogger(__name__)

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_VAR     = re.compile(r"var\(\s*--([A-Za-z0-9_-]+)\s*\)")
_ALPHA   = re.compile(r"alpha\(\s*(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})\s*,\s*(\d+(?:\.\d+)?)\s*%\s*\)")
_ICON    = re.compile(r"icon\(\s*([A-Za-z0-9_/-]+)\s*,\s*(#[0-9A-Fa-f]{6})\s*\)")
_SVG_PLACEHOLDER = re.compile(r"#000000", re.IGNORECASE)  # IconManager's recolor placeholder
_GRADIENT_START = "linear-gradient("
_STOP_POSITION  = re.compile(r"^(.*?)\s+(\d+(?:\.\d+)?)%$")
# CSS "to <side>" -> (x1, y1, x2, y2) in Qt's 0..1 bounding-box coordinates.
_GRADIENT_SIDES = {"left": (1, 0), "right": (0, 1)}, {"top": (1, 0), "bottom": (0, 1)}


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
      - alpha(<#hex>, <n>%) -> rgba(r, g, b, a), for translucent variants;
      - linear-gradient([to <side>,] <color> [<n>%], ...) -> qlineargradient(...).
        Standard CSS, so editors that treat .qss as CSS parse it (Qt's own
        `qlineargradient(x1:0, ...)` is a syntax error to a CSS parser).
        Sides: top / bottom / left / right and diagonals ("to bottom right");
        default "to bottom", like CSS. Stops without a % spread evenly;
      - icon(<sub_folder/name>, <#hex>) -> url(<file>): an assets/icons SVG
        with its #000000 placeholder recolored, written once per color to a
        temp cache — for sub-control images (`QComboBox::down-arrow`), which
        QSS can only take from a file and can't tint.

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
        qss = StylesheetBuilder._resolve_gradients(qss)
        qss = _ICON.sub(StylesheetBuilder._resolve_icon, qss)
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

    ICON_CACHE_DIR = Paths.get_temp_dir() / "msl_tools" / "qss_icons"

    @classmethod
    def _resolve_icon(cls, match: re.Match) -> str:
        name, color = match.group(1), match.group(2).lower()
        source = FileSystemManager.icons / f"{name}.svg"
        if not source.is_file():
            _LOGGER.warning(f'QSS icon("{name}") not found: {source}')
            return "none"
        target = cls.ICON_CACHE_DIR / f"{name.replace('/', '__')}__{color[1:]}.svg"
        # Rewritten when the source is newer, so an edited SVG shows after a restart.
        if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_SVG_PLACEHOLDER.sub(color, source.read_text(encoding="utf-8")), encoding="utf-8")
        return f"url({target.as_posix()})"

    @staticmethod
    def _resolve_gradients(qss: str) -> str:
        """Rewrites every linear-gradient(...) into Qt's qlineargradient(...).
        Runs after var()/alpha(), so colors are already #hex / rgba(...) —
        hence the paren-aware scan instead of a regex."""
        parts, cursor = [], 0
        while (start := qss.find(_GRADIENT_START, cursor)) != -1:
            depth, end = 1, start + len(_GRADIENT_START)
            while end < len(qss) and depth:
                depth += {"(": 1, ")": -1}.get(qss[end], 0)
                end += 1
            body = qss[start + len(_GRADIENT_START):end - 1]
            parts += [qss[cursor:start], StylesheetBuilder._qt_gradient(body)]
            cursor = end
        parts.append(qss[cursor:])
        return "".join(parts)

    @staticmethod
    def _qt_gradient(body: str) -> str:
        args, depth, current = [], 0, ""
        for char in body:
            depth += {"(": 1, ")": -1}.get(char, 0)
            if char == "," and depth == 0:
                args.append(current.strip()); current = ""
            else:
                current += char
        args.append(current.strip())

        coords = {"x": (0, 0), "y": (0, 1)}  # CSS default: to bottom
        if args and args[0].startswith("to "):
            coords = {"x": (0, 0), "y": (0, 0)}
            for side in args.pop(0).split()[1:]:
                for axis, sides in zip("xy", _GRADIENT_SIDES):
                    if side in sides:
                        coords[axis] = sides[side]
        if len(args) < 2:
            _LOGGER.warning(f"linear-gradient needs two colors or more: linear-gradient({body})")
            return "transparent"

        stops = []
        for index, arg in enumerate(args):
            match = _STOP_POSITION.match(arg)
            color, position = (match.group(1), float(match.group(2)) / 100) if match \
                else (arg, index / (len(args) - 1))
            stops.append(f"stop:{position:g} {color}")
        (x1, x2), (y1, y2) = coords["x"], coords["y"]
        return f"qlineargradient(x1:{x1}, y1:{y1}, x2:{x2}, y2:{y2}, {', '.join(stops)})"

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
