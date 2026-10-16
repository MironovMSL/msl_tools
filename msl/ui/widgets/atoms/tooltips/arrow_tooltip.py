# ui/widgets/atoms/tooltips/arrow_tooltip.py
"""A tooltip of our own: a rounded bubble with a tail pointing at its widget, holding a bold
title, an optional key (drawn as key caps) and a line or two of description.

    attach_tooltip(button, "Make unique", "Every repeated short name gets _01, _02 ...", "Ctrl+U")

That is all a widget needs: the hook takes the widget's ToolTip event (Qt sends it after the
system's hover delay), so the plain tooltip never shows. Once a tooltip was on screen, moving
to another hooked widget shows its tooltip at once (WARM_MS), as menus and toolbars do.
Content that changes (a state, a count) comes from `provider=`, asked each time it shows.

One ArrowTooltip per window is shared by every hooked widget of that window
(`ArrowTooltip.shared()`); it is a child of the window, so the window's stylesheet colors it.
Colors are Qt properties set by ui/theme/widgets.qss: backgroundColor, borderColor, titleColor,
textColor, keyColor, keyBorderColor, keyTextColor, shadowColor.
"""
import time
from typing import Callable, Optional

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property

Content = tuple[str, str, str]  # title, description, key


def key_caps(key: str) -> list[str]:
    """The caps a key text is drawn as: "Ctrl+Shift+F" -> ["Ctrl", "Shift", "F"]. A "+" key
    itself is kept ("Ctrl++" -> ["Ctrl", "+"]); "" -> []."""
    key = (key or "").strip()
    if not key:
        return []
    caps = [part.strip() for part in key.split("+") if part.strip()]
    if key == "+" or "++" in key or key.endswith(" +"):
        caps.append("+")
    return caps


def place(target: tuple[int, int, int, int], size: tuple[int, int],
          screen: tuple[int, int, int, int], gap: int, tail: int, edge: int,
          tail_margin: int, prefer: str = "below") -> tuple[int, int, str, int]:
    """Where a bubble of `size` (width, height; without the tail) goes for a `target` rect
    (x, y, w, h) on a `screen` rect: (x, y) of the bubble's top left, the SIDE of the target it
    stands on ("below" / "above" / "right" / "left" - its tail points back at the target), and
    the tail's place along that edge of the bubble.

    `prefer` "below" (the default; flips above when the screen ends) or "right" (beside it -
    a sidebar's tiles; flips left). If neither side fits, the one with more room. Kept `edge` px
    inside the screen along the edge; the tail points at the target's middle, but stays
    `tail_margin` px away from the bubble's corners."""
    tx, ty, tw, th = target
    sx, sy, sw, sh = screen
    width, height = size
    if prefer in ("right", "left"):
        room_right = (sx + sw) - (tx + tw) - gap - tail
        room_left = tx - sx - gap - tail
        right = room_right >= width or room_right >= room_left
        x = tx + tw + gap + tail if right else tx - gap - tail - width
        x = max(sx, min(x, sx + sw - width))
        middle = ty + th // 2
        y = max(sy + edge, min(middle - height // 2, sy + sh - edge - height))
        return x, y, "right" if right else "left", max(tail_margin, min(middle - y, height - tail_margin))
    room_below = (sy + sh) - (ty + th) - gap - tail
    room_above = ty - sy - gap - tail
    below = room_below >= height or room_below >= room_above
    y = ty + th + gap + tail if below else ty - gap - tail - height
    y = max(sy, min(y, sy + sh - height))
    middle = tx + tw // 2
    x = max(sx + edge, min(middle - width // 2, sx + sw - edge - width))
    return x, y, "below" if below else "above", max(tail_margin, min(middle - x, width - tail_margin))


class ArrowTooltip(qt.QtWidgets.QWidget):
    """The bubble itself — painted by hand, translucent around it (rounded corners, a soft
    shadow, the tail). Mostly reached through attach_tooltip(); `show_for(widget, ...)` /
    `show_at(global rect, ...)` show it by hand (e.g. for a row of a list), `dismiss()` hides
    it. Never takes the focus or a click."""

    PAD_X = 10
    PAD_Y = 7
    RADIUS = 6
    TAIL = 6            # how far the tail sticks out
    TAIL_HALF = 7       # half its width at the bubble
    SHADOW = 10         # room around the bubble for its shadow
    GAP = 3             # between the target and the tail's tip
    EDGE = 6            # kept inside the screen
    MAX_TEXT = 280      # the description wraps at this width
    LINE_GAP = 3        # title -> description
    KEY_GAP = 14        # title -> its keys
    CAP_PAD = 5
    CAP_GAP = 3
    FADE_MS = 110
    WARM_MS = 500       # another tooltip shows at once within this time

    backgroundColor = color_property("_background_color")
    borderColor = color_property("_border_color")
    titleColor = color_property("_title_color")
    textColor = color_property("_text_color")
    keyColor = color_property("_key_color")
    keyBorderColor = color_property("_key_border_color")
    keyTextColor = color_property("_key_text_color")
    shadowColor = color_property("_shadow_color")

    OBJECT_NAME = "arrowTooltip"

    def __init__(self, parent=None):
        flags = (qt.QtCore.Qt.WindowType.ToolTip
                 | qt.QtCore.Qt.WindowType.FramelessWindowHint
                 | qt.QtCore.Qt.WindowType.NoDropShadowWindowHint)
        super().__init__(parent, flags)
        self.setObjectName(self.OBJECT_NAME)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._background_color = qt.QtGui.QColor(fallback.surface)
        self._border_color = qt.QtGui.QColor(fallback.border)
        self._title_color = qt.QtGui.QColor(fallback.text_primary)
        self._text_color = qt.QtGui.QColor(fallback.text_secondary)
        self._key_color = qt.QtGui.QColor(fallback.surface)
        self._key_border_color = qt.QtGui.QColor(fallback.border)
        self._key_text_color = qt.QtGui.QColor(fallback.text_secondary)
        self._shadow_color = qt.QtGui.QColor(0, 0, 0, 90)
        self._title = ""
        self._text = ""
        self._caps: list[str] = []
        self._side = "below"   # of the target; the tail is on the facing edge
        self._tail_at = 0
        self._body = qt.QtCore.QSize(0, 0)
        self._target: Optional[qt.QtWidgets.QWidget] = None
        self._hidden_at = 0.0
        self._fade = qt.QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(self.FADE_MS)
        self._fade.setEndValue(1.0)
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.dismiss)

    # --- the shared one --------------------------------------------------------------

    @classmethod
    def shared(cls, widget: qt.QtWidgets.QWidget, create: bool = True) -> Optional["ArrowTooltip"]:
        """The one tooltip of `widget`'s window (made on first use when `create`)."""
        window = widget.window()
        tip = window.findChild(cls, cls.OBJECT_NAME, qt.QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
        if tip is None and create:
            tip = cls(window)
        return tip

    # --- showing ----------------------------------------------------------------------

    def target(self) -> Optional[qt.QtWidgets.QWidget]:
        """The widget it points at now (None when hidden or shown by show_at)."""
        return self._target if self.isVisible() else None

    def is_warm(self) -> bool:
        """Is it on screen, or was it a moment ago? Then the next one shows at once."""
        return self.isVisible() or (time.monotonic() - self._hidden_at) * 1000 < self.WARM_MS

    def show_for(self, widget: qt.QtWidgets.QWidget, title: str, description: str = "",
                 key: str = "", animate: bool = True, side: str = "below") -> None:
        """Points at `widget` (its whole rect). `side`: "below" or "right" (see place())."""
        rect = qt.QtCore.QRect(widget.mapToGlobal(qt.QtCore.QPoint(0, 0)), widget.size())
        self.show_at(rect, title, description, key, animate=animate, side=side)
        self._target = widget

    def show_at(self, rect: qt.QtCore.QRect, title: str, description: str = "", key: str = "",
                animate: bool = True, side: str = "below") -> None:
        """Points at `rect`, in global coordinates."""
        self._message_timer.stop()
        self._title, self._text, self._caps = title or "", description or "", key_caps(key)
        self._target = None
        self.ensurePolished()  # the fonts / colors of the window's QSS before measuring
        self._body = self._measure()
        screen = qt.QtGui.QGuiApplication.screenAt(rect.center()) or qt.QtGui.QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else qt.QtCore.QRect(0, 0, 1920, 1080)
        x, y, self._side, self._tail_at = place(
            (rect.x(), rect.y(), rect.width(), rect.height()),
            (self._body.width(), self._body.height()),
            (area.x(), area.y(), area.width(), area.height()),
            self.GAP, self.TAIL, self.EDGE, self.RADIUS + self.TAIL_HALF, prefer=side)
        sideways = self._side in ("right", "left")
        self.setFixedSize(self._body.width() + 2 * self.SHADOW + (self.TAIL if sideways else 0),
                          self._body.height() + 2 * self.SHADOW + (0 if sideways else self.TAIL))
        offset = self._body_offset()
        self.move(x - offset.x(), y - offset.y())
        fade = animate and not self.isVisible()
        self._fade.stop()
        self.setWindowOpacity(0.0 if fade else 1.0)
        self.show()
        self.raise_()
        self.update()
        if fade:
            self._fade.setStartValue(0.0)
            self._fade.start()

    def show_message(self, text: str, title: str = "", seconds: float = 2.5) -> None:
        """A short note at the pointer that goes away by itself ("Copied 3 to Stable")."""
        self.show_at(qt.QtCore.QRect(qt.QtGui.QCursor.pos(), qt.QtCore.QSize(1, 1)), title, text)
        self._message_timer.start(int(seconds * 1000))

    def dismiss(self) -> None:
        if self.isVisible():
            self._fade.stop()
            self.hide()

    def hideEvent(self, event) -> None:
        self._hidden_at = time.monotonic()
        self._target = None
        super().hideEvent(event)

    # --- measuring and painting --------------------------------------------------------

    def _body_offset(self) -> qt.QtCore.QPoint:
        """Where the bubble starts in the window: past the shadow, and past the tail on the
        side it sticks out of."""
        return qt.QtCore.QPoint(self.SHADOW + (self.TAIL if self._side == "right" else 0),
                                self.SHADOW + (self.TAIL if self._side == "below" else 0))

    def _fonts(self) -> tuple[qt.QtGui.QFont, qt.QtGui.QFont, qt.QtGui.QFont]:
        """Title (semibold), description, key caps (a little smaller)."""
        text = qt.QtGui.QFont(self.font())
        title = qt.QtGui.QFont(text)
        title.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        cap = qt.QtGui.QFont(text)
        if text.pointSizeF() > 0:
            cap.setPointSizeF(max(text.pointSizeF() - 1, 6))
        elif text.pixelSize() > 0:
            cap.setPixelSize(max(text.pixelSize() - 1, 8))
        return title, text, cap

    def _caps_size(self, cap_font: qt.QtGui.QFont) -> qt.QtCore.QSize:
        if not self._caps:
            return qt.QtCore.QSize(0, 0)
        metrics = qt.QtGui.QFontMetrics(cap_font)
        width = sum(self._cap_width(metrics, cap) for cap in self._caps) + self.CAP_GAP * (len(self._caps) - 1)
        return qt.QtCore.QSize(width, metrics.height() + 3)

    def _cap_width(self, metrics: qt.QtGui.QFontMetrics, cap: str) -> int:
        return max(metrics.horizontalAdvance(cap) + 2 * self.CAP_PAD, metrics.height() + 3)

    def _text_rects(self) -> tuple[qt.QtCore.QRect, qt.QtCore.QRect, qt.QtCore.QSize]:
        """The title's and the description's rects (from the bubble's padding corner) and the
        keys' size. A description without a title is drawn where the title would be."""
        title_font, text_font, cap_font = self._fonts()
        wrap = qt.QtCore.Qt.TextFlag.TextWordWrap
        caps = self._caps_size(cap_font)
        keys_room = caps.width() + self.KEY_GAP if self._caps else 0
        title = qt.QtCore.QRect()
        if self._title:
            title = qt.QtGui.QFontMetrics(title_font).boundingRect(
                qt.QtCore.QRect(0, 0, max(self.MAX_TEXT - keys_room, 80), 4000), wrap, self._title)
        text = qt.QtCore.QRect()
        if self._text:
            top = max(title.height(), caps.height()) + self.LINE_GAP if (self._title or self._caps) else 0
            text = qt.QtGui.QFontMetrics(text_font).boundingRect(
                qt.QtCore.QRect(0, 0, self.MAX_TEXT, 4000), wrap, self._text)
            text.moveTop(top)
        return title, text, caps

    def _measure(self) -> qt.QtCore.QSize:
        title, text, caps = self._text_rects()
        head = title.width() + (caps.width() + (self.KEY_GAP if self._title else 0) if self._caps else 0)
        width = max(head, text.width(), 24) + 2 * self.PAD_X
        height = max(title.height(), caps.height(), text.bottom() + 1 if self._text else 0) + 2 * self.PAD_Y
        return qt.QtCore.QSize(width, height)

    def _outline(self, body: qt.QtCore.QRectF) -> qt.QtGui.QPainterPath:
        """The bubble with its tail as ONE path (so the border runs round the tail too),
        drawn clockwise; the tail sits on the edge facing the target."""
        r, half, tail = float(self.RADIUS), float(self.TAIL_HALF), float(self.TAIL)
        left, top, right, bottom = body.left(), body.top(), body.right(), body.bottom()
        at = float(self._tail_at)
        point = qt.QtCore.QPointF
        path = qt.QtGui.QPainterPath()

        def tail_to(base_a, soft_a, apex, soft_b, base_b):
            path.lineTo(base_a)
            path.lineTo(soft_a)
            path.quadTo(apex, soft_b)  # a softened tip
            path.lineTo(base_b)

        path.moveTo(left + r, top)
        if self._side == "below":  # the target is above: the tail points up
            x = left + at
            tail_to(point(x - half, top), point(x - 1.2, top - tail + 1), point(x, top - tail),
                    point(x + 1.2, top - tail + 1), point(x + half, top))
        path.lineTo(right - r, top)
        path.arcTo(qt.QtCore.QRectF(right - 2 * r, top, 2 * r, 2 * r), 90, -90)
        if self._side == "left":  # the target is to the right: the tail points right
            y = top + at
            tail_to(point(right, y - half), point(right + tail - 1, y - 1.2), point(right + tail, y),
                    point(right + tail - 1, y + 1.2), point(right, y + half))
        path.lineTo(right, bottom - r)
        path.arcTo(qt.QtCore.QRectF(right - 2 * r, bottom - 2 * r, 2 * r, 2 * r), 0, -90)
        if self._side == "above":  # the target is below: the tail points down
            x = left + at
            tail_to(point(x + half, bottom), point(x + 1.2, bottom + tail - 1), point(x, bottom + tail),
                    point(x - 1.2, bottom + tail - 1), point(x - half, bottom))
        path.lineTo(left + r, bottom)
        path.arcTo(qt.QtCore.QRectF(left, bottom - 2 * r, 2 * r, 2 * r), 270, -90)
        if self._side == "right":  # the target is to the left: the tail points left
            y = top + at
            tail_to(point(left, y + half), point(left - tail + 1, y + 1.2), point(left - tail, y),
                    point(left - tail + 1, y - 1.2), point(left, y - half))
        path.lineTo(left, top + r)
        path.arcTo(qt.QtCore.QRectF(left, top, 2 * r, 2 * r), 180, -90)
        path.closeSubpath()
        return path

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        offset = self._body_offset()
        body = qt.QtCore.QRectF(offset.x() + 0.5, offset.y() + 0.5,
                                self._body.width() - 1.0, self._body.height() - 1.0)
        outline = self._outline(body)

        # a soft shadow: the outline stroked ever wider and fainter, a little lower down
        steps = 5
        painter.save()
        painter.translate(0, 2)
        for step in range(steps, 0, -1):
            shade = qt.QtGui.QColor(self._shadow_color)
            shade.setAlphaF(self._shadow_color.alphaF() * (1 - step / (steps + 1)) ** 2 * 0.5)
            pen = qt.QtGui.QPen(shade, step * 3.0)
            pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(outline, pen)
        painter.restore()

        painter.setPen(qt.QtGui.QPen(self._border_color, 1.0))
        painter.setBrush(self._background_color)
        painter.drawPath(outline)

        title, text, caps = self._text_rects()
        origin = qt.QtCore.QPoint(int(body.left()) + self.PAD_X, int(body.top()) + self.PAD_Y)
        title_font, text_font, cap_font = self._fonts()
        wrap = int(qt.QtCore.Qt.TextFlag.TextWordWrap)
        if self._title:
            painter.setFont(title_font)
            painter.setPen(self._title_color)
            painter.drawText(title.translated(origin), wrap, self._title)
        if self._caps:
            line = qt.QtGui.QFontMetrics(title_font).height() if self._title else caps.height()
            cap_top = origin.y() + (line - caps.height()) // 2
            self._paint_caps(painter, cap_font, int(body.right()) - self.PAD_X - caps.width(), cap_top)
        if self._text:
            painter.setFont(text_font)
            painter.setPen(self._text_color if self._title else self._title_color)
            painter.drawText(text.translated(origin), wrap, self._text)
        painter.end()

    def _paint_caps(self, painter: qt.QtGui.QPainter, font: qt.QtGui.QFont, x: int, y: int) -> None:
        """Each key as a little raised cap: a darker edge below, the face on top."""
        metrics = qt.QtGui.QFontMetrics(font)
        height = metrics.height() + 3
        painter.setFont(font)
        for cap in self._caps:
            width = self._cap_width(metrics, cap)
            face = qt.QtCore.QRectF(x + 0.5, y + 0.5, width - 1.0, height - 2.0)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._key_border_color)
            painter.drawRoundedRect(face.translated(0, 1.5), 3, 3)
            painter.setPen(qt.QtGui.QPen(self._key_border_color, 1.0))
            painter.setBrush(self._key_color)
            painter.drawRoundedRect(face, 3, 3)
            painter.setPen(self._key_text_color)
            painter.drawText(face, int(qt.QtCore.Qt.AlignmentFlag.AlignCenter), cap)
            x += width + self.CAP_GAP


class _TooltipHook(qt.QtCore.QObject):
    """Lives on a hooked widget: shows the window's ArrowTooltip instead of the plain one."""

    HIDING = (qt.QtCore.QEvent.Type.Leave, qt.QtCore.QEvent.Type.MouseButtonPress,
              qt.QtCore.QEvent.Type.MouseButtonDblClick, qt.QtCore.QEvent.Type.Wheel,
              qt.QtCore.QEvent.Type.KeyPress, qt.QtCore.QEvent.Type.Hide,
              qt.QtCore.QEvent.Type.WindowDeactivate)

    def __init__(self, widget: qt.QtWidgets.QWidget):
        super().__init__(widget)
        self.setObjectName("arrowTooltipHook")
        self.content: Content = ("", "", "")
        self.provider: Optional[Callable[[], Optional[Content]]] = None
        self.side = "below"
        widget.installEventFilter(self)

    def current(self) -> Optional[Content]:
        """What to show now; None (or an empty title and description) = nothing."""
        content = self.provider() if self.provider else self.content
        if not content:
            return None
        title, description, key = (tuple(content) + ("", "", ""))[:3]
        return (title, description, key) if (title or description) else None

    def show(self, widget: qt.QtWidgets.QWidget, animate: bool) -> None:
        content = self.current()
        tip = ArrowTooltip.shared(widget, create=content is not None)
        if tip is None:
            return
        if content is None:
            if tip.target() is widget:
                tip.dismiss()
            return
        tip.show_for(widget, *content, animate=animate, side=self.side)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == qt.QtCore.QEvent.Type.ToolTip:
            self.show(watched, animate=True)
            return True  # never the plain tooltip
        if kind == qt.QtCore.QEvent.Type.Enter:
            tip = ArrowTooltip.shared(watched, create=False)
            if tip is not None and tip.is_warm():
                self.show(watched, animate=False)
        elif kind in self.HIDING:
            tip = ArrowTooltip.shared(watched, create=False)
            if tip is not None and tip.target() is watched:
                tip.dismiss()
        return False


def _hook_of(widget: qt.QtWidgets.QWidget) -> Optional[_TooltipHook]:
    return widget.findChild(_TooltipHook, "arrowTooltipHook", qt.QtCore.Qt.FindChildOption.FindDirectChildrenOnly)


def attach_tooltip(widget: qt.QtWidgets.QWidget, title: str = "", description: str = "",
                   key: str = "", provider: Optional[Callable[[], Optional[Content]]] = None,
                   side: str = "below") -> None:
    """Gives `widget` an ArrowTooltip. Called again, it changes what the tooltip says.

    `provider()` -> (title, description, key) or None is asked each time the tooltip shows
    and wins over the fixed texts. `side`: "below" (flips above at the screen's end) or "right"
    (beside it, for a column of tiles; flips left). The widget's plain toolTip() is set to the same words (for
    whatever reads it: accessibility, tests) but never shows."""
    hook = _hook_of(widget) or _TooltipHook(widget)
    hook.content = (title, description, key)
    hook.provider = provider
    hook.side = side
    widget.setToolTip("\n".join(part for part in (title, description) if part))


def detach_tooltip(widget: qt.QtWidgets.QWidget) -> None:
    """Back to the plain tooltip."""
    hook = _hook_of(widget)
    if hook is not None:
        widget.removeEventFilter(hook)
        hook.setParent(None)
        hook.deleteLater()
    tip = ArrowTooltip.shared(widget, create=False)
    if tip is not None and tip.target() is widget:
        tip.dismiss()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        row = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        cases = [("Unique", "Make unique", "Every repeated short name gets _01, _02 ... "
                                            "none of them taken already.", "Ctrl+U"),
                 ("Search", "Find in the list", "", "Ctrl+F"),
                 ("No key", "Mirror", "A mirrored copy on the other side, its zero groups made again.", ""),
                 ("Text only", "", "Only a description, no title.", "")]
        for caption, title, description, key in cases:
            button = qt.QtWidgets.QPushButton(caption)
            attach_tooltip(button, title, description, key)
            layout.addWidget(button)
        clicks = [0]
        counter = qt.QtWidgets.QPushButton("Live")
        counter.clicked.connect(lambda: clicks.__setitem__(0, clicks[0] + 1))
        attach_tooltip(counter, provider=lambda: ("Clicked", f"● {clicks[0]} times so far", "Space"))
        layout.addWidget(counter)
        dialog.add_case("ArrowTooltip", row)
        dialog.show()
