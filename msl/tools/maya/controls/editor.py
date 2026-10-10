# tools/maya/controls/editor.py
"""The shape editor: the preview grown to the library's room, where a shape's points are edited by
hand — no Maya needed (Qt only; the shape is data, see shapes.py).

    EditorCanvas   the picture: the curves, a handle on every point, the pivot; tools that drag
                   points, move / turn / scale the shape (or the picked points), add and remove points
    ShapeEditor    the canvas with its tools beside it and, under it: the views, undo / redo, reset,
                   save, and what to do with the result

Picking works in every tool; Move / Turn / Scale put a manipulator on the picked points (arms along
the axes). In the straight views (Top / Front / Side) a point also drags freely in the plane of the
screen; in 3/4 the manipulator's three axes do the editing and Alt + drag turns the view. The shape
is the library's own, facing +Y: the axis a control faces is applied when it is made, as always.
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
STEP = 0.1              # the grid's step at first: what "snap" lands on and a nudge moves by
KEYS = {"Q": "points", "W": "move", "E": "turn", "R": "scale"}      # Maya's own keys for these
GIZMO = 46.0            # how long the manipulator's arms are, px
GRAB = 9.0              # how near a click must be to one of its handles, px
UNDO_STEPS = 60


def _copied(curves: list) -> list:
    return [shape_data.Curve([tuple(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]


class EditorCanvas(qt.QtWidgets.QWidget):
    """The shape with a handle on every point.

    PICKING works in every tool, so a tool never has to be left to pick: a click on a point picks it
    (Shift: adds / takes away), a drag over empty room frames several, a click on empty room picks
    none; A picks all.
    Tools (`set_tool`; Q / W / E / R as in Maya): "points" — drag the picked points freely; "move" /
    "turn" / "scale" — a MANIPULATOR stands on the picked points: its arms move / scale along one axis
    (colored like the axes), its middle moves freely / scales evenly, its ring turns; "turn" and "scale"
    go about the pivot, or about the middle of the picked points (`set_about_centre`); "add" — a click
    on a line puts a point there; "remove" — a click on a point takes it out.
    In Top / Front / Side a point also drags freely in the plane of the screen. In 3/4 there is no
    such plane, so there the manipulator's three axes do the editing — and Alt + drag turns the view.
    Snap (`set_snap`, or Ctrl held while dragging): a moved point lands on the grid of `set_step`,
    turns go by 15°, scales by 0.1. `nudge()` — the arrow keys — moves the picked points one step.
    The wheel zooms, the middle button (Alt + drag in the straight views) pans, F fits, Delete removes
    the picked points, Ctrl+Z / Ctrl+Y undo and redo.

    Signals:
        edited() — the curves were changed (also by undo / redo).
        picked_changed(int) — how many points are picked.
        tool_wanted(str) — a key asked for a tool.
    """

    edited = qt.QtCore.Signal()
    picked_changed = qt.QtCore.Signal(int)
    tool_wanted = qt.QtCore.Signal(str)

    groundColor = color_property("_ground", "update")
    gridColor = color_property("_grid", "update")
    lineColor = color_property("_line", "update")
    pointColor = color_property("_point", "update")
    pickedColor = color_property("_picked_color", "update")
    pivotColor = color_property("_pivot", "update")
    xColor = color_property("_x", "update")         # the manipulator's arms, by the axis they move along
    yColor = color_property("_y", "update")
    zColor = color_property("_z", "update")
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
        self._x = qt.QtGui.QColor(fallback.error)
        self._y = qt.QtGui.QColor(fallback.success)
        self._z = qt.QtGui.QColor(fallback.accent)
        self._hot = ""                  # the manipulator's handle under the pointer
        self._text = qt.QtGui.QColor(fallback.text_secondary)
        self._curves = []
        self._title = ""
        self._picked = set()            # (curve index, point index)
        self._tool = "points"
        self._view = "Top"
        self._symmetry = False
        self._snap = False
        self._about_centre = False      # turn / scale about the middle of the picked points, not the pivot
        self._step = STEP
        self._warning = ""              # said in place of the hint until the next press
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

    def set_about_centre(self, on: bool) -> None:
        self._about_centre = bool(on)

    def coordinates(self) -> list:
        """[x, y, z] of the picked points: a number where they all agree, None where they differ (or
        nothing is picked)."""
        points = [self._curves[c].points[p] for c, p in sorted(self._picked)]
        if not points:
            return [None, None, None]
        return [points[0][i] if all(abs(point[i] - points[0][i]) < 1e-6 for point in points) else None
                for i in range(3)]

    def set_coordinate(self, axis: int, value: float) -> None:
        """Every picked point gets `value` on one axis (0 x, 1 y, 2 z): one point is put exactly, several
        are lined up. With symmetry their mirror points follow."""
        targets = sorted(self._picked)
        if not targets:
            self._warn("Pick points first — click one, drag a frame, or A for all")
            return
        self._remember()
        partners = self._partners(targets)
        for target in targets:
            point = list(self._curves[target[0]].points[target[1]])
            point[axis] = float(value)
            self._curves[target[0]].points[target[1]] = tuple(point)
            partner = partners.get(target)
            if partner:
                other = list(self._curves[partner[0]].points[partner[1]])
                other[axis] = -float(value) if axis == 0 else float(value)
                self._curves[partner[0]].points[partner[1]] = tuple(other)
        self._keep_in_view()
        self._changed()

    def align(self, axis: int) -> None:
        """The picked points lined up on one axis, at their average there."""
        points = [self._curves[c].points[p] for c, p in sorted(self._picked)]
        if len(points) < 2:
            self._warn("Pick two or more points to line them up")
            return
        self.set_coordinate(axis, sum(point[axis] for point in points) / len(points))

    def set_snap(self, on: bool) -> None:
        self._snap = bool(on)
        self.update()

    def set_step(self, step: float) -> None:
        self._step = max(0.001, float(step))
        self.update()

    def step(self) -> float:
        return self._step

    def nudge(self, right: int, down: int, times: int = 1) -> None:
        """The picked points one step to the right / down on the screen (-1: left / up) — a small,
        exact move a drag can't make."""
        if self._view == "3/4":             # no plane of the screen there: right = +X, up = +Y
            if right:
                self.nudge_axis(0, right, times)
            if down:
                self.nudge_axis(1, -down, times)
            return
        scale = self._scale()
        self._nudge_by(self._in_shape(right * self._step * times * scale, down * self._step * times * scale))

    def nudge_axis(self, axis: int, sign: int, times: int = 1) -> None:
        """The picked points one step along an axis (0 x, 1 y, 2 z; `sign` -1: the other way) — the
        same in every view, 3/4 too."""
        move = [0.0, 0.0, 0.0]
        move[axis] = sign * self._step * times
        self._nudge_by(move)

    def _nudge_by(self, move) -> None:
        if not self._picked:
            self._warn("Pick points first — click one, drag a frame, or A for all")
            return
        self._remember()
        self._move_points(sorted(self._picked), self._partners(sorted(self._picked)), self._curves, move)
        self._keep_in_view()
        self._changed()

    def _warn(self, text: str) -> None:
        self._warning = text
        self.update()

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
        """What move / turn / scale act on: the picked points — never what isn't picked."""
        return sorted(self._picked)

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

    # ---- the manipulator: where it stands, its handles

    def _plane_axes(self) -> tuple:
        """The axes a point can move along in this view: the two of the screen's plane; all three in 3/4."""
        return {"Top": (0, 2), "Front": (0, 1), "Side": (2, 1)}.get(self._view, (0, 1, 2))

    def _middle_of_picked(self) -> tuple:
        points = [self._curves[c].points[p] for c, p in self._picked]
        return tuple((min(point[i] for point in points) + max(point[i] for point in points)) / 2.0 for i in range(3))

    def _gizmo_origin(self) -> tuple:
        """Move: on the picked points. Turn / scale: on what they go about — the pivot, or their middle."""
        if self._tool == "move" or self._about_centre:
            return self._middle_of_picked()
        return (0.0, 0.0, 0.0)

    def _axis_on_screen(self, origin, axis: int) -> "qt.QtCore.QPointF":
        """How far one unit along an axis goes on the screen, from `origin` (px, a vector)."""
        tip = list(origin)
        tip[axis] += 1.0
        return self._on_screen(tip) - self._on_screen(origin)

    def gizmo_handles(self) -> dict:
        """The manipulator's handles on the screen: "X" / "Y" / "Z" (an arm's end), "free" (move: its
        middle), "all" (scale: its middle), "ring" (turn in a straight view: the middle of the ring).
        Empty when there is none: another tool, or nothing picked."""
        if self._tool not in ("move", "turn", "scale") or not self._picked:
            return {}
        origin = self._gizmo_origin()
        middle = self._on_screen(origin)
        straight = self._view != "3/4"
        handles = {}
        if not (self._tool == "turn" and straight):
            for axis in self._plane_axes():
                arm = self._axis_on_screen(origin, axis)
                length = math.hypot(arm.x(), arm.y())
                if length < self._scale() * 0.2:
                    continue                    # it points at the eye: nothing to pull on
                handles["XYZ"[axis]] = middle + arm * (GIZMO / length)
        if self._tool == "move" and straight:
            handles["free"] = middle
        elif self._tool == "scale":
            handles["all"] = middle
        elif self._tool == "turn" and straight:
            handles["ring"] = middle
        return handles

    def _handle_at(self, spot) -> str:
        handles = self.gizmo_handles()
        for name in ("X", "Y", "Z", "free", "all"):
            if name in handles:
                away = handles[name] - spot
                if math.hypot(away.x(), away.y()) <= GRAB:
                    return name
        if "ring" in handles:
            away = handles["ring"] - spot
            if abs(math.hypot(away.x(), away.y()) - GIZMO) <= GRAB:
                return "ring"
        return ""

    # ---- pressing, dragging

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        self._warning = ""
        spot = event.position()
        alt = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.AltModifier)
        shift = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        left = event.button() == qt.QtCore.Qt.MouseButton.LeftButton
        looking = self._view == "3/4"
        if left and alt and looking:
            self._drag = {"kind": "orbit", "from": spot, "yaw": self._yaw, "pitch": self._pitch}
            return
        if event.button() == qt.QtCore.Qt.MouseButton.MiddleButton or (left and alt):
            self._drag = {"kind": "pan", "from": spot, "pan": qt.QtCore.QPointF(self._pan)}
            return
        if not left:
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
            if not looking:
                self._start_edit("free", "", spot, remembered=True)
            return
        # the manipulator first: its handles lie over the points
        handle = self._handle_at(spot)
        if handle:
            self._start_edit("gizmo", handle, spot)
            return
        if hit is None:
            # empty room: a frame around several — a mere click there picks none
            self._drag = {"kind": "frame", "from": spot, "keep": set(self._picked) if shift else set()}
            if not shift and self._picked:
                self._picked = set()
                self.picked_changed.emit(0)
                self.update()
            return
        if shift:
            self._picked ^= {hit}
        elif hit not in self._picked:
            self._picked = {hit}
        self.picked_changed.emit(len(self._picked))
        self.update()
        # a picked point drags freely where the screen has a plane to drag it in (not in 3/4), in the
        # tools that move points
        if hit in self._picked and not looking and self._tool in ("points", "move"):
            self._start_edit("free", "", spot)

    def _start_edit(self, kind: str, handle: str, spot, remembered: bool = False) -> None:
        targets = self._targets()
        if not targets:
            self._warn("Pick points first — click one, drag a frame, or A for all")
            return
        # the point under the pointer (else the first picked one) is the one that lands on the grid
        hit = self._point_at(spot)
        anchor = hit if hit in targets else targets[0]
        origin = self._gizmo_origin() if kind == "gizmo" else (0.0, 0.0, 0.0)
        centre = self._middle_of_picked() if self._about_centre else (0.0, 0.0, 0.0)
        self._drag = {"kind": kind, "handle": handle, "tool": self._tool, "from": spot, "targets": targets,
                      "partners": self._partners(targets), "start": _copied(self._curves), "remembered": remembered,
                      "moved": False, "anchor": anchor, "centre": centre, "origin": origin,
                      "middle": self._on_screen(origin),
                      "arms": {name: self._axis_on_screen(origin, "XYZ".index(name)) for name in "XYZ"}}

    def mouseMoveEvent(self, event) -> None:
        drag, spot = self._drag, event.position()
        if drag is None:
            hot = self._handle_at(spot)
            if hot != self._hot:
                self._hot = hot
                self.update()
            over = bool(hot) or (self._tool != "add" and self._point_at(spot) is not None)
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
            stepped = self._snap != bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
            self._apply(drag, delta, spot, stepped)
        self.update()

    def _apply(self, drag: dict, delta, spot, stepped: bool) -> None:
        """The drag so far, applied to the points as they were when it began."""
        start, handle = drag["start"], drag["handle"]
        tool = drag["tool"] if drag["kind"] == "gizmo" else "move"
        anchor = start[drag["anchor"][0]].points[drag["anchor"][1]]

        def put(target, point) -> None:
            self._curves[target[0]].points[target[1]] = tuple(point)

        def along(arm) -> float:
            """How many units the pointer went along an arm (its screen vector per unit)."""
            return (delta.x() * arm.x() + delta.y() * arm.y()) / max(1e-9, arm.x() ** 2 + arm.y() ** 2)

        if tool == "move":
            if handle in ("X", "Y", "Z"):
                axis = "XYZ".index(handle)
                move = [0.0, 0.0, 0.0]
                move[axis] = along(drag["arms"][handle])
            else:
                move = list(self._in_shape(delta.x(), delta.y()))
            if stepped:
                # the anchor point lands ON the grid (not: the move is a whole number of steps)
                move = [round((a + b) / self._step) * self._step - a if abs(b) > 1e-12 else 0.0
                        for a, b in zip(anchor, move)]
            self._move_points(drag["targets"], drag["partners"], start, move)
            return
        centre = drag["centre"]
        if tool == "scale":
            if handle in ("X", "Y", "Z"):
                arm = drag["arms"][handle]
                length = math.hypot(arm.x(), arm.y()) or 1.0
                factor = 1.0 + (delta.x() * arm.x() + delta.y() * arm.y()) / length / 60.0
            else:
                factor = 1.0 + delta.x() / 150.0
            factor = max(0.05, factor)
            if stepped:
                factor = max(0.1, round(factor / 0.1) * 0.1)
            axes = ("XYZ".index(handle),) if handle in ("X", "Y", "Z") else (0, 1, 2)
            for target in drag["targets"]:
                was = start[target[0]].points[target[1]]
                put(target, (c + (value - c) * factor if index in axes else value
                             for index, (value, c) in enumerate(zip(was, centre))))
            return
        # turn
        if handle == "ring":
            axis = {"Front": "Z", "Side": "X"}.get(self._view, "Y")
            middle = drag["middle"]
            before = math.atan2(drag["from"].y() - middle.y(), drag["from"].x() - middle.x())
            now = math.atan2(spot.y() - middle.y(), spot.x() - middle.x())
            swept = math.degrees(now - before)
            swept = (swept + 180.0) % 360.0 - 180.0
            degrees = swept * self._turn_sign(axis)
        else:
            axis = handle
            degrees = delta.x() * 0.5
        if stepped:
            degrees = round(degrees / 15.0) * 15.0
        for target in drag["targets"]:
            was = tuple(a - b for a, b in zip(start[target[0]].points[target[1]], centre))
            turned = shape_data.turned([shape_data.Curve([was])], axis, degrees)[0].points[0]
            put(target, (a + b for a, b in zip(turned, centre)))

    def _turn_sign(self, axis: str) -> float:
        """+1 when a positive turn about `axis` goes the way the angle on the SCREEN grows in this
        view, else -1 — found by turning a point a little and looking, not by reasoning about views."""
        probe = [0.0, 0.0, 0.0]
        probe[self._plane_axes()[0]] = 1.0
        turned = shape_data.turned([shape_data.Curve([tuple(probe)])], axis, 5.0)[0].points[0]
        zero = self._on_screen((0.0, 0.0, 0.0))
        a, b = self._on_screen(probe) - zero, self._on_screen(turned) - zero
        return 1.0 if a.x() * b.y() - a.y() * b.x() > 0 else -1.0

    def _move_points(self, targets: list, partners: dict, start: list, move) -> None:
        """`targets` moved by `move` from where they are in `start`; with symmetry their mirror points
        follow and a point on the middle line stays on it."""
        near = self._extent * 1e-3
        for target in targets:
            was = start[target[0]].points[target[1]]
            shift = list(move)
            if self._symmetry and abs(was[0]) <= near:
                shift[0] = 0.0
            self._curves[target[0]].points[target[1]] = tuple(a + b for a, b in zip(was, shift))
            partner = partners.get(target)
            if partner:
                other = start[partner[0]].points[partner[1]]
                self._curves[partner[0]].points[partner[1]] = (other[0] - shift[0], other[1] + shift[1], other[2] + shift[2])

    def mouseReleaseEvent(self, event) -> None:
        drag, self._drag = self._drag, None
        self._frame = None
        if drag and drag.get("moved"):
            self._keep_in_view()
            self._changed()
        if drag and drag["kind"] == "frame":
            self.picked_changed.emit(len(self._picked))
        self.update()

    def _keep_in_view(self) -> None:
        """After an edit that took a point out of the picture, the whole shape is brought back in."""
        room = qt.QtCore.QRectF(self.rect()).adjusted(8, 8, -8, -8)
        if any(not room.contains(self._on_screen(point)) for curve in self._curves for point in curve.points):
            self.fit()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._point_at(event.position()) is None and not self._handle_at(event.position()):
            if self._view == "3/4":
                self._yaw, self._pitch = THUMB_YAW, 28.0
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
        elif not control and event.text().upper() in KEYS:
            self.tool_wanted.emit(KEYS[event.text().upper()])
        elif key in self._ARROWS:
            right, down = self._ARROWS[key]
            self.nudge(right, down, 5 if shift else 1)
        elif key in (qt.QtCore.Qt.Key.Key_PageUp, qt.QtCore.Qt.Key.Key_PageDown):
            self.nudge_axis(2, 1 if key == qt.QtCore.Qt.Key.Key_PageUp else -1, 5 if shift else 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()          # these are the editor's: Maya's own hotkeys must not answer them too

    _ARROWS = {qt.QtCore.Qt.Key.Key_Left: (-1, 0), qt.QtCore.Qt.Key.Key_Right: (1, 0),
               qt.QtCore.Qt.Key.Key_Up: (0, -1), qt.QtCore.Qt.Key.Key_Down: (0, 1)}

    def event(self, event) -> bool:
        # Maya takes single keys (W, E, R…) for its own hotkeys before a widget sees them — unless the
        # widget says "mine" when asked (ShortcutOverride); then the key comes to keyPressEvent
        if event.type() == qt.QtCore.QEvent.Type.ShortcutOverride:
            key = event.key()
            control = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
            mine = key in self._ARROWS or key in (qt.QtCore.Qt.Key.Key_Delete, qt.QtCore.Qt.Key.Key_Backspace,
                                                  qt.QtCore.Qt.Key.Key_A, qt.QtCore.Qt.Key.Key_F,
                                                  qt.QtCore.Qt.Key.Key_PageUp, qt.QtCore.Qt.Key.Key_PageDown) \
                or (control and key in (qt.QtCore.Qt.Key.Key_Z, qt.QtCore.Qt.Key.Key_Y)) \
                or (not control and event.text().upper() in KEYS)
            if mine:
                event.accept()
                return True
        return super().event(event)

    # ------------------------------------------------------------------ the picture

    def _paint_gizmo(self, painter) -> None:
        """The manipulator: arms in the colors of their axes, a square (move / scale) or a ring (turn)."""
        handles = self.gizmo_handles()
        if not handles:
            return
        middle = self._on_screen(self._gizmo_origin())
        colors = {"X": self._x, "Y": self._y, "Z": self._z}
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        for name in ("X", "Y", "Z"):
            if name not in handles:
                continue
            end = handles[name]
            hot = self._hot == name
            pen = qt.QtGui.QPen(colors[name], 3.0 if hot else 2.0)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            if self._tool != "turn":
                painter.drawLine(middle, end)
            painter.setBrush(colors[name])
            if self._tool == "move":            # an arrow head
                way = end - middle
                length = math.hypot(way.x(), way.y()) or 1.0
                way = qt.QtCore.QPointF(way.x() / length, way.y() / length)
                side = qt.QtCore.QPointF(-way.y(), way.x())
                painter.drawPolygon(qt.QtGui.QPolygonF([end + way * 6, end - way * 4 + side * 5, end - way * 4 - side * 5]))
            elif self._tool == "scale":         # a block
                painter.drawRect(qt.QtCore.QRectF(end.x() - 4.5, end.y() - 4.5, 9, 9))
            else:                               # turn in 3/4: a dot to drag sideways
                painter.drawEllipse(end, 5.5, 5.5)
            painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        for name in ("free", "all"):
            if name in handles:
                hot = self._hot == name
                painter.setPen(qt.QtGui.QPen(self._picked_color, 2.0 if hot else 1.4))
                wash = qt.QtGui.QColor(self._picked_color)
                wash.setAlpha(120 if hot else 50)
                painter.setBrush(wash)
                painter.drawRect(qt.QtCore.QRectF(middle.x() - 6, middle.y() - 6, 12, 12))
                painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        if "ring" in handles:
            painter.setPen(qt.QtGui.QPen(self._picked_color, 3.0 if self._hot == "ring" else 2.0))
            painter.drawEllipse(middle, GIZMO, GIZMO)
            painter.drawLine(middle + qt.QtCore.QPointF(-4, 0), middle + qt.QtCore.QPointF(4, 0))
            painter.drawLine(middle + qt.QtCore.QPointF(0, -4), middle + qt.QtCore.QPointF(0, 4))

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

        # the grid a snapped point lands on, when its lines are not too close to tell apart
        if not looking and self._step * self._scale() >= 7.0 and abs(self._step - 0.5) > 1e-9:
            fine = qt.QtGui.QColor(self._grid)
            fine.setAlpha(110 if self._snap else 45)
            painter.setPen(qt.QtGui.QPen(fine, 0.6))
            count = min(200, int(reach / self._step))
            for step in range(-count, count + 1):
                value = step * self._step
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

        # a handle on every point
        for c, curve in enumerate(self._curves):
            for p, point in enumerate(curve.points):
                spot = self._on_screen(point)
                picked = (c, p) in self._picked
                half = HANDLE + (1.0 if picked else 0.0)
                painter.setPen(qt.QtGui.QPen(self._picked_color if picked else self._point, 1.4))
                painter.setBrush(self._picked_color if picked else self._ground)
                painter.drawRect(qt.QtCore.QRectF(spot.x() - half, spot.y() - half, half * 2, half * 2))
        self._paint_gizmo(painter)
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
        snapped = " · on the grid" if self._snap else " · Ctrl: on the grid"
        about = "their middle" if self._about_centre else "the pivot"
        none = "Click a point, drag a frame, or A for all — then "
        hint = {
            "points": "Click a point, Shift for more, drag a frame · " +
                      ("3/4: W, then pull an arm · Alt + drag turns the view" if looking else "drag the picked points" + snapped),
            "move": (none + "pull an arm" if not self._picked else
                     "Pull an arm: along that axis" + ("" if looking else " · the middle: freely") + snapped),
            "turn": (none + "pull the ring" if not self._picked else
                     ("Drag a colored dot sideways: about that axis" if looking else "Pull the ring: about " + about)
                     + (" · by 15°" if self._snap else " · Ctrl: by 15°")),
            "scale": (none + "pull an arm" if not self._picked else
                      "Pull an arm: along that axis · the middle: evenly · about " + about),
            "add": "Click on a line: a new point there",
            "remove": "Click a point: it goes"}[self._tool]
        if looking and self._tool in ("move", "turn", "scale") and self._picked:
            hint += " · Alt + drag turns the view"
        if self._warning:
            hint = self._warning
            painter.setPen(self._picked_color)
        painter.drawText(qt.QtCore.QRectF(10, self.height() - 22, self.width() - 20, 16),
                         qt.QtCore.Qt.AlignmentFlag.AlignLeft | qt.QtCore.Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(hint, qt.QtCore.Qt.TextElideMode.ElideRight, self.width() - 20))
        painter.end()


class CoordinateField(qt.QtWidgets.QLineEdit):
    """One coordinate of the picked points as a number: empty when they differ. Enter puts it; the
    wheel and Up / Down change it by the step.

    Signals:
        entered(float)
    """

    entered = qt.QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._step = STEP
        self.setObjectName("controlsCoordinate")
        self.setFixedWidth(58)
        self.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setPlaceholderText("—")
        self.returnPressed.connect(self._enter)

    def set_step(self, step: float) -> None:
        self._step = step

    def show_value(self, value) -> None:
        if not self.hasFocus() or value is None:
            self.setText("" if value is None else f"{value:.3f}".rstrip("0").rstrip(".") or "0")

    def _enter(self) -> None:
        try:
            self.entered.emit(float(self.text().replace(",", ".")))
        except ValueError:
            pass
        self.clearFocus()

    def _bump(self, steps: int) -> None:
        try:
            value = float(self.text().replace(",", "."))
        except ValueError:
            return
        value = round((value + steps * self._step) / self._step) * self._step
        self.setText(f"{value:.3f}".rstrip("0").rstrip(".") or "0")
        self.entered.emit(value)

    def wheelEvent(self, event) -> None:
        self._bump(1 if event.angleDelta().y() > 0 else -1)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Up:
            self._bump(1)
        elif event.key() == qt.QtCore.Qt.Key.Key_Down:
            self._bump(-1)
        else:
            super().keyPressEvent(event)


class _HoverButton(qt.QtWidgets.QPushButton):
    """A push button that says when the pointer is over it (`hovered(bool)`), like the tool buttons do."""

    hovered = qt.QtCore.Signal(bool)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)


def axis_step_button(axis: str, mark: str, tooltip: str) -> "qt.QtWidgets.QPushButton":
    """A small "−X" / "+X" button in the axis' color: one step along that axis."""
    made = _HoverButton(mark + axis)
    made.setObjectName("controlsAxisStep")
    made.setProperty("axis", axis)
    made.setToolTip(tooltip)
    made.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
    made.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
    return made


class ShapeEditor(qt.QtWidgets.QWidget):
    """The canvas with its tools: a column of tool buttons beside it; under it the views, undo /
    redo, reset and save; then what to do with the shape. The owner gives it a shape (`open`) and
    listens.

    Signals:
        edited() — the shape was changed (`curves()` is the result).
        reset_requested() / save_requested() / closed()
        take_requested() — "open the selected control's shape here".
        create_requested() / apply_requested() — a new control of it / onto the selected controls.
    """

    edited = qt.QtCore.Signal()
    reset_requested = qt.QtCore.Signal()
    save_requested = qt.QtCore.Signal()
    closed = qt.QtCore.Signal()
    create_requested = qt.QtCore.Signal()
    apply_requested = qt.QtCore.Signal()
    take_requested = qt.QtCore.Signal()

    TOOL_LINES = (("points", "cvs", "Points · Q", "Pick points and drag them freely (picking works in every tool)"),
                  ("move", "move", "Move · W", "A manipulator on the picked points: an arm moves them along its "
                                               "axis, the middle freely (A picks all: the whole shape off its pivot)"),
                  ("turn", "restart", "Turn · E", "A ring on the picked points: pull it to turn them"),
                  ("scale", "grow", "Scale · R", "A manipulator on the picked points: an arm scales along its axis, "
                                                 "the middle evenly"),
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
        self._snap = button("snap_grid", "Snap to the grid", "On: a moved point lands on the grid of the Step below, "
                                                              "turns go by 15°, scales by 0.1 (off: hold Ctrl for it)")
        column.addWidget(self._smooth)
        column.addWidget(self._symmetry)
        column.addWidget(self._snap)
        self._centre = button("center", "About their middle", "Turn and Scale go about the middle of the picked "
                                                              "points (off: about the control's pivot)")
        column.addWidget(self._centre)
        column.addStretch(1)
        self._close = button("collapse", "Back to the library", "Close the editor: the shape stays as you left it "
                                                                "until you pick another one")
        column.addWidget(self._close)

        top = qt.QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        top.addLayout(column)
        top.addWidget(self.canvas, 1)

        self._views = SegmentedControl(list(VIEWS), "Top")
        self._views.setToolTip("Top / Front / Side: a point also drags freely, in the plane of the screen · 3/4: the manipulator's "
                               "three axes; Alt + drag turns the view")
        self._undo = button("undo", "Undo", "Ctrl+Z")
        self._redo = button("redo", "Redo", "Ctrl+Y")
        self._reset = qt.QtWidgets.QPushButton("Reset")
        self._reset.setToolTip("Back to the shape as the library has it")
        self._save = qt.QtWidgets.QPushButton("Save…")
        self._save.setToolTip("Keep what you made: update the library's shape itself (a fix of its points), "
                              "or save it as a new shape of yours (under Mine)")
        bar = qt.QtWidgets.QHBoxLayout()
        bar.setSpacing(4)
        bar.addWidget(self._views)
        bar.addSpacing(6)
        bar.addWidget(self._undo)
        bar.addWidget(self._redo)
        self._take = button("color_pick", "Take the selected curve", "Open the curve (the control) selected in "
                            "the scene here, as it is — change it, then put it back (\"Onto the selected "
                            "controls\"), make more of it, or save it as yours")
        bar.addStretch(1)
        bar.addWidget(self._take)
        bar.addWidget(self._reset)
        bar.addWidget(self._save)

        # small exact moves: the picked points one step at a time
        from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
        self._step = DragNumberField(0.1, 0.01, 100.0, 0.05, width=48)
        self._step.setToolTip("The step: what a nudge moves by and what Snap lands on — drag with the middle "
                              "mouse button, the wheel")
        caption = qt.QtWidgets.QLabel("Step")
        caption.setObjectName("controlsCaption")
        nudges = qt.QtWidgets.QHBoxLayout()
        nudges.setSpacing(3)
        nudges.addWidget(caption)
        nudges.addWidget(self._step)
        nudges.addSpacing(4)
        # by AXIS, so they mean the same in every view — 3/4 too, where the screen has no left and up
        for index, axis in enumerate("XYZ"):
            for sign, mark in ((-1, "−"), (1, "+")):
                made = axis_step_button(axis, mark, f"The picked points one Step along {mark}{axis} (Shift: five) · "
                                                    "the arrow keys step on the screen, Page Up / Down along Z")
                made.clicked.connect(lambda _checked=False, index=index, sign=sign: self._nudge_axis(index, sign))
                nudges.addWidget(made)
        nudges.addStretch(1)
        self._picked_label = qt.QtWidgets.QLabel("")
        self._picked_label.setObjectName("controlsCaption")
        nudges.addWidget(self._picked_label)

        # the picked points as numbers: put one exactly, or line several up
        self._coordinates = []
        numbers = qt.QtWidgets.QHBoxLayout()
        numbers.setSpacing(3)
        for index, axis in enumerate("XYZ"):
            line_up = qt.QtWidgets.QPushButton(axis)
            line_up.setObjectName("controlsAxis")
            line_up.setProperty("axis", axis)
            line_up.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            line_up.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            line_up.setToolTip(f"Line the picked points up on {axis}: all at their average there")
            line_up.clicked.connect(lambda _checked=False, index=index: self._align(index))
            field = CoordinateField()
            field.setToolTip(f"{axis} of the picked points — type a number and Enter: one point is put exactly, "
                             "several are lined up there · the wheel, Up / Down: by the Step · empty: they differ")
            field.entered.connect(lambda value, index=index: self._put(index, value))
            self._coordinates.append(field)
            numbers.addWidget(line_up)
            numbers.addWidget(field)
            numbers.addSpacing(4)
        numbers.addStretch(1)

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
        layout.addLayout(nudges)
        layout.addLayout(numbers)
        layout.addLayout(bar)
        layout.addLayout(ends)

        self.canvas.edited.connect(self._on_edited)
        self.canvas.picked_changed.connect(lambda _count: self._show_state())
        self._views.current_changed.connect(self.canvas.set_view)
        self._smooth.clicked.connect(self.canvas.toggle_smooth)
        self._symmetry.clicked.connect(self._toggle_symmetry)
        self._snap.clicked.connect(self._toggle_snap)
        self._centre.clicked.connect(self._toggle_centre)
        self._take.clicked.connect(self.take_requested)
        self._step.value_changed.connect(self._set_step)
        self.canvas.tool_wanted.connect(self.set_tool)
        self._undo.clicked.connect(self.canvas.undo)
        self._redo.clicked.connect(self.canvas.redo)
        self._reset.clicked.connect(self.reset_requested)
        self._save.clicked.connect(self.save_requested)
        self._close.clicked.connect(self.closed)
        self._create.clicked.connect(self.create_requested)
        self._apply.clicked.connect(self.apply_requested)
        self._symmetric = False
        self._snapping = False
        self._centred = False
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
            try:
                repolish(made)
            except RuntimeError:
                # before the button is in a styled window its style is Maya's own, and PySide can hand
                # back a wrapper of a style Maya already replaced (seen right after Maya's start); the
                # window's stylesheet reads the property anyway when it is applied
                pass

    def _toggle_symmetry(self) -> None:
        self._symmetric = not self._symmetric
        self.canvas.set_symmetry(self._symmetric)
        self._lit(self._symmetry, self._symmetric)

    def _toggle_snap(self) -> None:
        self._snapping = not self._snapping
        self.canvas.set_snap(self._snapping)
        self._lit(self._snap, self._snapping)

    def _toggle_centre(self) -> None:
        self._centred = not self._centred
        self.canvas.set_about_centre(self._centred)
        self._lit(self._centre, self._centred)

    def _set_step(self, step: float) -> None:
        self.canvas.set_step(step)
        for field in self._coordinates:
            field.set_step(step)

    def _put(self, axis: int, value: float) -> None:
        self.canvas.set_coordinate(axis, value)
        self.canvas.setFocus()

    def _align(self, axis: int) -> None:
        self.canvas.align(axis)
        self.canvas.setFocus()

    def set_apply_text(self, text: str) -> None:
        self._apply.setText(text)

    def _nudge_axis(self, axis: int, sign: int) -> None:
        shift = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.canvas.nudge_axis(axis, sign, 5 if shift else 1)
        self.canvas.setFocus()

    def _nudge(self, right: int, down: int) -> None:
        shift = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        self.canvas.nudge(right, down, 5 if shift else 1)
        self.canvas.setFocus()

    def _on_edited(self) -> None:
        self._show_state()
        self.edited.emit()

    def _show_state(self) -> None:
        self._undo.setEnabled(self.canvas.can_undo())
        self._redo.setEnabled(self.canvas.can_redo())
        count = self.canvas.picked()
        self._picked_label.setText(f"{count} point{'s' if count != 1 else ''} picked" if count else "no point picked")
        for field, value in zip(self._coordinates, self.canvas.coordinates()):
            field.setEnabled(bool(count))
            field.show_value(value)
