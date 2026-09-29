# core/theme/theme.py
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Theme:
    """Immutable set of semantic color tokens for a single UI theme.

    Built from a palette file (assets/themes/<name>.css, see ThemeRegistry);
    the palette file is the only place the actual colors live.

    Tokens are named by their UI role, not by their appearance — a widget
    should reference `theme.accent` or `theme.error`, never a literal hex
    string. That's what makes switching themes a matter of swapping one
    Theme instance for another, instead of touching widget code.

    Two layers:
    - The typed fields below are the tokens Python widgets read directly
      (custom-painted atoms). Palette token `--text-primary` fills field
      `text_primary`. Add a field only once Python code needs the token.
    - `tokens` holds EVERY palette declaration by its palette name
      ("text-primary", ...). That's what the QSS template (ui/theme/
      base.qss) resolves var(--name) against — so a color used only in QSS
      needs just a line in the palette files, no change here.

    Attributes:
        name: Unique theme identifier, e.g. "light", "dark" — the palette
            file's name.
        text_primary: Main/high-emphasis text color.
        text_secondary: Muted/low-emphasis text color (labels, hints).
        border: Default border color for outlined widgets.
        surface: Background color for windows and recessed surfaces.
        chrome_background: Window chrome (header) background.
        accent: Default/neutral brand color.
        success: Semantic "good/complete" color.
        warning: Semantic "needs attention" color.
        error: Semantic "bad/failed" color.
        tokens: All palette declarations, palette-named.
    """
    name: str
    text_primary: str
    text_secondary: str
    border: str
    surface: str
    chrome_background: str
    accent: str
    success: str
    warning: str
    error: str
    tokens: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False, repr=False)
