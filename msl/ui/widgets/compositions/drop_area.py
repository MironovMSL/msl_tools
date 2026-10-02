# ui/widgets/compositions/drop_area.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon


class DropArea(qt.QtWidgets.QWidget):
    """The place files are dropped onto, made to read as one at a glance: a
    dashed rounded frame, an icon and a line saying what to drop, a quiet
    second line, and — for those who would rather pick — a pill of round
    icon buttons (a file, a folder, ...).

        area = DropArea(icon, "Drop a video or an image sequence here", "or pick one:")
        file_button = area.add_button(file_icon, "Choose a file…")
        file_button.clicked.connect(...)
        area.set_dragging(True)     # something is dragged over: the frame lights up

    It only SHOWS the target: the owner takes the drop itself (often on a
    larger widget around it) and calls set_dragging() while something
    hovers. set_busy("Reading clip.mp4…") replaces the texts and hides the
    buttons until set_texts() is called again.

    The frame is painted here (QSS can't space a dashed border's dashes);
    its colors are Qt properties set by ui/theme/widgets.qss: borderColor /
    fillColor, and activeBorderColor / activeFillColor while dragging.
    """

    RADIUS = 10
    DASHES = (5, 4)        # dash, gap — in pen widths
    PEN_WIDTH = 1.4
    ICON_SIZE = 28
    BUTTON_SIZE = 34
    BUTTON_ICON = 18

    borderColor = color_property("_border_color")
    activeBorderColor = color_property("_active_border_color")
    fillColor = color_property("_fill_color")
    activeFillColor = color_property("_active_fill_color")

    def __init__(self, icon: "qt.QtGui.QIcon | None" = None, title: str = "", note: str = "", parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._border_color = qt.QtGui.QColor(fallback.text_secondary)
        self._active_border_color = qt.QtGui.QColor(fallback.accent)
        self._fill_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._active_fill_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._dragging = False
        self._buttons: list[IconPushButton] = []

        self._icon = TintedIcon(icon, self.ICON_SIZE)
        self._title = qt.QtWidgets.QLabel(title)
        self._title.setObjectName("dropAreaTitle")
        self._note = qt.QtWidgets.QLabel(note)
        self._note.setObjectName("dropAreaNote")
        self._note.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._note.setWordWrap(True)
        if not note:
            self._note.hide()
        self._pill = qt.QtWidgets.QFrame()
        self._pill.setObjectName("dropAreaPill")
        self._pill_layout = qt.QtWidgets.QHBoxLayout(self._pill)
        self._pill_layout.setContentsMargins(4, 3, 4, 3)
        self._pill_layout.setSpacing(4)
        self._pill.hide()  # until it has a button

        head = qt.QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addStretch(1)
        head.addWidget(self._icon)
        head.addWidget(self._title)
        head.addStretch(1)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(6)
        layout.addStretch(1)
        layout.addLayout(head)
        layout.addWidget(self._note)
        layout.addSpacing(2)
        layout.addWidget(self._pill, 0, qt.QtCore.Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    # --- content ---------------------------------------------------------------------------

    def add_button(self, icon: "qt.QtGui.QIcon | None", tooltip: str, fallback_text: str = "") -> IconPushButton:
        """Adds a round icon button to the pill and returns it (connect its `clicked`)."""
        button = IconPushButton(icon, tooltip, icon_size=qt.QtCore.QSize(self.BUTTON_ICON, self.BUTTON_ICON),
                                fallback_text=fallback_text)
        button.setObjectName("dropAreaButton")
        button.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.TabFocus)
        self._pill_layout.addWidget(button)
        self._buttons.append(button)
        self._pill.show()
        return button

    def set_texts(self, title: str, note: str = "") -> None:
        """What to drop (and the quiet line under it); the buttons are shown again."""
        self._title.setText(title)
        self._note.setText(note)
        self._note.setVisible(bool(note))
        self._pill.setVisible(bool(self._buttons))

    def set_busy(self, text: str) -> None:
        """Something is being read: only `text` is shown."""
        self._title.setText(text)
        self._note.hide()
        self._pill.hide()

    def title(self) -> str:
        return self._title.text()

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def set_dragging(self, dragging: bool) -> None:
        """Something is dragged over the target: the frame and the icon turn to the accent."""
        if dragging == self._dragging:
            return
        self._dragging = dragging
        self.setProperty("dragging", dragging)  # widgets.qss: DropArea[dragging="true"] ...
        for widget in (self, self._icon, self._title):
            repolish(widget)
        self.update()

    # --- painting ---------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        inset = self.PEN_WIDTH / 2 + 0.5
        rect = qt.QtCore.QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        pen = qt.QtGui.QPen(self._active_border_color if self._dragging else self._border_color, self.PEN_WIDTH)
        pen.setDashPattern(list(self.DASHES))
        pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(self._active_fill_color if self._dragging else self._fill_color)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        icons = UiResources().iconManager
        dialog = ThemedWidgetPlaygroundDialog()
        area = DropArea(icons.get_icon("media", sub_folder="tools"), "Drop a video or an image sequence here",
                        "or pick one:")
        area.setMinimumSize(520, 150)
        area.add_button(icons.get_icon("file_video", sub_folder="actions"), "Choose a file…", "F").clicked.connect(
            lambda: area.set_dragging(True))
        area.add_button(icons.get_icon("browse", sub_folder="actions"), "Choose a folder…", "D").clicked.connect(
            lambda: area.set_dragging(False))
        dialog.add_case("DropArea (the buttons switch the dragging look)", area)
        dialog.show()
