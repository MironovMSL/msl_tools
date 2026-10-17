# ui/widgets/atoms/editors/key_capture_field.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property

Key = qt.QtCore.Qt.Key

# Windows virtual keys -> the key's name, whatever the layout and Shift make of it ("1" stays "1" with Shift,
# "R" stays "R" with a Cyrillic layout)
_VIRTUAL = {0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[", 0xDC: "\\",
            0xDD: "]", 0xDE: "'"}
_VIRTUAL.update({code: chr(code) for code in range(0x30, 0x3A)})
_VIRTUAL.update({code: chr(code) for code in range(0x41, 0x5B)})
_NAMED = {Key.Key_Up: "Up", Key.Key_Down: "Down", Key.Key_Left: "Left", Key.Key_Right: "Right", Key.Key_Home: "Home",
          Key.Key_End: "End", Key.Key_PageUp: "PageUp", Key.Key_PageDown: "PageDown", Key.Key_Insert: "Insert",
          Key.Key_Delete: "Delete", Key.Key_Return: "Enter", Key.Key_Enter: "Enter", Key.Key_Space: "Space",
          Key.Key_Tab: "Tab", Key.Key_Backtab: "Tab", Key.Key_Backspace: "Backspace"}
_NAMED.update({getattr(Key, "Key_F%d" % number): "F%d" % number for number in range(1, 13)})
_MODIFIER_KEYS = (Key.Key_Control, Key.Key_Alt, Key.Key_Shift, Key.Key_Meta, Key.Key_AltGr)


def key_name(event) -> str:
    """The pressed key's name ("R", "1", "F5", "PageUp", ";") or "" for a key without one."""
    if event.key() in _NAMED:
        return _NAMED[event.key()]
    virtual = event.nativeVirtualKey()
    if virtual in _VIRTUAL:
        return _VIRTUAL[virtual]
    text = qt.QtGui.QKeySequence(event.key()).toString()
    return text.upper() if len(text) == 1 and text.isascii() and text.isprintable() else ""


def modifier_names(modifiers) -> list:
    Modifier = qt.QtCore.Qt.KeyboardModifier
    return [name for name, flag in (("Ctrl", Modifier.ControlModifier), ("Alt", Modifier.AltModifier),
                                    ("Shift", Modifier.ShiftModifier)) if modifiers & flag]


class KeyCaptureField(qt.QtWidgets.QWidget):
    """A field that holds ONE keyboard shortcut and shows it as key caps ("Ctrl" "Alt" "R").

    Click it (or Tab into it) and press the combination: the held modifiers show at once, the first other key
    completes it -> `key_changed("Ctrl+Alt+R")`. Esc gives up (the old shortcut stays), Backspace or Delete
    on their own clear it -> `key_changed("")` - and so does the × that shows at the field's right end under the
pointer while it holds a shortcut. While it listens it takes every key - also Tab and the hub's
    own shortcuts. `accept(text) -> bool` (optional) refuses a combination: the field flashes and says so.
    `check(text) -> str` (optional) WARNS before taking one: a non-empty answer (what else uses that key) holds
    the combination back - its caps in the warning color, `warned(text, note)` for the owner to show the note -
    until it is pressed again or Enter takes it; another combination is checked anew; Esc gives up.

    The text is "Ctrl+Alt+Shift+<key>"; key names: letters in upper case, digits, F1..F12, Up, Down, Left,
    Right, Home, End, PageUp, PageDown, Insert, Delete, Enter, Space, Tab, Backspace and ` - = [ ] \\ ; ' , . /
    (from the PHYSICAL key: a Cyrillic layout or Shift change nothing). Only shows and reports: what the
    shortcut is for is the owner's.

    Colors: qproperty backgroundColor / borderColor / hoverBorderColor / focusColor / capColor /
    capBorderColor / capTextColor / placeholderColor / errorColor (ui/theme/widgets.qss).
    """

    key_changed = qt.QtCore.Signal(str)
    warned = qt.QtCore.Signal(str, str)     # (the combination held back, what check() said about it)
    warn_ended = qt.QtCore.Signal()         # taken, given up or replaced: the note can go
    capture_started = qt.QtCore.Signal()
    capture_ended = qt.QtCore.Signal()

    HEIGHT = 22
    RADIUS = 4
    CAP_GAP = 3
    CAP_PADDING = 5
    REFUSED_MS = 1400

    backgroundColor = color_property("_background_color")
    borderColor = color_property("_border_color")
    hoverBorderColor = color_property("_hover_border_color")
    focusColor = color_property("_focus_color")
    capColor = color_property("_cap_color")
    capBorderColor = color_property("_cap_border_color")
    capTextColor = color_property("_cap_text_color")
    placeholderColor = color_property("_placeholder_color")
    errorColor = color_property("_error_color")
    warnColor = color_property("_warn_color")

    def __init__(self, text: str = "", placeholder: str = "Type a hotkey", accept=None, check=None, parent=None):
        super().__init__(parent)
        self._text = text
        self._placeholder = placeholder
        self._accept = accept
        self._check = check
        self._pending = ""              # a combination check() warned about, waiting for a second press / Enter
        self._held: list = []           # modifiers held while listening
        self._refused = ""              # what was refused, shown for a moment
        self._hovered = False
        theme = ThemeRegistry.fallback()
        self._background_color = qt.QtGui.QColor(theme.tokens.get("field", "#ffffff"))
        self._border_color = qt.QtGui.QColor(theme.tokens.get("border", "#c8c8c8"))
        self._hover_border_color = qt.QtGui.QColor(theme.accent)
        self._focus_color = qt.QtGui.QColor(theme.accent)
        self._cap_color = qt.QtGui.QColor(theme.tokens.get("surface-raised", "#f4f4f4"))
        self._cap_border_color = qt.QtGui.QColor(theme.tokens.get("border", "#c8c8c8"))
        self._cap_text_color = qt.QtGui.QColor(theme.text_primary)
        self._placeholder_color = qt.QtGui.QColor(theme.text_secondary)
        self._error_color = qt.QtGui.QColor(theme.tokens.get("error", "#d03030"))
        self._warn_color = qt.QtGui.QColor(theme.tokens.get("warning", "#ff9800"))
        self._refuse_timer = qt.QtCore.QTimer(self)
        self._refuse_timer.setSingleShot(True)
        self._refuse_timer.setInterval(self.REFUSED_MS)
        self._refuse_timer.timeout.connect(self._end_refused)
        self._over_clear = False
        self.setMouseTracking(True)
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(110)
        # TabFocus, not StrongFocus: Qt would give the focus BEFORE mousePressEvent, which then could not tell
        # a first click (listen) from a second one (give up) - nor the × (the user's click did nothing)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.TabFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_Hover, True)

    # --- what it holds --------------------------------------------------------------------------

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        """Shows `text` (no signal)."""
        if text != self._text:
            self._text = text
            self.update()

    def is_listening(self) -> bool:
        return self.hasFocus()

    def sizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(140, self.HEIGHT)

    # --- keys --------------------------------------------------------------------------------------

    def event(self, event) -> bool:
        kind = event.type()
        if self.hasFocus() and kind == qt.QtCore.QEvent.Type.ShortcutOverride:
            event.accept()      # the window's own shortcuts wait while the field listens
            return True
        if self.hasFocus() and kind == qt.QtCore.QEvent.Type.KeyPress and event.key() in (Key.Key_Tab, Key.Key_Backtab):
            self.keyPressEvent(event)     # Tab is a key here, not the way to the next field
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = modifier_names(event.modifiers())
        if key == Key.Key_Escape and not modifiers:
            self.clearFocus()
            return
        if self._pending and key in (Key.Key_Return, Key.Key_Enter) and not modifiers:
            self._commit(self._pending)     # Enter takes the combination it warned about
            return
        if key in (Key.Key_Backspace, Key.Key_Delete) and not modifiers:
            self.clear()
            return
        if key in _MODIFIER_KEYS:
            self._held = modifiers
            self.update()
            return
        name = key_name(event)
        if not name:
            return
        text = "+".join(modifiers + [name])
        if self._accept is not None and not self._accept(text):
            self._refused = text
            self._refuse_timer.start()
            self.update()
            return
        note = self._check(text) if self._check is not None and text != self._pending else ""
        if note:
            self._held = []          # show the combination held back, not the modifiers still down
            self._set_pending(text)
            self.warned.emit(text, note)
            return
        self._commit(text)

    def _set_pending(self, text: str) -> None:
        had = bool(self._pending)
        self._pending = text
        self.update()
        if had and not text:
            self.warn_ended.emit()

    def _commit(self, text: str) -> None:
        self._set_pending("")
        self.clearFocus()
        if text != self._text:
            self._text = text
            self.update()
            self.key_changed.emit(text)

    def keyReleaseEvent(self, event) -> None:
        # The key let go of is no longer held - Windows still reports a released Alt / Ctrl in modifiers(), and a
        # warned combination stayed hidden behind a lone "Alt" cap until another key came (the user saw no warning).
        released = {Key.Key_Control: "Ctrl", Key.Key_Alt: "Alt", Key.Key_Shift: "Shift"}.get(event.key())
        self._held = [name for name in modifier_names(event.modifiers()) if name != released] if not self._pending             else [name for name in self._held if name != released]
        self.update()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._held = []
        self.update()
        self.capture_started.emit()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._set_pending("")
        self._held = []
        self.update()
        self.capture_ended.emit()

    def _clear_rect(self) -> qt.QtCore.QRectF:
        """Where the × that clears the shortcut is (shown under the pointer while there is one)."""
        side = self.height() - 6
        return qt.QtCore.QRectF(self.width() - side - 3, 3, side, side)

    def _shows_clear(self) -> bool:
        return bool(self._text) and self._hovered and not self.hasFocus() and self.isEnabled()

    def clear(self) -> None:
        """No shortcut any more -> key_changed("")."""
        self.clearFocus()
        if self._text:
            self._text = ""
            self.update()
            self.key_changed.emit("")

    def mouseMoveEvent(self, event) -> None:
        over = self._shows_clear() and self._clear_rect().contains(event.position())
        if over != getattr(self, "_over_clear", False):
            self._over_clear = over
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            # the press itself is over the field: no hover state needed (it may not have caught up)
            if self._text and self._clear_rect().contains(event.position()):
                self.clear()
                event.accept()
                return
            if self.hasFocus():
                self.clearFocus()       # a second click gives up, like Esc
            else:
                self.setFocus(qt.QtCore.Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._over_clear = False
        self.update()
        super().leaveEvent(event)

    def _end_refused(self) -> None:
        self._refused = ""
        self.update()

    # --- drawing -------------------------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        listening = self.hasFocus()
        border = self._error_color if self._refused else (
            self._focus_color if listening else (self._hover_border_color if self._hovered and self.isEnabled()
                                                 else self._border_color))
        painter.setPen(qt.QtGui.QPen(border, 1))
        painter.setBrush(self._background_color)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        font = qt.QtGui.QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = qt.QtGui.QFontMetrics(font)
        x = 4.0
        if self._refused:
            self._draw_note(painter, metrics, x, "%s can't be used" % self._refused, self._error_color)
            return
        warning = listening and bool(self._pending) and not self._held
        if warning:   # held back: a warm tint and a stronger frame, seen at a glance
            tint = qt.QtGui.QColor(self._warn_color)
            tint.setAlpha(36)
            painter.setPen(qt.QtGui.QPen(self._warn_color, 1.6))
            painter.setBrush(tint)
            painter.drawRoundedRect(rect.adjusted(0.4, 0.4, -0.4, -0.4), self.RADIUS, self.RADIUS)
        caps = ([part for part in self._pending.split("+") if part] if warning else self._held) if listening else ([part for part in self._text.split("+") if part] if self._text else [])
        for cap in caps:
            width = metrics.horizontalAdvance(cap) + 2 * self.CAP_PADDING
            if x + width > self.width() - 4:
                break
            cap_rect = qt.QtCore.QRectF(x, 3.5, width, self.height() - 7)
            painter.setPen(qt.QtGui.QPen(self._warn_color if warning else self._cap_border_color, 1))
            painter.setBrush(self._cap_color)
            painter.drawRoundedRect(cap_rect, 3, 3)
            painter.setPen(self._cap_text_color if self.isEnabled() else self._placeholder_color)
            painter.drawText(cap_rect, qt.QtCore.Qt.AlignmentFlag.AlignCenter, cap)
            x += width + self.CAP_GAP
        if self._shows_clear():
            cross = self._clear_rect()
            if self._over_clear:
                tint = qt.QtGui.QColor(self._error_color)
                tint.setAlpha(40)
                painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                painter.drawRoundedRect(cross, 3, 3)
            pen = qt.QtGui.QPen(self._error_color if self._over_clear else self._placeholder_color, 1.4)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            inner = cross.adjusted(5, 5, -5, -5)
            painter.drawLine(inner.topLeft(), inner.bottomRight())
            painter.drawLine(inner.topRight(), inner.bottomLeft())
        if listening:
            self._draw_note(painter, metrics, x + 2, "again / ↵" if warning else ("press keys…" if not caps else "…"),
                            self._warn_color if warning else self._focus_color)
        elif not caps:
            self._draw_note(painter, metrics, x + 2, self._placeholder, self._placeholder_color)

    def _draw_note(self, painter, metrics, x: float, text: str, color) -> None:
        painter.setPen(color)
        room = max(int(self.width() - x - 4), 0)
        painter.drawText(qt.QtCore.QRectF(x, 0, room, self.height()),
                         qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft,
                         metrics.elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight, room))


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for start in ("", "Ctrl+Alt+R", "Shift+F5"):
            field = KeyCaptureField(start)
            field.key_changed.connect(print)
            dialog.add_case(start or "empty", field)
        dialog.exec()
