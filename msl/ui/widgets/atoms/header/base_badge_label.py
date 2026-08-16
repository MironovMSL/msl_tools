import msl_tools.msl.ui.qt_bindings as qt


class BaseBadgeLabel(qt.QtWidgets.QLabel):
    """Small pill-shaped label for status/tier markers next to a window title
    (e.g. 'TRIAL', 'BETA'). Purely presentational."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            "color: #e08a2e; font-weight: 600; font-size: 10px;"
            "padding: 1px 4px;"
        )