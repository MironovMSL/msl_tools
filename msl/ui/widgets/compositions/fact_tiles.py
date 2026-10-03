# ui/widgets/compositions/fact_tiles.py
import msl_tools.msl.ui.qt_bindings as qt


class FactTiles(qt.QtWidgets.QWidget):
    """A row of small tiles, each a VALUE over what it is — "1920×1080 / frame
    size", "≈ 68 KB / result". A way of showing DATA: what a source is,
    what a result is expected to be, what a scene holds. Tiles are read, never
    clicked — which is what tells them apart from the controls around them.

        tiles = FactTiles()
        tiles.set_pairs([("1920×1080", "frame size"), ("30", "fps")])

    The row keeps its natural size inside this widget, which CLIPS it when
    there is less room (the last tiles go first): it never widens a window,
    and a layout as wide as the widget would squeeze or overlap the tiles.
    Looks: widgets.qss (QFrame#factTile, QLabel#factTileValue / #factTileCaption).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Fixed)
        self._row = qt.QtWidgets.QWidget(self)
        self._layout = qt.QtWidgets.QHBoxLayout(self._row)
        self._layout.setContentsMargins(0, 1, 0, 1)
        self._layout.setSpacing(5)
        self._pairs: list = []

    def pairs(self) -> list:
        return list(self._pairs)

    def set_pairs(self, pairs: list) -> None:
        """The tiles, left to right: (value, what it is)."""
        pairs = [(str(value), str(caption)) for value, caption in pairs]
        if pairs == self._pairs:
            return
        self._pairs = pairs
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for value, caption in pairs:
            tile = qt.QtWidgets.QFrame(self._row)
            tile.setObjectName("factTile")
            value_label = qt.QtWidgets.QLabel(value, tile)
            value_label.setObjectName("factTileValue")
            caption_label = qt.QtWidgets.QLabel(caption, tile)
            caption_label.setObjectName("factTileCaption")
            box = qt.QtWidgets.QVBoxLayout(tile)
            box.setContentsMargins(8, 2, 8, 3)
            box.setSpacing(0)
            box.addWidget(value_label)
            box.addWidget(caption_label)
            self._layout.addWidget(tile)
            for widget in (tile, value_label, caption_label):
                widget.ensurePolished()  # the fonts from QSS, before the row is measured
            tile.show()
        self._layout.activate()
        self._row.resize(self._layout.sizeHint() if pairs else qt.QtCore.QSize(0, 0))
        if pairs:
            self.setFixedHeight(self._row.height())

    def text(self) -> str:
        """The tiles as one line of text."""
        return "  ·  ".join(f"{value} {caption}" for value, caption in self._pairs)
