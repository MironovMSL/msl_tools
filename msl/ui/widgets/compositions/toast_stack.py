# ui/widgets/compositions/toast_stack.py
"""Short messages inside a window: rounded cards that slide in at the bottom right of the
window's content, stack upwards, and go away by themselves.

    show_toast(self, "Done: 7 paths in 3 scenes", tone="success",
               action="Undo", on_action=self._on_undo)

Tones: "info" (the accent), "success", "warning", "error" — a colored edge on the left and
the tone's icon. A toast with an action button ("Undo", "Open") offers one thing to do about
it; a click on it runs `on_action` and closes the toast. Each goes away after `seconds` (by
tone; 0 = only when closed), its remaining time drawn as a thin line along its bottom; while
the pointer is over it, the time stands still. At most MOST toasts at once (the oldest goes).

For things the user should notice where they are working — not a log (the page's own message
line stays for that) and not a question (ConfirmDialog). One ToastStack per window, made on
first use (`ToastStack.of(widget)`); toasts are children of the window's content surface, so
the window's stylesheet colors them: `Toast` qproperty backgroundColor / borderColor /
toneColor / shadowColor, per tone by `Toast[tone=...]`, in ui/theme/widgets.qss.
"""
from typing import Callable, Optional

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon

TONES = ("info", "success", "warning", "error")
TONE_ICONS = {"info": "bell", "success": "check", "warning": "warning", "error": "error"}
TONE_SECONDS = {"info": 5.0, "success": 5.0, "warning": 8.0, "error": 10.0}


class Toast(qt.QtWidgets.QWidget):
    """One message card. Made by ToastStack.show(); `closed` when it has gone."""

    WIDTH = 320
    SHADOW = 10     # room around the card for its painted shadow
    RADIUS = 8
    EDGE = 3        # the tone's edge on the left
    SLIDE = 40      # px it slides in from / out to the right
    MOVE_MS = 180

    closed = qt.QtCore.Signal()

    backgroundColor = color_property("_background_color")
    borderColor = color_property("_border_color")
    toneColor = color_property("_tone_color")
    shadowColor = color_property("_shadow_color")

    def __init__(self, text: str, title: str = "", tone: str = "info", action: str = "",
                 on_action: Optional[Callable[[], None]] = None, seconds: Optional[float] = None,
                 parent=None):
        super().__init__(parent)
        tone = tone if tone in TONES else "info"
        self.setProperty("tone", tone)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, False)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._background_color = qt.QtGui.QColor(fallback.surface)
        self._border_color = qt.QtGui.QColor(fallback.border)
        self._tone_color = qt.QtGui.QColor(getattr(fallback, tone, fallback.accent) if tone != "info" else fallback.accent)
        self._shadow_color = qt.QtGui.QColor(0, 0, 0, 90)
        self._on_action = on_action
        self._closing = False
        self._left = 1.0   # the part of its time still to go (the line along the bottom)

        icons = UiResources().iconManager
        icon = TintedIcon(icons.get_icon(TONE_ICONS[tone], sub_folder="actions"), 16)
        icon.setObjectName("toastIcon")
        texts = qt.QtWidgets.QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self.title_label = qt.QtWidgets.QLabel(title)
        self.title_label.setObjectName("toastTitle")
        self.title_label.setWordWrap(True)
        self.text_label = qt.QtWidgets.QLabel(text)
        self.text_label.setObjectName("toastText" if title else "toastTitle")
        self.text_label.setWordWrap(True)
        if title:
            texts.addWidget(self.title_label)
        else:
            self.title_label.hide()
        texts.addWidget(self.text_label)
        self.action_button: Optional[qt.QtWidgets.QPushButton] = None
        if action:
            self.action_button = qt.QtWidgets.QPushButton(action)
            self.action_button.setObjectName("toastAction")
            self.action_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            self.action_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            self.action_button.clicked.connect(self._on_action_clicked)
        close = GlyphButton("×", "Close")
        close.setObjectName("toastClose")
        close.set_icon(icons.get_icon("clear", sub_folder="actions"))
        close.clicked.connect(self.close_toast)

        row = qt.QtWidgets.QHBoxLayout(self)
        pad = self.SHADOW
        row.setContentsMargins(pad + self.EDGE + 10, pad + 9, pad + 6, pad + 10)
        row.setSpacing(10)
        row.addWidget(icon, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        row.addLayout(texts, 1)
        if self.action_button is not None:
            row.addWidget(self.action_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(close, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)

        self._move = qt.QtCore.QPropertyAnimation(self, b"pos", self)
        self._move.setDuration(self.MOVE_MS)
        self._move.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._time = qt.QtCore.QVariantAnimation(self)
        self._time.setStartValue(1.0)
        self._time.setEndValue(0.0)
        self._time.valueChanged.connect(self._on_time)
        self._time.finished.connect(self.close_toast)
        self.seconds = TONE_SECONDS[tone] if seconds is None else max(float(seconds), 0.0)

    # --- the clock -------------------------------------------------------------------

    def start_clock(self) -> None:
        if self.seconds > 0:
            self._time.setDuration(int(self.seconds * 1000))
            self._time.start()

    def _on_time(self, value) -> None:
        self._left = float(value)
        self.update(0, self.height() - self.SHADOW - 3, self.width(), 4)

    def enterEvent(self, event) -> None:
        if self._time.state() == qt.QtCore.QAbstractAnimation.State.Running:
            self._time.pause()  # read it in peace
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._time.state() == qt.QtCore.QAbstractAnimation.State.Paused:
            self._time.resume()
        super().leaveEvent(event)

    # --- moving and closing ------------------------------------------------------------

    def body_height(self) -> int:
        """Its height for its width (the texts wrap)."""
        layout = self.layout()
        if layout.hasHeightForWidth():
            return layout.totalHeightForWidth(self.width())
        return self.sizeHint().height()

    def glide_to(self, point: qt.QtCore.QPoint, animate: bool = True) -> None:
        self._move.stop()
        if not animate or not self.isVisible():
            self.move(point)
            return
        self._move.setStartValue(self.pos())
        self._move.setEndValue(point)
        self._move.start()

    def close_toast(self) -> None:
        """Slides it out and deletes it (`closed` first, so the stack closes the gap at once)."""
        if self._closing:
            return
        self._closing = True
        self._time.stop()
        self.closed.emit()
        self._move.stop()   # (gliding never connects `finished`: deleting is its only use)
        self._move.setStartValue(self.pos())
        self._move.setEndValue(self.pos() + qt.QtCore.QPoint(self.SLIDE, 0))
        self._move.finished.connect(self.deleteLater)
        self._move.start()
        effect = qt.QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        fade = qt.QtCore.QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(self.MOVE_MS)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.start()

    def is_closing(self) -> bool:
        return self._closing

    def _on_action_clicked(self) -> None:
        callback = self._on_action
        self.close_toast()
        if callable(callback):
            callback()

    # --- painting -------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        s = self.SHADOW
        body = qt.QtCore.QRectF(s + 0.5, s + 0.5, self.width() - 2 * s - 1.0, self.height() - 2 * s - 1.0)
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(body, self.RADIUS, self.RADIUS)

        painter.save()  # a soft shadow: the outline stroked ever wider and fainter, a little lower
        painter.translate(0, 2)
        steps = 5
        for step in range(steps, 0, -1):
            shade = qt.QtGui.QColor(self._shadow_color)
            shade.setAlphaF(self._shadow_color.alphaF() * (1 - step / (steps + 1)) ** 2 * 0.5)
            painter.strokePath(path, qt.QtGui.QPen(shade, step * 3.0))
        painter.restore()

        painter.setPen(qt.QtGui.QPen(self._border_color, 1.0))
        painter.setBrush(self._background_color)
        painter.drawPath(path)

        painter.save()  # the tone's edge and the time line, both inside the rounded card
        painter.setClipPath(path)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._tone_color)
        painter.drawRect(qt.QtCore.QRectF(body.left(), body.top(), self.EDGE, body.height()))
        if self.seconds > 0 and self._left > 0:
            line = qt.QtGui.QColor(self._tone_color)
            line.setAlphaF(line.alphaF() * 0.55)
            painter.setBrush(line)
            painter.drawRect(qt.QtCore.QRectF(body.left(), body.bottom() - 2, body.width() * self._left, 2))
        painter.restore()
        painter.end()


class ToastStack(qt.QtCore.QObject):
    """The toasts of one window: placed at the bottom right of `host` (the window's content
    surface), newest at the bottom, stacking upwards; follows the host's size."""

    OBJECT_NAME = "toastStack"
    MARGIN = 18     # from the host's edges to the cards (the hub's page card sits ~6 px in)
    GAP = 8         # between cards
    MOST = 4

    def __init__(self, host: qt.QtWidgets.QWidget):
        super().__init__(host)
        self.setObjectName(self.OBJECT_NAME)
        self._host = host
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    @classmethod
    def of(cls, widget: qt.QtWidgets.QWidget) -> "ToastStack":
        """The stack of `widget`'s window (made on first use)."""
        window = widget.window()
        host = getattr(window, "content_surface", None)
        host = host if isinstance(host, qt.QtWidgets.QWidget) else window
        stack = host.findChild(cls, cls.OBJECT_NAME, qt.QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
        return stack if stack is not None else cls(host)

    def toasts(self) -> list[Toast]:
        """The toasts on screen (not those on their way out), oldest first."""
        return [toast for toast in self._toasts if not toast.is_closing()]

    def show(self, text: str, title: str = "", tone: str = "info", action: str = "",
             on_action: Optional[Callable[[], None]] = None, seconds: Optional[float] = None) -> Toast:
        toast = Toast(text, title, tone, action, on_action, seconds, parent=self._host)
        toast.closed.connect(lambda t=toast: self._on_closed(t))
        self._toasts.append(toast)
        while len(self.toasts()) > self.MOST:
            self.toasts()[0].close_toast()
        width = min(Toast.WIDTH + 2 * Toast.SHADOW, max(self._host.width() - 2 * self.MARGIN + 2 * Toast.SHADOW, 200))
        toast.setFixedWidth(width)
        toast.ensurePolished()
        toast.setFixedHeight(toast.body_height())
        target = self._places().get(id(toast))
        if target is not None:
            toast.move(target + qt.QtCore.QPoint(Toast.SLIDE, 0))
        toast.show()
        toast.raise_()
        self._arrange(animate=True)
        toast.start_clock()
        return toast

    def clear(self) -> None:
        for toast in self.toasts():
            toast.close_toast()

    def _on_closed(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._arrange(animate=True)

    def _places(self) -> dict:
        """id(toast) -> its top left: the newest card's bottom MARGIN above the host's bottom,
        the older ones above it."""
        places = {}
        bottom = self._host.height() - self.MARGIN + Toast.SHADOW  # the card's bottom edge + its shadow room
        for toast in reversed(self.toasts()):
            top = bottom - toast.height()
            places[id(toast)] = qt.QtCore.QPoint(self._host.width() - self.MARGIN + Toast.SHADOW - toast.width(), top)
            bottom = top + 2 * Toast.SHADOW - self.GAP
        return places

    def _arrange(self, animate: bool) -> None:
        places = self._places()
        for toast in self.toasts():
            point = places.get(id(toast))
            if point is not None:
                toast.glide_to(point, animate=animate)
                toast.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._host and event.type() == qt.QtCore.QEvent.Type.Resize:
            self._arrange(animate=False)
        return False


def show_toast(widget: qt.QtWidgets.QWidget, text: str, title: str = "", tone: str = "info",
               action: str = "", on_action: Optional[Callable[[], None]] = None,
               seconds: Optional[float] = None) -> Toast:
    """A toast in `widget`'s window (see the module's docstring)."""
    return ToastStack.of(widget).show(text, title, tone, action, on_action, seconds)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        dialog.resize(560, 460)
        row = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(row)
        cases = [("Success", lambda: show_toast(row, "Done: 7 paths in 3 scenes.", tone="success",
                                                action="Undo", on_action=lambda: show_toast(row, "Undone."))),
                 ("Info", lambda: show_toast(row, "clip_v003.mp4 is ready.", "Media", action="Open")),
                 ("Warning", lambda: show_toast(row, "2 scenes left out: open in Maya.", tone="warning")),
                 ("Error", lambda: show_toast(row, "Maya 2025 ended unexpectedly at 14:03 — its log is kept.",
                                              "Maya Gate", tone="error", action="Show log"))]
        for caption, callback in cases:
            button = qt.QtWidgets.QPushButton(caption)
            button.clicked.connect(callback)
            layout.addWidget(button)
        dialog.add_case("Toasts", row)
        dialog.show()
