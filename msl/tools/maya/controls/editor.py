# tools/maya/controls/editor.py
"""The shape editor: the preview grown to the library's room, where a shape's points are edited by
hand — no Maya needed (Qt only; the shape is data, see shapes.py).

    EditorCanvas   the picture: the curves, a handle on every point, the pivot; tools that drag
                   points, move / turn / scale the shape (or the picked points), add and remove points
    ShapeEditor    the canvas with its tools beside it and, under it: the views, undo / redo, reset,
                   save, and what to do with the result

Points are edited in the three straight views (Top / Front / Side: a drag moves a point in the plane
of the screen); the 3/4 view is for looking only — there a drag turns the view. The shape is the
library's own, facing +Y: the axis a control faces is applied when it is made, as always.
"""
import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.controls import shapes as shape_data
from msl_tools.msl.tools.maya.controls.preview import THUMB_YAW, _projected
from msl_tools.msl.tools.maya.rename.buttons import QuickButton
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl

VIEWS = ("Top", "Front", "Side", "3/4")
TOOLS = ("points", "move", "turn", "scale", "add", "remove")
HANDLE = 4.0            # half a point's handle, px
PICK = 8.0              # how near a click must be, px
SNAP = 0.05             # with Ctrl held: moves go by this
UNDO_STEPS = 60


def _copied(curves: list) -> list:
    return [shape_data.Curve([tuple(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]


class EditorCanvas(qt.QtWidgets.QWidget):
    """The shape with a handle on every point. Tools (`set_tool`): "points" — click a point (Shift:
    more; drag on empty room: a frame around several) and drag it; "move" / "turn" / "scale" — the
    picked points, or the whole shape when none is picked, about the pivot; "add" — a click on a line
    puts a point there; "remove" — a click on a point takes it out. Ctrl while dragging: by steps.
    The wheel zooms, the middle button (or Alt + drag) pans, F fits, A picks all, Delete removes the
    picked points, Ctrl+Z / Ctrl+Y undo and redo.

    Signals:
        edited() — the curves were changed (also by undo / redo).
        picked_changed(int) — how many points are picked.
    """

    edited = qt.QtCore.Signal()
    picked_changed = qt.QtCore.Signal(int)

    groundColor = color_property("_ground", "update")
    gridColor = color_property("_grid", "update")
    lineColor = color_property("_line", "update")
    pointColor = color_property("_point", "update")
    pickedColor = color_property("_picked_color", "update")
    pivotColor = color_property("_pivot", "update")
    textColor = color_property("_text", "update")

    def __init__(self, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()
        self._ground = qt.QtGui.QColor(fallback.surface)
        self._grid = qt.QtGui.QColor(fallback.border)
        self._line = qt.QtGui.QColor(fallback.accent)
        self._point = qt.QtGui.QColor(fallback.text_primary)
        self._picked_color = qt.QtGui.QColor(fallback.accent)
        self._pivot = qt.QtGui.QColor(fallback.text_secondary)
        self._text = qt.QtGui.QColor(fallback.text_secondary)
        self._curves = []
        self._title = ""
        self._picked = set()            # (curve index, point index)
        self._tool = "points"
        self._view = "Top"
        self._symmetry = False
        self._extent = 1.35
        self._zoom = 1.0
        self._pan = qt.QtCore.QPointF(0, 0)
        self._yaw, self._pitch = THUMB_YAW, 28.0
        self._drag = None               # what the pressed mouse is doing
        self._frame = None              # the selection frame (QRectF) while it is dragged
        self._undo, self._redo = [], []
        self.setMinimumSize(200, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)

    # ------------------------------------------------------------------ what it holds

    def set_curves(self, curves: list, title: str = "") -> None:
        """A shape to edit (copied); the history starts anew."""
        self._curves = _copied(curves)
        self._title = title
        self._picked.clear()
        self._undo, self._redo = [], []
        self._view = "Top" if self._is_flat() else self._view if self._view != "Top" else "3/4"
        self.fit()
        self.picked_changed.emit(0)

    def curves(self) -> list:
        return _copied(self._curves)

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def view(self) -> str:
        return self._view

    def set_view(self, view: str) -> None:
        if view in VIEWS and view != self._view:
            self._view = view
            self.update()

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool in TOOLS:
            self._tool = tool
            self.update()

    def set_symmetry(self, on: bool) -> None:
        self._symmetry = bool(on)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def picked(self) -> int:
        return len(self._picked)

    def _is_flat(self) -> bool:
        return all(abs(point[1]) < 1e-4 for curve in self._curves for point in curve.points)

    def fit(self) -> None:
        """The whole shape (and its pivot) in view."""
        reach = max([abs(value) for curve in self._curves for point in curve.points for value in point] or [1.0])
        self._extent = max(reach, 0.25) * 1.35
        self._zoom = 1.0
        self._pan = qt.QtCore.QPointF(0, 0)
        self.update()

    # ------------------------------------------------------------------ history

    def _remember(self) -> None:
        self._undo.append((_copied(self._curves), set(self._picked)))
        del self._undo[:-UNDO_STEPS]
        self._redo = []

    def _changed(self) -> None:
        self.update()
        self.edited.emit()
        self.picked_changed.emit(len(self._picked))

    def undo(self) -> None:
        if self._undo:
            self._redo.append((_copied(self._curves), set(self._picked)))
            self._curves, self._picked = self._undo.pop()
            self._changed()

    def redo(self) -> None:
        if self._redo:
            self._undo.append((_copied(self._curves), set(self._picked)))
            self._curves, self._picked = self._redo.pop()
            self._changed()

    # ------------------------------------------------------------------ whole-shape edits (buttons)

    def pick_all(self) -> None:
        self._picked = {(c, p) for c, curve in enumerate(self._curves) for p in range(len(curve.points))}
        self.update()
        self.picked_changed.emit(len(self._picked))

    def remove_picked(self) -> None:
        """The picked points go — a curve keeps at least two (three if it is closed)."""
        if not self._picked:
            return
        self._remember()
        for c, curve in enumerate(self._curves):
            gone = sorted((p for cc, p in self._picked if cc == c), reverse=True)
            least = 3 if curve.closed else 2
            for p in gone:
                if len(curve.points) > least:
                    del curve.points[p]
            curve.degree = max(1, min(curve.degree, len(curve.points) - 1))
        self._picked.clear()
        self._changed()

    def toggle_smooth(self) -> None:
        """Straight lines <-> a smooth curve, for the curves of the picked points (all, when none)."""
        wanted = {c for c, _p in self._picked} or set(range(len(self._curves)))
        if not wanted:
            return
        self._remember()
        for c in wanted:
            curve = self._curves[c]
            if curve.degree > 1:
                curve.degree = 1
            elif len(curve.points) >= (3 if curve.closed else 4):
                curve.degree = 3
        self._changed()

    # ------------------------------------------------------------------ view <-> shape

    def _scale(self) -> float:
        return self._zoom * min(self.width(), self.height()) / 2.0 / self._extent

    def _on_screen(self, point) -> "qt.QtCore.QPointF":
        if self._view == "3/4":
            x, y, _depth = _projected(point, self._yaw, self._pitch)
            sx, sy = x, -y
        elif self._view == "Front":
            sx, sy = point[0], -point[1]
        elif self._view == "Side":
            sx, sy = point[2], -point[1]
        else:
            sx, sy = point[0], point[2]
        scale = self._scale()
        return qt.QtCore.QPointF(self.width() / 2.0 + self._pan.x() + sx * scale,
                                 self.height() / 2.0 + self._pan.y() + sy * scale)

    def _in_shape(self, dx: float, dy: float) -> tuple:
        """A move on the screen as a move of a point (in the plane of the view)."""
        scale = self._scale()
        if self._view == "Front":
            return dx / scale, -dy / scale, 0.0
        if self._view == "Side":
            return 0.0, -dy / scale, dx / scale
        return dx / scale, 0.0, dy / scale

    def _point_at(self, spot) -> "tuple | None":
        best, nearest = None, PICK
        for c, curve in enumerate(self._curves):
            for p, point in enumerate(curve.points):
                away = self._on_screen(point) - spot
                distance = math.hypot(away.x(), away.y())
                if distance <= nearest:
                    best, nearest = (c, p), distance
        return best

    def _line_at(self, spot) -> "tuple | None":
        """(curve, the point index a new point gets, where on the line) nearest to a click."""
        best, nearest = None, PICK * 1.5
        for c, curve in enumerate(self._curves):
            count = len(curve.points)
            for p in range(count if curve.closed else count - 1):
                a, b = curve.points[p], curve.points[(p + 1) % count]
                sa, sb = self._on_screen(a), self._on_screen(b)
                along = sb - sa
                length = along.x() ** 2 + along.y() ** 2
                t = 0.5 if length < 1e-9 else max(0.0, min(1.0, ((spot.x() - sa.x()) * along.x() +
                                                                 (spot.y() - sa.y()) * along.y()) / length))
                foot = sa + along * t
                distance = math.hypot(spot.x() - foot.x(), spot.y() - foot.y())
                if distance <= nearest:
                    best, nearest = (c, p + 1, tuple(x + (y - x) * t for x, y in zip(a, b))), distance
        return best

    # ------------------------------------------------------------------ the mouse

    def _targets(self) -> list:
        """What move / turn / scale act on: the picked points, or every point."""
        return sorted(self._picked) or [(c, p) for c, curve in enumerate(self._curves) for p in range(len(curve.points))]

    def _partners(self, targets: list) -> dict:
        """With symmetry on: for each moved point, the point that mirrors it across X (not moved itself)."""
        if not self._symmetry:
            return {}
        moved = set(targets)
        near = self._extent * 1e-3
        found = {}
        for c, p in targets:
            x, y, z = self._curves[c].points[p]
            if abs(x) <= near:
                continue
            for cc, curve in enumerate(self._curves):
                for pp, other in enumerate(curve.points):
                    if (cc, pp) not in moved and abs(other[0] + x) <= near and abs(other[1] - y) <= near \
                            and abs(other[2] - z) <= near:
                        found[(c, p)] = (cc, pp)
        return found

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        spot = event.position()
        alt = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.AltModifier)
        shift = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        if event.button() == qt.QtCore.Qt.MouseButton.MiddleButton or \
                (event.button() == qt.QtCore.Qt.MouseButton.LeftButton and alt):
            self._drag = {"kind": "pan", "from": spot, "pan": qt.QtCore.QPointF(self._pan)}
            return
        if event.button() != qt.QtCore.Qt.MouseButton.LeftButton:
            return
        if self._view == "3/4":
            self._drag = {"kind": "orbit", "from": spot, "yaw": self._yaw, "pitch": self._pitch}
            return
        hit = self._point_at(spot)
        if self._tool == "remove":
            if hit:
                self._picked = {hit}
                self.remove_picked()
            return
        if self._tool == "add":
            line = self._line_at(spot)
            if not line:
                return
            self._remember()
            c, p, where = line
            self._curves[c].points.insert(p, where)
            self._picked = {(c, p)}
            self._changed()
            self._start_edit("points", spot, remembered=True)
            return
        if self._tool == "points":
            if hit is None:
                self._drag = {"kind": "frame", "from": spot, "keep": set(self._picked) if shift else set()}
                return
            if shift:
                self._picked ^= {hit}
            elif hit not in self._picked:
                self._picked = {hit}
            self.picked_changed.emit(len(self._picked))
            self.update()
            if hit in self._picked:
                self._start_edit("points", spot)
            return
        self._start_edit(self._tool, spot)

    def _start_edit(self, kind: str, spot, remembered: bool = False) -> None:
        targets = sorted(self._picked) if kind == "points" else self._targets()
        self._drag = {"kind": kind, "from": spot, "targets": targets, "partners": self._partners(targets),
                      "start": _copied(self._curves), "remembered": remembered, "moved": False}

    def mouseMoveEvent(self, event) -> None:
        drag, spot = self._drag, event.position()
        if drag is None:
            over = self._view != "3/4" and self._tool in ("points", "remove") and self._point_at(spot) is not None
            self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor if over else qt.QtCore.Qt.CursorShape.ArrowCursor)
            return
        delta = spot - drag["from"]
        kind = drag["kind"]
        if kind == "pan":
            self._pan = drag["pan"] + delta
        elif kind == "orbit":
            self._yaw = drag["yaw"] - delta.x() * 0.6
            self._pitch = max(-89.0, min(89.0, drag["pitch"] + delta.y() * 0.6))
        elif kind == "frame":
            self._frame = qt.QtCore.QRectF(drag["from"], spot).normalized()
            inside = {(c, p) for c, curve in enumerate(self._curves) for p, point in enumerate(curve.points)
                      if self._frame.contains(self._on_screen(point))}
            self._picked = drag["keep"] | inside
            self.picked_changed.emit(len(self._picked))
        else:
            if not drag["moved"] and abs(delta.x()) + abs(delta.y()) < 2:
                return
            if not drag["remembered"]:
                self._undo.append((drag["start"], set(self._picked)))
                del self._undo[:-UNDO_STEPS]
                self._redo = []
                drag["remembered"] = True
            drag["moved"] = True
            stepped = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
            self._apply(drag, delta, stepped)
        self.update()

    def _apply(self, drag: dict, delta, stepped: bool) -> None:
        """The drag so far, applied to the points as they were when it began."""
        start, kind = drag["start"], drag["kind"]

        def put(target, point) -> None:
            self._curves[target[0]].points[target[1]] = tuple(point)

        if kind in ("points", "move"):
            move = self._in_shape(delta.x(), delta.y())
            if stepped:
                move = tuple(round(value / SNAP) * SNAP for value in move)
            near = self._extent * 1e-3
            for target in drag["targets"]:
                was = start[target[0]].points[target[1]]
                shift = list(move)
                if self._symmetry and abs(was[0]) <= near:
                    shift[0] = 0.0                      # a point on the mirror line stays on it
                put(target, (a + b for a, b in zip(was, shift)))
                partner = drag["partners"].get(target)
                if partner:
                    other = start[partner[0]].points[partner[1]]
                    put(partner, (other[0] - shift[0], other[1] + shift[1], other[2] + shift[2]))
            return
        if kind == "turn":
            degrees = delta.x() * 0.5
            if stepped:
                degrees = round(degrees / 15.0) * 15.0
            axis = {"Front": "Z", "Side": "X"}.get(self._view, "Y")
            # the same turn on the screen whatever the view: a drag to the right turns clockwise
            degrees = degrees if axis == "Y" else -degrees
            for target in drag["targets"]:
                was = start[target[0]].points[target[1]]
                put(target, shape_data.turned([shape_data.Curve([was])], axis, degrees)[0].points[0])
            return
        factor = max(0.05, 1.0 + delta.x() / 150.0)
        if stepped:
            factor = max(0.1, round(factor / 0.1) * 0.1)
        for target in drag["targets"]:
            was = start[target[0]].points[target[1]]
            put(target, (value * factor for value in was))

    def mouseReleaseEvent(self, event) -> None:
        drag, self._drag = self._drag, None
        self._frame = None
        if drag and drag.get("moved"):
            self._keep_in_view()
            self._changed()
        self.update()

    def _keep_in_view(self) -> None:
        """After an edit that took a point out of the picture, the whole shape is brought back in."""
        room = qt.QtCore.QRectF(self.rect()).adjusted(8, 8, -8, -8)
        if any(not room.contains(self._on_screen(point)) for curve in self._curves for point in curve.points):
            self.fit()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._view == "3/4":
            self._yaw, self._pitch = THUMB_YAW, 28.0
            self.update()
        elif self._point_at(event.position()) is None:
            self.fit()

    def wheelEvent(self, event) -> None:
        self._zoom = max(0.2, min(12.0, self._zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()
        event.accept()

    def keyPressEvent(self, event) -> None:
        control = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        shift = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        key = event.key()
        if key in (qt.QtCore.Qt.Key.Key_Delete, qt.QtCore.Qt.Key.Key_Backspace):
            self.remove_picked()
        elif control and key == qt.QtCore.Qt.Key.Key_Z:
            self.redo() if shift else self.undo()
        elif control and key == qt.QtCore.Qt.Key.Key_Y:
            self.redo()
        elif key == qt.QtCore.Qt.Key.Key_A:
            self.pick_all()
        elif key == qt.QtCore.Qt.Key.Key_F:
            self.fit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()          # these are the editor's: Maya's own hotkeys must not answer them too

    # ------------------------------------------------------------------ the picture

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        frame = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(qt.QtGui.QPen(self._grid, 1))
        painter.setBrush(self._ground)
        painter.drawRoundedRect(frame, 6, 6)
        painter.setClipRect(frame.adjusted(1, 1, -1, -1))
        looking = self._view == "3/4"

        # the grid of the view's plane (the ground, in 3/4), a line every half unit
        faint = qt.QtGui.QColor(self._grid)
        faint.setAlpha(90)
        steps = max(2, min(40, int(math.ceil(self._extent / 0.5)) + 1))

        def on_plane(a: float, b: float) -> tuple:
            return {"Front": (a, b, 0.0), "Side": (0.0, b, a)}.get(self._view, (a, 0.0, b))

        reach = steps * 0.5
        for step in range(-steps, steps + 1):
            value = step * 0.5
            strong = qt.QtGui.QColor(self._grid) if step == 0 else faint
            painter.setPen(qt.QtGui.QPen(strong, 1.0 if step == 0 else 0.7))
            painter.drawLine(self._on_screen(on_plane(value, -reach)), self._on_screen(on_plane(value, reach)))
            painter.drawLine(self._on_screen(on_plane(-reach, value)), self._on_screen(on_plane(reach, value)))

        # the pivot: where the control's own point is — what "move the shape" moves the shape away from
        pivot = self._on_screen((0.0, 0.0, 0.0))
        painter.setPen(qt.QtGui.QPen(self._pivot, 1.6))
        painter.drawLine(pivot + qt.QtCore.QPointF(-7, 0), pivot + qt.QtCore.QPointF(7, 0))
        painter.drawLine(pivot + qt.QtCore.QPointF(0, -7), pivot + qt.QtCore.QPointF(0, 7))

        # the curves; for a smooth one also the cage of its points, faintly
        for curve in self._curves:
            if curve.degree > 1 and not looking:
                cage = qt.QtGui.QPen(faint, 1.0)
                cage.setStyle(qt.QtCore.Qt.PenStyle.DashLine)
                painter.setPen(cage)
                spots = [self._on_screen(point) for point in curve.points]
                painter.drawPolyline(qt.QtGui.QPolygonF(spots + (spots[:1] if curve.closed else [])))
            pen = qt.QtGui.QPen(self._line, 2.0)
            pen.setJoinStyle(qt.QtCore.Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
            painter.drawPolyline(qt.QtGui.QPolygonF([self._on_screen(point)
                                                     for point in shape_data.polyline(curve, 8)]))

        # a handle on every point (not while only looking)
        if not looking:
            for c, curve in enumerate(self._curves):
                for p, point in enumerate(curve.points):
                    spot = self._on_screen(point)
                    picked = (c, p) in self._picked
                    half = HANDLE + (1.0 if picked else 0.0)
                    painter.setPen(qt.QtGui.QPen(self._picked_color if picked else self._point, 1.4))
                    painter.setBrush(self._picked_color if picked else self._ground)
                    painter.drawRect(qt.QtCore.QRectF(spot.x() - half, spot.y() - half, half * 2, half * 2))
        if self._frame is not None:
            wash = qt.QtGui.QColor(self._picked_color)
            wash.setAlpha(40)
            painter.setPen(qt.QtGui.QPen(self._picked_color, 1.0))
            painter.setBrush(wash)
            painter.drawRect(self._frame)

        # what it is, and what the mouse does here
        painter.setClipping(False)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(self._text)
        painter.drawText(qt.QtCore.QRectF(10, 6, self.width() - 60, 16),
                         qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter, self._title)
        hint = "Looking only — pick Top, Front or Side to edit · drag turns the view" if looking else {
            "points": "Click a point, Shift for more, drag a frame · drag to move · Ctrl: by steps",
            "move": "Drag: the picked points — or the whole shape — move away from the pivot",
            "turn": "Drag sideways: turn about the pivot · Ctrl: by 15°",
            "scale": "Drag sideways: bigger / smaller about the pivot",
            "add": "Click on a line: a new point there",
            "remove": "Click a point: it goes"}[self._tool]
        painter.drawText(qt.QtCore.QRectF(10, self.height() - 22, self.width() - 20, 16),
                         qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(hint, qt.QtCore.Qt.TextElideMode.ElideRight, self.width() - 20))
        painter.end()


class ShapeEditor(qt.QtWidgets.QWidget):
    """The canvas with its tools: a column of tool buttons beside it; under it the views, undo /
    redo, reset and save; then what to do with the shape. The owner gives it a shape (`open`) and
    listens.

    Signals:
        edited() — the shape was changed (`curves()` is the result).
        reset_requested() / save_requested() / closed()
        create_requested() / apply_requested() — a new control of it / onto the selected controls.
    """

    edited = qt.QtCore.Signal()
    reset_requested = qt.QtCore.Signal()
    save_requested = qt.QtCore.Signal()
    closed = qt.QtCore.Signal()
    create_requested = qt.QtCore.Signal()
    apply_requested = qt.QtCore.Signal()

    TOOL_LINES = (("points", "cvs", "Points", "Pick points and drag them"),
                  ("move", "move", "Move", "Move the picked points — or the whole shape away from the pivot"),
                  ("turn", "restart", "Turn", "Turn the picked points — or the whole shape — about the pivot"),
                  ("scale", "grow", "Scale", "Scale the picked points — or the whole shape — about the pivot"),
                  ("add", "add", "Add a point", "A click on a line puts a point there"),
                  ("remove", "minus", "Remove a point", "A click on a point takes it out (Delete: the picked ones)"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlsEditor")
        icons = UiResources().iconManager
        self.canvas = EditorCanvas()
        self.canvas.setObjectName("controlsEditorCanvas")

        def button(icon: str, text: str, tooltip: str) -> QuickButton:
            made = QuickButton(icons.get_icon(icon, sub_folder="actions"), text, f"{text}\n{tooltip}", icon_size=16)
            made.setObjectName("controlsTool")
            return made

        self._tools = {}
        column = qt.QtWidgets.QVBoxLayout()
        column.setSpacing(3)
        column.setContentsMargins(0, 0, 0, 0)
        for index, (key, icon, text, tooltip) in enumerate(self.TOOL_LINES):
            if index == 4:
                column.addSpacing(6)
            self._tools[key] = button(icon, text, tooltip)
            self._tools[key].clicked.connect(lambda _checked=False, key=key: self.set_tool(key))
            column.addWidget(self._tools[key])
        column.addSpacing(6)
        self._smooth = button("smooth_curve", "Smooth / straight", "The curves of the picked points (all, when none "
                                                                   "is picked): straight lines ↔ a smooth curve")
        self._symmetry = button("mirror_sides", "Symmetry", "On: what is done to a point on one side of X is done to "
                                                            "its mirror point too; points on the middle line stay on it")
        column.addWidget(self._smooth)
        column.addWidget(self._symmetry)
        column.addStretch(1)
        self._close = button("collapse", "Back to the library", "Close the editor: the shape stays as you left it "
                                                                "until you pick another one")
        column.addWidget(self._close)

        top = qt.QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        top.addLayout(column)
        top.addWidget(self.canvas, 1)

        self._views = SegmentedControl(list(VIEWS), "Top")
        self._views.setToolTip("Top / Front / Side: a point moves in the plane of the screen · 3/4: looking only")
        self._undo = button("undo", "Undo", "Ctrl+Z")
        self._redo = button("redo", "Redo", "Ctrl+Y")
        self._reset = qt.QtWidgets.QPushButton("Reset")
        self._reset.setToolTip("Back to the shape as the library has it")
        self._save = qt.QtWidgets.QPushButton("Save as…")
        self._save.setToolTip("Keep this shape among yours (it goes under Mine)")
        bar = qt.QtWidgets.QHBoxLayout()
        bar.setSpacing(4)
        bar.addWidget(self._views)
        bar.addSpacing(6)
        bar.addWidget(self._undo)
        bar.addWidget(self._redo)
        bar.addStretch(1)
        bar.addWidget(self._reset)
        bar.addWidget(self._save)

        self._create = qt.QtWidgets.QPushButton("Create")
        self._create.setProperty("primary", True)
        self._create.setObjectName("controlsCreate")
        self._apply = qt.QtWidgets.QPushButton("Onto the selected controls")
        self._apply.setObjectName("controlsCreate")
        self._apply.setToolTip("The selected controls get this shape — as big as theirs, their own color")
        ends = qt.QtWidgets.QHBoxLayout()
        ends.setSpacing(6)
        ends.addWidget(self._create, 1)
        ends.addWidget(self._apply, 1)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(top, 1)
        layout.addLayout(bar)
        layout.addLayout(ends)

        self.canvas.edited.connect(self._on_edited)
        self.canvas.picked_changed.connect(lambda _count: self._show_state())
        self._views.current_changed.connect(self.canvas.set_view)
        self._smooth.clicked.connect(self.canvas.toggle_smooth)
        self._symmetry.clicked.connect(self._toggle_symmetry)
        self._undo.clicked.connect(self.canvas.undo)
        self._redo.clicked.connect(self.canvas.redo)
        self._reset.clicked.connect(self.reset_requested)
        self._save.clicked.connect(self.save_requested)
        self._close.clicked.connect(self.closed)
        self._create.clicked.connect(self.create_requested)
        self._apply.clicked.connect(self.apply_requested)
        self._symmetric = False
        self.set_tool("points")
        self._show_state()

    # ---- for the owner

    def open(self, curves: list, title: str) -> None:
        self.canvas.set_curves(curves, title)
        self._views.set_current(self.canvas.view(), animate=False)
        self._show_state()

    def curves(self) -> list:
        return self.canvas.curves()

    def set_title(self, title: str) -> None:
        self.canvas.set_title(title)

    def set_create_text(self, text: str) -> None:
        self._create.setText(text)

    def save_button(self) -> "qt.QtWidgets.QPushButton":
        return self._save

    def set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        for key, made in self._tools.items():
            self._lit(made, key == tool)

    # ---- its own

    @staticmethod
    def _lit(made, on: bool) -> None:
        if bool(made.property("on")) != on:
            made.setProperty("on", on)
            repolish(made)

    def _toggle_symmetry(self) -> None:
        self._symmetric = not self._symmetric
        self.canvas.set_symmetry(self._symmetric)
        self._lit(self._symmetry, self._symmetric)

    def _on_edited(self) -> None:
        self._show_state()
        self.edited.emit()

    def _show_state(self) -> None:
        self._undo.setEnabled(self.canvas.can_undo())
        self._redo.setEnabled(self.canvas.can_redo())
