"""Placeholder tool page used only to validate hub navigation."""
from __future__ import annotations

import msl_tools.msl.ui.qt_bindings as qt


class StubToolWidget(qt.QtWidgets.QWidget):
    """Minimal placeholder page shown in the hub's content area.

    Args:
        label: Text displayed in the placeholder, so stub pages can be
            told apart while testing navigation.
        parent: Optional parent widget.
    """

    def __init__(self, label: str, parent=None) -> None:
        super().__init__(parent)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.addWidget(qt.QtWidgets.QLabel(label, self))
        layout.addWidget(qt.QtWidgets.QPushButton(label))
        layout.addStretch()