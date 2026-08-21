# ui/theme/stylesheet_builder.py
from msl_tools.msl.core.theme import Theme


class StylesheetBuilder:
    """Builds a global Qt stylesheet (QSS) string from a Theme.

    Stateless by design — a plain namespace of staticmethods, held as a class
    reference rather than instantiated (same pattern as core.fs.Paths). Theme
    in, QSS string out; no I/O, no Qt object held, nothing to construct.

    Meant to be applied once per theme change, e.g.:
        QApplication.instance().setStyleSheet(StylesheetBuilder.build(theme))

    Scope is intentionally limited to the shared, static baseline for common
    controls (QDialog, QPushButton, QLineEdit, QLabel) actually used in the
    codebase today. QDialog is styled specifically — not a blanket QWidget
    rule — so nested QWidget containers inside composed widgets (e.g. the
    inner containers in InstallPathWidget/VersionStatusWidget) stay
    transparent and inherit their parent's background, instead of every
    single container suddenly becoming an opaque, theme-colored panel.

    Widgets with their own semantic/state-driven coloring —
    BaseProgressBar's NORMAL/SUCCESS/ERROR states, VersionStatusWidget's
    per-status colors — are out of scope here on purpose: those read Theme
    tokens directly to build their own small stylesheet snippets, since a
    single global QSS block can't express "color depends on this widget's
    current state". This class only establishes what every plain button,
    field, and label falls back to before any widget-specific override.
    """

    @staticmethod
    def build(theme: Theme) -> str:
        return "\n".join([
            StylesheetBuilder._dialog_style(theme),
            StylesheetBuilder._button_style(theme),
            StylesheetBuilder._line_edit_style(theme),
            StylesheetBuilder._label_style(theme),
            StylesheetBuilder._progress_bar_style(theme),
            StylesheetBuilder._window_header_style(theme),
        ])

    @staticmethod
    def _dialog_style(theme: Theme) -> str:
        return (
            "QDialog {\n"
            f"  background-color: {theme.surface};\n"
            f"  color: {theme.text_primary};\n"
            "}\n"
        )

    @staticmethod
    def _button_style(theme: Theme) -> str:
        return (
            "QPushButton {\n"
            f"  background-color: {theme.surface};\n"
            f"  color: {theme.text_primary};\n"
            f"  border: 1px solid {theme.border};\n"
            "  border-radius: 3px;\n"
            "  padding: 4px 10px;\n"
            "}\n"
            "QPushButton:hover {\n"
            f"  border: 1px solid {theme.accent};\n"
            "}\n"
            "QPushButton:pressed {\n"
            f"  background-color: {theme.accent};\n"
            f"  color: {theme.surface};\n"
            "}\n"
            "QPushButton:disabled {\n"
            f"  color: {theme.text_secondary};\n"
            f"  border: 1px solid {theme.text_secondary};\n"
            "}\n"
        )

    @staticmethod
    def _line_edit_style(theme: Theme) -> str:
        return (
            "QLineEdit {\n"
            f"  background-color: {theme.surface};\n"
            f"  color: {theme.text_primary};\n"
            f"  border: 1px solid {theme.border};\n"
            "  border-radius: 3px;\n"
            "  padding: 2px 4px;\n"
            "}\n"
            "QLineEdit:focus {\n"
            f"  border: 1px solid {theme.accent};\n"
            "}\n"
            "QLineEdit:read-only {\n"
            f"  color: {theme.text_secondary};\n"
            "}\n"
        )

    @staticmethod
    def _label_style(theme: Theme) -> str:
        return (
            "QLabel {\n"
            f"  color: {theme.text_primary};\n"
            "}\n"
        )

    @staticmethod
    def _progress_bar_style(theme: Theme) -> str:
        return (
            "QProgressBar {\n"
            f"  border: 1px solid {theme.border};\n"
            "   border-radius: 4px;\n"
            f"  background-color: {theme.surface};\n"
            "   text-align: center;\n"
            f"  color: {theme.surface};\n"
            "}\n"
            "QProgressBar::chunk {\n"
            "  border-radius: 3px;\n"
            "}\n"
        )

    @staticmethod
    def _window_header_style(theme: Theme) -> str:
        return (
            "WindowHeader {\n"
            f"  background-color: {theme.chrome_background};\n"
            "}\n"
            "QLabel#headerSubtitle {\n"
            f"  color: {theme.text_secondary};\n"
            "}\n"
        )


if __name__ == "__main__":
    from pathlib import Path
    from msl_tools.msl.core.theme import ThemeRegistry

    registry = ThemeRegistry(Path(__file__).resolve().parents[3] / "assets" / "themes")
    print(StylesheetBuilder.build(registry.get("dark")))