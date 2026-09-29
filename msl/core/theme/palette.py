# core/theme/palette.py
"""Reads theme palette files — plain CSS custom properties:

    :root {
        --accent: #2f7dd1;   /* comments are fine */
    }

Only `--name: value;` declarations are read; selectors and comments are
ignored. Keeping the files valid CSS (instead of JSON) is the point: code
editors show color swatches and a color picker for them.
"""
import re
from pathlib import Path

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_DECLARATION = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;{}]+?)\s*;")


def parse_palette(text: str) -> dict[str, str]:
    """`{"accent": "#2f7dd1", ...}` from palette text (names without the `--`).
    A name declared twice keeps its last value, like CSS."""
    return {name: value for name, value in _DECLARATION.findall(_COMMENT.sub("", text))}


def load_palette(path: str | Path) -> dict[str, str]:
    """parse_palette() of a file (UTF-8). Raises OSError if it can't be read."""
    return parse_palette(Path(path).read_text(encoding="utf-8"))


def token_to_field(token: str) -> str:
    """Palette token -> Theme field name: "text-primary" -> "text_primary"."""
    return token.replace("-", "_")
