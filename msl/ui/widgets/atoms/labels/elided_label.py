# ui/widgets/atoms/labels/elided_label.py
import msl_tools.msl.ui.qt_bindings as qt


class ElidedLabel(qt.QtWidgets.QLabel):
    """A one-line label that shortens its text with "…" when there is less
    room than the text needs — at the left, the middle or the right — and
    never asks for more width than it is given. For paths: the END of a
    path (the folder, the file) is what matters, so elide at the left.

        label = ElidedLabel("in H:/Projects/Shots/sq010/out", elide=qt.QtCore.Qt.TextElideMode.ElideLeft)

    full_text() is what was set; the tooltip shows it whenever it is cut.
    """

    def __init__(self, text: str = "", elide=None, parent=None):
        super().__init__(parent)
        self._full_text = ""
        self._elide = elide if elide is not None else qt.QtCore.Qt.TextElideMode.ElideRight
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self.setText(text)

    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = self.fontMetrics().elidedText(self._full_text, self._elide, max(self.width(), 0))
        super().setText(shown)
        self.setToolTip(self._full_text if shown != self._full_text else "")
