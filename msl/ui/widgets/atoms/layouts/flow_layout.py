# ui/widgets/atoms/layouts/flow_layout.py
import msl_tools.msl.ui.qt_bindings as qt


class FlowLayout(qt.QtWidgets.QLayout):
    """Lays its items out like words in a paragraph: left to right, wrapping
    to a new line when the row is full. The height follows the width
    (height-for-width), so a container of chips grows downwards instead of
    widening its window. Hidden widgets take no room.

        layout = FlowLayout(container, spacing=6)
        layout.addWidget(chip)
    """

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return qt.QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(qt.QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> qt.QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> qt.QtCore.QSize:
        size = qt.QtCore.QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + qt.QtCore.QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect, apply: bool) -> int:
        """Places the items inside `rect` (only when `apply`) and returns the height they take."""
        margins = self.contentsMargins()
        left, right = rect.x() + margins.left(), rect.right() - margins.right()
        x, y, row_height = left, rect.y() + margins.top(), 0
        for item in self._items:
            if item.isEmpty():  # a hidden widget
                continue
            hint = item.sizeHint()
            if x > left and x + hint.width() - 1 > right:
                x, y, row_height = left, y + row_height + self.spacing(), 0
            if apply:
                item.setGeometry(qt.QtCore.QRect(qt.QtCore.QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()
