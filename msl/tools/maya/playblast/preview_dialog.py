# tools/maya/playblast/preview_dialog.py
"""A preview of one frame of the playblast — what the camera, the size, the
background and the shot mask make of it — before the real
playblast is taken."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.scrollbars.slim_scroll_bar import SlimScrollBar
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class _Zoomable(qt.QtWidgets.QScrollArea):
    """Private: the frame, fitted into the window; a click shows the spot clicked at ZOOM x its real
    pixels, unsmoothed (edges, anti-aliasing, thin lines can be judged there), a second click fits it
    again. Drawn in the screen's own pixels — on a scaled screen Qt would otherwise stretch (blur) them."""

    ZOOM = 2

    def __init__(self, image: qt.QtGui.QImage, fit: qt.QtCore.QSize, parent=None):
        super().__init__(parent)
        self._image = image
        self._fit = fit
        self._zoomed = False
        self._label = qt.QtWidgets.QLabel()
        self._label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._label.setCursor(qt.QtCore.Qt.CursorShape.CrossCursor)
        self._label.setToolTip("Click: the spot at 2× its pixels — click again to fit")
        self.setWidget(self._label)
        self.setWidgetResizable(True)
        self.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(qt.QtWidgets.QFrame.Shape.NoFrame)
        self.setVerticalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Vertical))
        self.setHorizontalScrollBar(SlimScrollBar(qt.QtCore.Qt.Orientation.Horizontal))
        self.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self._label.installEventFilter(self)
        self._show()

    def _ratio(self) -> float:
        return self.devicePixelRatioF() or 1.0

    def _show(self, anchor: qt.QtCore.QPointF | None = None) -> None:
        ratio = self._ratio()
        if self._zoomed:
            size = self._image.size() * self.ZOOM
            pixmap = qt.QtGui.QPixmap.fromImage(self._image.scaled(
                size, qt.QtCore.Qt.AspectRatioMode.IgnoreAspectRatio, qt.QtCore.Qt.TransformationMode.FastTransformation))
        else:
            target = self._fit * ratio  # the box in the screen's own pixels
            image = self._image
            if image.size() != target:
                image = image.scaled(target, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                     qt.QtCore.Qt.TransformationMode.SmoothTransformation)
            pixmap = qt.QtGui.QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)  # drawn in screen pixels: zoomed, one image pixel = ZOOM of them
        self._label.setPixmap(pixmap)
        self.setWidgetResizable(not self._zoomed)
        if self._zoomed:
            self._label.resize(pixmap.size() / ratio)
            if anchor is not None:  # the spot clicked comes to the middle
                self.horizontalScrollBar().setValue(int(anchor.x() * self._label.width() - self.viewport().width() / 2))
                self.verticalScrollBar().setValue(int(anchor.y() * self._label.height() - self.viewport().height() / 2))

    def eventFilter(self, watched, event) -> bool:
        if watched is self._label and event.type() == qt.QtCore.QEvent.Type.MouseButtonRelease \
                and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            pixmap = self._label.pixmap()
            shown = pixmap.deviceIndependentSize() if pixmap is not None else qt.QtCore.QSizeF(1, 1)
            # where in the picture (0..1) the click was — the label may be bigger than the picture
            left = (self._label.width() - shown.width()) / 2
            top = (self._label.height() - shown.height()) / 2
            position = event.position()
            anchor = qt.QtCore.QPointF(min(max((position.x() - left) / max(shown.width(), 1), 0), 1),
                                       min(max((position.y() - top) / max(shown.height(), 1), 0), 1))
            self._zoomed = not self._zoomed
            self._show(anchor)
            return True
        return super().eventFilter(watched, event)


class PreviewDialog(FramelessDialog):
    """Shows `image` (a QImage) fitted into MAX_WIDTH x MAX_HEIGHT, with a caption in the header;
    a click on it shows that spot at 2x its pixels (to judge edges — "Smooth edges").

        PreviewDialog.show_for(parent, image, "Frame 24 · 1920×1080 · shotCam")
    """

    MAX_WIDTH, MAX_HEIGHT = 960, 560

    def __init__(self, image: qt.QtGui.QImage, caption: str, parent=None):
        scale = min(self.MAX_WIDTH / max(image.width(), 1), self.MAX_HEIGHT / max(image.height(), 1), 1.0)
        fit = qt.QtCore.QSize(int(image.width() * scale), int(image.height() * scale))
        super().__init__(title="Preview", subtitle=caption + "  ·  click to zoom", width=fit.width() + 40,
                         height=fit.height() + 110, show_minimize_button=False, show_maximize_button=False,
                         parent=parent)
        self.add_widget(_Zoomable(image, fit))
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)

    @classmethod
    def show_for(cls, parent, image: qt.QtGui.QImage, caption: str) -> "PreviewDialog":
        dialog = cls(image, caption, parent=parent)
        dialog.show()
        return dialog
