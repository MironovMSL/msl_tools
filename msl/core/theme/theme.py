# core/theme/theme.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """Immutable set of semantic color tokens for a single UI theme.

    Tokens are named by their UI role, not by their appearance — a widget
    should reference `theme.accent` or `theme.error`, never a literal hex
    string. That's what makes switching themes a matter of swapping one
    Theme instance for another, instead of touching widget code.

    Kept intentionally small (YAGNI): only the tokens actually needed by
    existing widgets (BaseProgressBar, VersionStatusWidget) are defined here.
    Extend with new tokens only once a widget actually needs one — resist the
    urge to pre-populate a "complete" palette speculatively.

    Attributes:
        name: Unique theme identifier, e.g. "light", "dark". Matches the key
            used to look this theme up via ThemeRegistry.
        text_primary: Main/high-emphasis text color.
        text_secondary: Muted/low-emphasis text color (labels, hints).
        border: Default border color for outlined widgets.
        surface: Background color for recessed/track surfaces (e.g. a
            progress bar's track, as opposed to its filled portion).
        accent: Default/neutral brand color (e.g. a progress bar's normal,
            non-semantic state).
        success: Semantic "good/complete" color.
        warning: Semantic "needs attention" color.
        error: Semantic "bad/failed" color.
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