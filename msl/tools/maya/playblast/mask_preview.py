# tools/maya/playblast/mask_preview.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property

SLOTS = ("topLeft", "topCenter", "topRight", "bottomLeft", "bottomCenter", "bottomRight")
NEW_LINE, LOGO_TOKEN = "|", "{logo}"


class MaskPreview(qt.QtWidgets.QWidget):
    """A small picture of the shot mask: the frame with its two bars and the six
    slots where they will be — each showing its text with the tokens filled
    in. A click picks a slot (to edit its text elsewhere); an empty slot is a
    dashed box with a plus.

        preview = MaskPreview()
        preview.set_look(texts={"topLeft": "{scene}", ...}, values={"scene": "sh010", ...},
                         text_color="#ffffff", bar_color="#000000", bar_opacity=1.0, ...)
        preview.slot_picked.connect(...)

    It is a SKETCH, not the viewport: the text is as big as reads well at this
    size, not to scale; what a slot says and where it sits is what it shows.
    The mask's own colors are the user's data; the frame, the outline of the
    picked slot and the dashes of an empty one come from QSS (qproperty
    frameColor / borderColor / accentColor / mutedColor).

    Signals:
        slot_picked(str) — the slot that was clicked.
    """

    slot_picked = qt.QtCore.Signal(str)

    frameColor = color_property("_frame_color", "update")
    borderColor = color_property("_border_color", "update")
    accentColor = color_property("_accent_color", "update")
    mutedColor = color_property("_muted_color", "update")

    TEXT_PX = 11
    MIN_BAR = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._frame_color = qt.QtGui.QColor(fallback.surface)
        self._border_color = qt.QtGui.QColor(fallback.border)
        self._accent_color = qt.QtGui.QColor(fallback.accent)
        self._muted_color = qt.QtGui.QColor(fallback.text_secondary)
        self._look = {"texts": {}, "values": {}, "text_color": "#ffffff", "bar_color": "#000000", "bar_opacity": 1.0,
                      "text_opacity": 1.0, "top_bar": True, "bottom_bar": True, "font": "Consolas", "aspect": 16 / 9,
                      "letterbox": 0.0, "logo": ""}
        self._logo = qt.QtGui.QPixmap()
        self._logo_path = None
        self._current = SLOTS[0]
        self._hovered = ""
        self._rects: dict[str, qt.QtCore.QRectF] = {}
        self.setMouseTracking(True)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        policy = qt.QtWidgets.QSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding,
                                          qt.QtWidgets.QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMinimumWidth(200)

    # ------------------------------------------------------------------ what it shows

    def set_look(self, **look) -> None:
        """Any of: texts, values, text_color, bar_color, bar_opacity, text_opacity, top_bar,
        bottom_bar, font, aspect, letterbox, logo (a picture's path), safe_action, safe_title."""
        self._look.update(look)
        path = str(self._look.get("logo") or "")
        if path != self._logo_path:
            self._logo_path = path
            self._logo = qt.QtGui.QPixmap(path) if path else qt.QtGui.QPixmap()
        self.updateGeometry()
        self.update()

    def current(self) -> str:
        return self._current

    def set_current(self, slot: str) -> None:
        if slot in SLOTS and slot != self._current:
            self._current = slot
            self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        aspect = float(self._look.get("aspect") or 16 / 9)
        return max(2 * self.MIN_BAR + 30, min(240, int(round(width / max(0.5, aspect)))))

    def sizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(320, self.heightForWidth(320))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.height() != self.heightForWidth(self.width()):
            self.setFixedHeight(self.heightForWidth(self.width()))

    # ------------------------------------------------------------------ the mouse

    def _slot_at(self, point) -> str:
        for slot, rect in self._rects.items():
            if rect.contains(point):
                return slot
        return ""

    def mouseMoveEvent(self, event) -> None:
        slot = self._slot_at(event.position())
        if slot != self._hovered:
            self._hovered = slot
            self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._hovered:
            self._hovered = ""
            self.update()

    def mousePressEvent(self, event) -> None:
        slot = self._slot_at(event.position())
        if slot and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._current = slot
            self.update()
            self.slot_picked.emit(slot)

    # ------------------------------------------------------------------ painting

    def _lines(self, slot: str) -> tuple[list[str], bool]:
        """(the slot's lines with the tokens filled in, it holds the logo)."""
        text = str(self._look["texts"].get(slot, "") or "")
        logo = LOGO_TOKEN in text
        text = text.replace(LOGO_TOKEN, "").strip()
        for token, value in self._look["values"].items():
            text = text.replace("{" + token + "}", str(value))
        lines = [part.strip() for part in text.split(NEW_LINE)] if text else []
        while lines and not lines[-1]:
            lines.pop()
        return lines, logo

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        look = self._look
        frame = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(frame, 6, 6)
        painter.setClipPath(path)
        painter.fillPath(path, self._frame_color)

        width, height = frame.width(), frame.height()
        bar = max(self.MIN_BAR, height * 0.15)
        letterbox = float(look.get("letterbox") or 0.0)
        if letterbox > 0.0 and width / letterbox < height:
            bar = max(self.MIN_BAR, (height - width / letterbox) / 2.0)
        bar = min(bar, height / 2.0 - 8)
        bar_color = qt.QtGui.QColor(look["bar_color"])
        bar_color.setAlphaF(max(0.0, min(1.0, float(look["bar_opacity"]))))
        rows = (("top", frame.top(), bool(look["top_bar"])), ("bottom", frame.bottom() - bar, bool(look["bottom_bar"])))
        text_color = qt.QtGui.QColor(look["text_color"])
        text_color.setAlphaF(max(0.15, min(1.0, float(look["text_opacity"]))))
        self._rects = {}
        for row, top, shown in rows:
            band = qt.QtCore.QRectF(frame.left(), top, width, bar)
            if shown and bar_color.alphaF() > 0.0:
                painter.fillRect(band, bar_color)
            third = (width - 8) / 3.0
            for index, column in enumerate(("Left", "Center", "Right")):
                slot = row + column
                rect = qt.QtCore.QRectF(frame.left() + 4 + index * third, top + 3, third, bar - 6).adjusted(1, 0, -1, 0)
                self._rects[slot] = rect
                self._paint_slot(painter, slot, rect, text_color, shown and bar_color.alphaF() > 0.3,
                                 ("left", "center", "right")[index])
        # the safe frames, as the viewport draws them (90 % solid, 80 % dashed) — a sketch, not to scale
        guides = qt.QtGui.QColor(text_color)
        guides.setAlphaF(text_color.alphaF() * 0.55)
        for wanted, part, style in ((look.get("safe_action"), 0.9, qt.QtCore.Qt.PenStyle.SolidLine),
                                    (look.get("safe_title"), 0.8, qt.QtCore.Qt.PenStyle.DashLine)):
            if wanted:
                painter.setPen(qt.QtGui.QPen(guides, 1, style))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRect(qt.QtCore.QRectF(frame.center().x() - width * part / 2,
                                                  frame.center().y() - height * part / 2, width * part, height * part))
        painter.setClipping(False)
        painter.setPen(qt.QtGui.QPen(self._border_color, 1))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 6, 6)

    def _paint_slot(self, painter, slot: str, rect, text_color, on_bar: bool, side: str) -> None:
        lines, logo = self._lines(slot)
        empty = not lines and not logo
        picked, hovered = slot == self._current, slot == self._hovered
        if picked or hovered or empty:
            pen = qt.QtGui.QPen(self._accent_color if picked else self._muted_color, 1)
            if empty and not picked:
                pen.setStyle(qt.QtCore.Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 4, 4)
        if empty:
            painter.setPen(self._accent_color if picked else self._muted_color)
            font = self.font()
            font.setPixelSize(12)
            painter.setFont(font)
            painter.drawText(rect, qt.QtCore.Qt.AlignmentFlag.AlignCenter, "+")
            return
        inner = rect.adjusted(5, 1, -5, -1)
        flags = {"left": qt.QtCore.Qt.AlignmentFlag.AlignLeft, "center": qt.QtCore.Qt.AlignmentFlag.AlignHCenter,
                 "right": qt.QtCore.Qt.AlignmentFlag.AlignRight}[side]
        if logo and not self._logo.isNull():
            logo_height = min(inner.height(), rect.height() * 0.8)
            logo_width = logo_height * self._logo.width() / max(1, self._logo.height())
            if side == "left":
                at = inner.left()
                inner.setLeft(inner.left() + logo_width + 5)
            elif side == "right":
                at = inner.right() - logo_width
                inner.setRight(inner.right() - logo_width - 5)
            else:
                at, lines = inner.center().x() - logo_width / 2.0, []
            target = qt.QtCore.QRectF(at, rect.center().y() - logo_height / 2.0, logo_width, logo_height)
            painter.setOpacity(text_color.alphaF())
            painter.drawPixmap(target, self._logo, qt.QtCore.QRectF(self._logo.rect()))
            painter.setOpacity(1.0)
        if not lines:
            return
        size = max(7, min(self.TEXT_PX, int(inner.height() / (len(lines) * 1.2))))
        font = qt.QtGui.QFont(str(self._look.get("font") or "Consolas"))
        font.setPixelSize(size)
        painter.setFont(font)
        # off a bar (the bar is switched off or see-through) the mask's own color may not read on
        # the sketch's ground: the theme's text color is used there
        painter.setPen(text_color if on_bar else self._muted_color)
        metrics = qt.QtGui.QFontMetricsF(font)
        step = size * 1.2
        top = inner.center().y() - step * len(lines) / 2.0
        for index, line in enumerate(lines):
            line_rect = qt.QtCore.QRectF(inner.left(), top + index * step, inner.width(), step)
            elided = metrics.elidedText(line, qt.QtCore.Qt.TextElideMode.ElideRight, inner.width())
            painter.drawText(line_rect, flags | qt.QtCore.Qt.AlignmentFlag.AlignVCenter, elided)
