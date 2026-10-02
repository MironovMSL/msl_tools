# ui/widgets/atoms/icons/motion_icons.py
"""Icons that MOVE: each one is drawn by code on the 24-unit grid of the
SVG icons (stroke 2, round ends) and takes a phase `t` in 0..1, so a button
can play a short animation that says what the icon does — scissors snip,
the loop turns, a clapper claps. At t = 0 and t = 1 an icon is at rest and
looks exactly like its SVG in assets/icons/actions/ (the same path data),
so a static place (a header) and a moving one (a button) show one shape.

    paint_motion_icon("scissors", painter, rect, color, t)
    "scissors" in MOTION_ICONS

To add one: the SVG file as usual, then a function here that draws it at
phase t with the helpers below, registered in MOTION_ICONS under the SVG's
name. Keep the rest pose identical to the SVG.
"""
import math
import re

import msl_tools.msl.ui.qt_bindings as qt

GRID = 24.0
_TOKEN = re.compile(r"([MLHVCZ])|(-?\d*\.?\d+)")
_paths: dict[str, "qt.QtGui.QPainterPath"] = {}


def path(data: str) -> "qt.QtGui.QPainterPath":
    """A QPainterPath from SVG path data — absolute M L H V C Z only (what the icons use). Cached."""
    cached = _paths.get(data)
    if cached is not None:
        return cached
    result = qt.QtGui.QPainterPath()
    command, numbers = "", []
    x = y = 0.0

    def flush() -> None:
        nonlocal x, y, numbers
        if command == "M":
            for index in range(0, len(numbers) - 1, 2):
                x, y = numbers[index], numbers[index + 1]
                result.moveTo(x, y) if index == 0 else result.lineTo(x, y)
        elif command == "L":
            for index in range(0, len(numbers) - 1, 2):
                x, y = numbers[index], numbers[index + 1]
                result.lineTo(x, y)
        elif command == "H":
            for value in numbers:
                x = value
                result.lineTo(x, y)
        elif command == "V":
            for value in numbers:
                y = value
                result.lineTo(x, y)
        elif command == "C":
            for index in range(0, len(numbers) - 5, 6):
                x, y = numbers[index + 4], numbers[index + 5]
                result.cubicTo(numbers[index], numbers[index + 1], numbers[index + 2], numbers[index + 3], x, y)
        elif command == "Z":
            result.closeSubpath()
        numbers = []

    for letter, number in _TOKEN.findall(data):
        if letter:
            flush()
            command = letter
        else:
            numbers.append(float(number))
    flush()
    _paths[data] = result
    return result


# --- the phase, shaped -----------------------------------------------------------------------


def there_and_back(t: float) -> float:
    """0 -> 1 -> 0 over the animation, smoothly."""
    return math.sin(math.pi * t) if 0.0 < t < 1.0 else 0.0


def ease(t: float) -> float:
    """0 -> 1, slow at both ends."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def window(t: float, start: float, end: float) -> float:
    """0 before `start`, 1 after `end`, eased in between."""
    return ease((t - start) / (end - start)) if end > start else float(t >= end)


def _moving(t: float) -> bool:
    return 0.0 < t < 1.0


# --- the icons -------------------------------------------------------------------------------

_FRAME = "M5 4H19C20.1 4 21 4.9 21 6V18C21 19.1 20.1 20 19 20H5C3.9 20 3 19.1 3 18V6C3 4.9 3.9 4 5 4Z"


def _compress(p, t) -> None:
    """Two arrows push toward the middle."""
    d = 2.2 * there_and_back(t)
    p.save(); p.translate(d, -d); p.drawPath(path("M4 14H10V20")); p.drawPath(path("M3 21L10 14")); p.restore()
    p.save(); p.translate(-d, d); p.drawPath(path("M20 10H14V4")); p.drawPath(path("M14 10L21 3")); p.restore()


def _scissors(p, t) -> None:
    """The blades snip twice."""
    angle = 13.0 * abs(math.sin(2.0 * math.pi * t)) if _moving(t) else 0.0
    for sign, circle_y, blades in ((1.0, 18.0, ("M20 4L8.12 15.88",)),
                                   (-1.0, 6.0, ("M14.47 14.48L20 20", "M8.12 8.12L12 12"))):
        p.save()
        p.translate(12, 12); p.rotate(sign * angle); p.translate(-12, -12)
        p.drawEllipse(qt.QtCore.QPointF(6, circle_y), 3, 3)
        for blade in blades:
            p.drawPath(path(blade))
        p.restore()


def _repeat(p, t) -> None:
    """The loop turns half a round — onto itself."""
    p.translate(12, 12); p.rotate(180.0 * ease(t)); p.translate(-12, -12)
    for data in ("M17 2L21 6L17 10", "M3 11V10C3 7.8 4.8 6 7 6H21", "M7 22L3 18L7 14",
                 "M21 13V14C21 16.2 19.2 18 17 18H3"):
        p.drawPath(path(data))


def _text_frame(p, t) -> None:
    """The letter is lifted and stamped onto the picture."""
    p.drawPath(path(_FRAME))
    lift = 3.2 * there_and_back(min(t / 0.75, 1.0)) if _moving(t) else 0.0
    press = 1.0 + 0.16 * there_and_back(window(t, 0.75, 1.0)) if _moving(t) else 1.0
    p.translate(12, 12.25 - lift); p.scale(press, press); p.translate(-12, -12.25)
    p.drawPath(path("M8.5 9H15.5")); p.drawPath(path("M12 9V15.5"))


def _volume(p, t) -> None:
    """The sound comes out: one wave, then the next."""
    p.drawPath(path("M11 5L6 9H3V15H6L11 19V5Z"))
    waves = ("M15.5 8.5C17.4 10.4 17.4 13.6 15.5 15.5", "M18.4 5.6C21.9 9.1 21.9 14.9 18.4 18.4")
    for data, (start, end) in zip(waves, ((0.10, 0.40), (0.40, 0.75))):
        opacity = window(t, start, end) if _moving(t) else 1.0
        if opacity > 0.0:
            p.setOpacity(opacity)
            p.drawPath(path(data))
    p.setOpacity(1.0)


def _gif(p, t) -> None:
    """The letters hop one after another."""
    letters = (("M8.4 8.3C7.8 7.1 6.9 6.5 5.8 6.5C3.7 6.5 2.5 8.6 2.5 12C2.5 15.4 3.7 17.5 5.8 17.5C7.6 17.5 8.6 16.2 8.6 "
                "13.8V12.6H6.3",), ("M12.2 6.5V17.5",), ("M16 17.5V6.5H21.5", "M16 12H20.2"))
    for index, parts in enumerate(letters):
        hop = 3.0 * there_and_back(window(t, 0.18 * index, 0.18 * index + 0.55)) if _moving(t) else 0.0
        p.save(); p.translate(0, -hop)
        for data in parts:
            p.drawPath(path(data))
        p.restore()


def _image_stack(p, t) -> None:
    """The pictures fan apart."""
    d = 1.6 * there_and_back(t)
    p.save(); p.translate(d, -d)
    p.drawPath(path("M9 3H19C20.1 3 21 3.9 21 5V13C21 14.1 20.1 15 19 15H9C7.9 15 7 14.1 7 13V5C7 3.9 7.9 3 9 3Z"))
    p.drawPath(path("M7 12.5L10.5 9.5L13.5 12L16 10L21 14"))
    p.restore()
    p.save(); p.translate(-d, d); p.drawPath(path("M3 8V17C3 18.1 3.9 19 5 19H16")); p.restore()


def _clapper(p, t) -> None:
    """The clapper opens and claps shut."""
    p.drawPath(path("M3 11H21V19C21 20.1 20.1 21 19 21H5C3.9 21 3 20.1 3 19V11Z"))
    opened = there_and_back(min(t / 0.8, 1.0)) if _moving(t) else 0.0
    p.translate(3, 11); p.rotate(-20.0 * opened); p.translate(-3, -11)
    for data in ("M3 11L4.2 6.4L20.4 3L21 7.2L3 11Z", "M8.2 5.6L10 9.5", "M13.6 4.4L15.4 8.4"):
        p.drawPath(path(data))


def _crop(p, t) -> None:
    """The crop frame turns a quarter and back."""
    p.translate(12, 12); p.rotate(90.0 * there_and_back(t)); p.translate(-12, -12)
    p.drawPath(path("M6 2V16C6 17.1 6.9 18 8 18H22")); p.drawPath(path("M2 6H16C17.1 6 18 6.9 18 8V22"))


def _merge(p, t) -> None:
    """The two pieces come together."""
    d = 2.6 * there_and_back(t)
    p.save(); p.translate(d, 0); p.drawPath(path("M3 7H7V17H3")); p.restore()
    p.save(); p.translate(-d, 0); p.drawPath(path("M21 7H17V17H21")); p.restore()
    p.setOpacity(1.0 - there_and_back(t))
    p.drawPath(path("M12 9.5V14.5")); p.drawPath(path("M9.5 12H14.5"))
    p.setOpacity(1.0)


def _split_view(p, t) -> None:
    """The divider slides to one side, then the other."""
    p.drawPath(path(_FRAME))
    x = 12.0 + (4.5 * math.sin(2.0 * math.pi * t) if _moving(t) else 0.0)
    p.drawLine(qt.QtCore.QPointF(x, 4), qt.QtCore.QPointF(x, 20))


def _film(p, t) -> None:
    """The film runs: its perforation moves along."""
    p.drawPath(path("M5 3H19C20.1 3 21 3.9 21 5V19C21 20.1 20.1 21 19 21H5C3.9 21 3 20.1 3 19V5C3 3.9 3.9 3 5 3Z"))
    p.drawPath(path("M7.5 3V21")); p.drawPath(path("M16.5 3V21")); p.drawPath(path("M3 12H21"))
    shift = 8.0 * ease(t) if _moving(t) else 0.0
    p.setClipRect(qt.QtCore.QRectF(2, 4, 20, 16))
    for y in (0.0, 8.0, 16.0):
        if abs(y + shift - 12.0) < 0.01:
            continue  # the middle line is there already
        for x1, x2 in ((3.0, 7.5), (16.5, 21.0)):
            p.drawLine(qt.QtCore.QPointF(x1, y + shift), qt.QtCore.QPointF(x2, y + shift))
    p.setClipping(False)


MOTION_ICONS = {
    "compress": _compress, "scissors": _scissors, "repeat": _repeat, "text_frame": _text_frame, "volume": _volume,
    "gif": _gif, "image_stack": _image_stack, "clapper": _clapper, "crop": _crop, "merge": _merge,
    "split_view": _split_view, "film": _film,
}
# How long each one plays, in milliseconds (a snip is quick, a hop of three letters takes longer).
DURATIONS = {"scissors": 520, "gif": 760, "volume": 700, "repeat": 560, "film": 560, "split_view": 700}
DEFAULT_DURATION = 480


def paint_motion_icon(name: str, painter: "qt.QtGui.QPainter", rect, color, t: float = 0.0) -> bool:
    """Draws motion icon `name` at phase `t` into `rect` in `color`. False if there is no such icon."""
    draw = MOTION_ICONS.get(name)
    if draw is None:
        return False
    rect = qt.QtCore.QRectF(rect)
    side = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side / GRID, side / GRID)
    pen = qt.QtGui.QPen(qt.QtGui.QColor(color), 2.0)
    pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
    draw(painter, min(max(float(t), 0.0), 1.0))
    painter.restore()
    return True
