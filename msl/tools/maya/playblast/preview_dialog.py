# tools/maya/playblast/preview_dialog.py
"""A preview of one frame of the playblast — what the camera, the size, the
background and the shot mask make of it — before the real
playblast is taken."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class PreviewDialog(FramelessDialog):
    """Shows `image` (a QImage) scaled to fit MAX_SIDE, with a caption under it.

        PreviewDialog.show_for(parent, image, "Frame 24 · 1920×1080 · shotCam")
    """

    MAX_WIDTH, MAX_HEIGHT = 960, 560

    def __init__(self, image: qt.QtGui.QImage, caption: str, parent=None):
        pixmap = qt.QtGui.QPixmap.fromImage(image)
        if pixmap.width() > self.MAX_WIDTH or pixmap.height() > self.MAX_HEIGHT:
            pixmap = pixmap.scaled(self.MAX_WIDTH, self.MAX_HEIGHT, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                   qt.QtCore.Qt.TransformationMode.SmoothTransformation)
        super().__init__(title="Preview", subtitle=caption, width=pixmap.width() + 40, height=pixmap.height() + 110,
                         show_minimize_button=False, show_maximize_button=False, parent=parent)
        picture = qt.QtWidgets.QLabel()
        picture.setPixmap(pixmap)
        picture.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self.add_widget(picture)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)

    @classmethod
    def show_for(cls, parent, image: qt.QtGui.QImage, caption: str) -> "PreviewDialog":
        dialog = cls(image, caption, parent=parent)
        dialog.show()
        return dialog
