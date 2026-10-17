# tools/desktop/maya_gate/hotkeys_keyboard.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property

ROWS = ("`1234567890-=", "QWERTYUIOP[]", "ASDFGHJKL;'", "ZXCVBNM,./")
OFFSETS = (0.0, 0.5, 0.75, 1.25)     # each row starts this many keys in, like a real keyboard
WIDEST = max(len(row) + offset for row, offset in zip(ROWS, OFFSETS))


class KeyboardMap(qt.QtWidgets.QWidget):
    """The letter / digit block of a keyboard, each key painted by what it does with the modifiers picked
    above it: OURS (outlined in its group's color - `tone`), TAKEN (Maya's own or the user's set: filled
    grey), FREE (dashed). Only shows what it is told (`set_keys`); hovering / clicking a key is reported.

    Colors: qproperty keyBorderColor / freeColor / takenColor / textColor / quietColor / highlightColor and one per
    tone (accentColor, orangeColor, violetColor, yellowColor, tealColor, pinkColor, successColor, errorColor),
    set in maya_gate.qss.
    """

    hovered = qt.QtCore.Signal(str)   # the key's character, "" when the pointer left the keys
    clicked = qt.QtCore.Signal(str)

    GAP = 4
    MAX_UNIT = 36
    RADIUS = 5

    keyBorderColor = color_property("_key_border")
    freeColor = color_property("_free")
    takenColor = color_property("_taken")
    textColor = color_property("_text")
    quietColor = color_property("_quiet")
    highlightColor = color_property("_highlight")
    accentColor = color_property("_tone_accent")
    orangeColor = color_property("_tone_orange")
    violetColor = color_property("_tone_violet")
    yellowColor = color_property("_tone_yellow")
    tealColor = color_property("_tone_teal")
    pinkColor = color_property("_tone_pink")
    successColor = color_property("_tone_success")
    errorColor = color_property("_tone_error")

    def __init__(self, parent=None):
        super().__init__(parent)
        theme = ThemeRegistry.fallback()
        token = lambda name, default: qt.QtGui.QColor(theme.tokens.get(name, default))
        self._key_border = token("border", "#c3c9d2")
        self._free = token("text-secondary", "#6b7078")
        self._taken = token("surface-raised", "#f5f7fa")
        self._text = qt.QtGui.QColor(theme.text_primary)
        self._quiet = qt.QtGui.QColor(theme.text_secondary)
        self._highlight = qt.QtGui.QColor(theme.accent)
        for tone, default in (("accent", "#2f7dd1"), ("orange", "#e8710a"), ("violet", "#7e57c2"),
                              ("yellow", "#c9a400"), ("teal", "#00897b"), ("pink", "#d6337f"),
                              ("success", "#4caf50"), ("error", "#f44336")):
            setattr(self, "_tone_" + tone, token(tone, default))
        self._keys: dict = {}            # character -> ("ours" | "taken", tone)
        self._highlighted = ""
        self._hovered = ""
        self._rects: dict = {}
        self.setMouseTracking(True)
        size_policy = qt.QtWidgets.QSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Preferred,
                                               qt.QtWidgets.QSizePolicy.Policy.Preferred)
        size_policy.setHeightForWidth(True)
        self.setSizePolicy(size_policy)

    # --- what it shows ------------------------------------------------------------------------------

    def set_keys(self, keys: dict) -> None:
        """{character: ("ours", tone) | ("taken", "")}; a character not in it is free."""
        self._keys = dict(keys)
        self.update()

    def set_highlight(self, character: str) -> None:
        self._highlighted = character
        self.update()

    # --- size ----------------------------------------------------------------------------------------

    def _unit(self, width: int) -> float:
        return min(self.MAX_UNIT, (width - self.GAP * (len(ROWS[0]) - 1)) / WIDEST)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        unit = self._unit(width)
        return int(len(ROWS) * unit * 0.86 + (len(ROWS) - 1) * self.GAP) + 2

    def sizeHint(self) -> qt.QtCore.QSize:
        width = int(WIDEST * self.MAX_UNIT + self.GAP * len(ROWS[0]))
        return qt.QtCore.QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(260, self.heightForWidth(260))

    def _layout_keys(self) -> None:
        unit = self._unit(self.width())
        height = unit * 0.86
        step = unit + self.GAP * (len(ROWS[0]) - 1) / WIDEST
        left = max((self.width() - WIDEST * step) / 2, 0)
        self._rects = {}
        for row_index, (row, offset) in enumerate(zip(ROWS, OFFSETS)):
            y = row_index * (height + self.GAP) + 1
            for index, character in enumerate(row):
                x = left + (offset + index) * step
                self._rects[character] = qt.QtCore.QRectF(x, y, step - self.GAP, height)

    def resizeEvent(self, event) -> None:
        self._layout_keys()
        super().resizeEvent(event)

    # --- the pointer -----------------------------------------------------------------------------------

    def _key_at(self, position) -> str:
        return next((character for character, rect in self._rects.items() if rect.contains(position)), "")

    def mouseMoveEvent(self, event) -> None:
        key = self._key_at(event.position())
        if key != self._hovered:
            self._hovered = key
            self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor if key else qt.QtCore.Qt.CursorShape.ArrowCursor)
            self.update()
            self.hovered.emit(key)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered:
            self._hovered = ""
            self.update()
            self.hovered.emit("")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        key = self._key_at(event.position())
        if key and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit(key)
            event.accept()
            return
        super().mousePressEvent(event)

    # --- painting --------------------------------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        if not self._rects:
            self._layout_keys()
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        font = qt.QtGui.QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        for character, rect in self._rects.items():
            state, tone = self._keys.get(character, ("free", ""))
            if state == "ours":
                color = qt.QtGui.QColor(getattr(self, "_tone_" + (tone or "accent"), self._tone_accent))
                fill = qt.QtGui.QColor(color)
                fill.setAlpha(40 if character == self._hovered else 26)
                painter.setPen(qt.QtGui.QPen(color, 1.6))
                painter.setBrush(fill)
                text = color
            elif state == "taken":
                painter.setPen(qt.QtGui.QPen(self._key_border, 1))
                painter.setBrush(self._taken)
                text = self._text
            else:
                pen = qt.QtGui.QPen(self._free, 1, qt.QtCore.Qt.PenStyle.DashLine)
                if character == self._hovered:
                    pen = qt.QtGui.QPen(self._highlight, 1.2, qt.QtCore.Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                text = self._quiet
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
            if character == self._highlighted:
                painter.setPen(qt.QtGui.QPen(self._highlight, 2.2))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), self.RADIUS + 1, self.RADIUS + 1)
            painter.setPen(text)
            painter.drawText(rect, qt.QtCore.Qt.AlignmentFlag.AlignCenter, character)
