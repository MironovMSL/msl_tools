# tools/maya/controls/shapes.py
"""Control shapes as data — no Qt, no Maya.

A `Shape` is one or more `Curve`s (points, degree, closed) that make ONE control: a cube is twelve
lines, a sphere three circles. Points lie in a unit box (the farthest one 1 from the origin) and
FLAT shapes lie in the XZ plane, facing +Y (like Maya's own circle) — `oriented()` turns them to
face X or Z. The origin is the control's pivot.

Built-in shapes are drawn here by code (`BUILT_IN`), in categories; shapes the user captured live
in the tool's config (`ShapeLibrary`). `polyline()` samples a curve the way Maya draws it (a
cubic B-spline through its CVs), so a preview can paint it without Maya.
"""
import math
from dataclasses import dataclass, field

CATEGORIES = ("Basic", "Arrows", "3D", "Rig", "Symbols", "Mine")
AXES = ("X", "Y", "Z")


@dataclass
class Curve:
    points: list            # [(x, y, z)] — the CVs; a closed curve does NOT repeat its first one
    degree: int = 1
    closed: bool = False

    def to_dict(self) -> dict:
        return {"points": [list(point) for point in self.points], "degree": self.degree, "closed": self.closed}

    @classmethod
    def from_dict(cls, data: dict) -> "Curve":
        return cls([tuple(float(value) for value in point) for point in data.get("points", [])],
                   int(data.get("degree", 1)), bool(data.get("closed", False)))


@dataclass
class Shape:
    name: str
    curves: list = field(default_factory=list)
    category: str = "Basic"
    user: bool = False
    changed: bool = False        # a built-in shape the user has corrected (ShapeLibrary.update)

    def to_dict(self) -> dict:
        return {"category": self.category, "curves": [curve.to_dict() for curve in self.curves]}

    @classmethod
    def from_dict(cls, name: str, data: dict, user: bool = True) -> "Shape":
        return cls(name, [Curve.from_dict(curve) for curve in data.get("curves", [])],
                   data.get("category", "Mine"), user)

    def title(self) -> str:
        return self.name.replace("_", " ").capitalize()


# ------------------------------------------------------------------ geometry helpers

def normalized(curves: list) -> list:
    """The same curves scaled so the farthest point OF THE DRAWN LINE is 1 from the origin on an
    axis (a smooth curve runs inside its CVs: a circle is as wide as a square); the pivot stays."""
    reach = max((max(abs(value) for value in point) for curve in curves for point in polyline(curve, 8)),
                default=0.0)
    if reach <= 0:
        return curves
    return [Curve([tuple(round(value / reach, 4) for value in point) for point in curve.points],
                  curve.degree, curve.closed) for curve in curves]


def oriented(curves: list, axis: str) -> list:
    """Flat shapes face +Y; turned to face +X ("X") or +Z ("Z").

    Facing X, the shape's own +X — where a pin's stick, an arrow, a pointer point in the library —
    goes UP (+Y): a half turn about the X = Y diagonal. (A quarter turn about Z sent it DOWN: every
    pin on a joint hung under it and had to be turned 180 by hand.) Facing Z is a quarter turn about
    X: the shape's +X stays +X, as the tile shows it seen from the front."""
    if axis == "X":
        turn = lambda p: (p[1], p[0], -p[2])      # +Y -> +X, +X -> +Y (up)
    elif axis == "Z":
        turn = lambda p: (p[0], -p[2], p[1])      # +Y -> +Z
    else:
        return curves
    return [Curve([turn(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]


def scaled(curves: list, size: float) -> list:
    return [Curve([tuple(value * size for value in point) for point in curve.points], curve.degree, curve.closed)
            for curve in curves]


def turned(curves: list, axis: str, degrees: float = 90.0) -> list:
    """Every point turned about the X, Y or Z axis through the origin."""
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    if axis == "X":
        turn = lambda p: (p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c)
    elif axis == "Y":
        turn = lambda p: (p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c)
    else:
        turn = lambda p: (p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2])
    return [Curve([turn(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]


def _cross(p, q) -> tuple:
    return (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])


def frame_along(normal, axis: str = "Y") -> tuple:
    """Three unit axes — (x, y, z), each a triple in the world — of a frame whose `axis` runs along
    `normal`, the other two as level as they can be: along the world's own axis the frame IS the
    world's. For a control (a locator) that stands on a surface and faces away from it."""
    length = math.sqrt(sum(value * value for value in normal)) or 1.0
    along = tuple(value / length for value in normal)
    axis = axis if axis in AXES else "Y"
    # where the frame's SECOND axis would like to point (X: its Y up; Y: its Z forward; Z: its Y up),
    # and what to take when the normal runs that very way
    hints = {"X": ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)), "Y": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
             "Z": ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0))}[axis]
    second = hints[1]
    for hint in hints:
        dot = sum(a * b for a, b in zip(hint, along))
        flat = tuple(a - dot * b for a, b in zip(hint, along))
        size = math.sqrt(sum(value * value for value in flat))
        if size > 1e-3:
            second = tuple(value / size for value in flat)
            break
    if axis == "X":
        return along, second, _cross(along, second)
    if axis == "Z":
        return _cross(second, along), second, along
    return _cross(along, second), along, second


def plane_normal(points) -> "tuple | None":
    """The unit normal of the plane a ring of points lies in best — the direction they vary in LEAST;
    they needn't be in order (an edge loop picked any way). It points up, else along +X, else +Z.
    None when the points span no plane: fewer than three, or all on one line."""
    points = [tuple(float(value) for value in point) for point in points]
    if len(points) < 3:
        return None
    middle = [sum(point[i] for point in points) / len(points) for i in range(3)]
    spread = [[sum((point[i] - middle[i]) * (point[j] - middle[j]) for point in points) for j in range(3)]
              for i in range(3)]

    def widest(matrix):
        """The direction a symmetric matrix stretches most, and by how much (power iteration — from
        several starts: one start can lie exactly across the answer, and then finds nothing)."""
        best = ((1.0, 0.0, 0.0), 0.0)
        for vector in ((0.61, 0.53, 0.59), (-0.37, 0.71, 0.60), (0.74, -0.42, 0.52)):
            stretch = 0.0
            for _turn in range(80):
                moved = tuple(sum(matrix[i][j] * vector[j] for j in range(3)) for i in range(3))
                stretch = math.sqrt(sum(value * value for value in moved))
                if stretch < 1e-14:
                    stretch = 0.0
                    break
                vector = tuple(value / stretch for value in moved)
            if stretch > best[1]:
                best = (vector, stretch)
        return best

    first, most = widest(spread)
    if most < 1e-12:
        return None
    rest = [[spread[i][j] - most * first[i] * first[j] for j in range(3)] for i in range(3)]
    second, next_most = widest(rest)
    if next_most < most * 1e-6:
        return None                     # on one line
    normal = _cross(first, second)
    length = math.sqrt(sum(value * value for value in normal))
    if length < 1e-9:
        return None
    normal = tuple(value / length for value in normal)
    for index in (1, 0, 2):
        if abs(normal[index]) > 1e-3:
            return normal if normal[index] > 0 else tuple(-value for value in normal)
    return normal


def polyline(curve: Curve, steps: int = 8) -> list:
    """Points along the curve as Maya draws it: degree 1 = its CVs (the first again at the end if
    closed); degree 2+ = a uniform B-spline — periodic when closed, clamped to its ends when open."""
    points = list(curve.points)
    degree = curve.degree
    if degree <= 1 or len(points) <= degree:
        return points + ([points[0]] if curve.closed and points else [])
    if curve.closed:
        count = len(points)
        cvs = points + points[:degree]
        knots = list(range(-degree, count + degree + 1))
        start, end = 0, count
    else:
        count = len(points)
        cvs = points
        inner = count - degree
        knots = [0] * degree + list(range(inner + 1)) + [inner] * degree
        start, end = 0, inner
    out = []
    total = max(1, (end - start) * steps)
    for index in range(total + (0 if curve.closed else 1)):
        out.append(_de_boor(cvs, knots, degree, start + (end - start) * index / total))
    if curve.closed:
        out.append(out[0])
    return out


def _de_boor(cvs, knots, degree, t):
    """A point of a B-spline at parameter t (the full knot vector: len(cvs) + degree + 1 knots)."""
    full = knots
    span = degree
    while span < len(cvs) - 1 and full[span + 1] <= t:
        span += 1
    points = [list(cvs[span - degree + j]) for j in range(degree + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            i = span - degree + j
            left, right = full[i], full[i + degree + 1 - r]
            alpha = 0.0 if right == left else (t - left) / (right - left)
            points[j] = [(1 - alpha) * a + alpha * b for a, b in zip(points[j - 1], points[j])]
    return tuple(points[degree])


# ------------------------------------------------------------------ the built-in shapes

def _ring(radius=1.0, count=8, y=0.0, plane="XZ"):
    """A circle of `count` CVs (a periodic cubic, like Maya's circle: a little inside its CVs)."""
    points = []
    for index in range(count):
        angle = 2 * math.pi * index / count
        a, b = math.cos(angle) * radius, math.sin(angle) * radius
        points.append({"XZ": (a, y, b), "XY": (a, b, y), "YZ": (y, a, b)}[plane])
    return Curve(points, 3, True)


def _poly(points, closed=True):
    return Curve([(float(x), 0.0, float(z)) for x, z in points], 1, closed)


def _arc(radius, start, end, count=12, plane="XZ", center=(0.0, 0.0)):
    points = []
    for index in range(count + 1):
        angle = math.radians(start + (end - start) * index / count)
        a, b = center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius
        points.append({"XZ": (a, 0.0, b), "XY": (a, b, 0.0)}[plane])
    return Curve(points, 1, False)


def _star(points=5, outer=1.0, inner=0.45):
    corners = []
    for index in range(points * 2):
        angle = math.pi / 2 + math.pi * index / points
        radius = outer if index % 2 == 0 else inner
        corners.append((math.cos(angle) * radius, -math.sin(angle) * radius))
    return _poly(corners)


def _gear(teeth=8, outer=1.0, inner=0.78):
    corners = []
    for index in range(teeth * 4):
        angle = 2 * math.pi * index / (teeth * 4)
        radius = outer if index % 4 in (1, 2) else inner
        corners.append((math.cos(angle) * radius, math.sin(angle) * radius))
    return _poly(corners)


def _box(half=1.0):
    h = half
    corners = [(-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h), (-h, h, -h), (h, h, -h), (h, h, h), (-h, h, h)]
    # one line through all twelve edges (some walked twice) — one curve, like most rigs' cubes
    walk = [0, 1, 2, 3, 0, 4, 5, 1, 5, 6, 2, 6, 7, 3, 7, 4]
    return [Curve([corners[index] for index in walk], 1, False)]


def _pyramid():
    base = [(-1, -0.7, -1), (1, -0.7, -1), (1, -0.7, 1), (-1, -0.7, 1)]
    top = (0, 1.0, 0)
    walk = [base[0], base[1], base[2], base[3], base[0], top, base[1], top, base[2], top, base[3]]
    return [Curve(walk, 1, False)]


def _octahedron():
    x, y, z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    nx, ny, nz = (-1, 0, 0), (0, -1, 0), (0, 0, -1)
    walk = [y, x, ny, nx, y, z, ny, nz, y, x, z, nx, nz, x]
    return [Curve(walk, 1, False)]


def _cylinder():
    top, bottom = _ring(1.0, 8, 1.0), _ring(1.0, 8, -1.0)
    lines = [Curve([(sx, 1.0, sz), (sx, -1.0, sz)], 1, False) for sx, sz in ((1, 0), (-1, 0), (0, 1), (0, -1))]
    return [top, bottom] + lines


def _cone():
    base = _ring(1.0, 8, -1.0)
    lines = [Curve([(sx, -1.0, sz), (0.0, 1.0, 0.0)], 1, False) for sx, sz in ((1, 0), (-1, 0), (0, 1), (0, -1))]
    return [base] + lines


def _arrow(length=1.0, width=0.3, head=0.6):
    """An arrow along +X in the XZ plane, from -length to +length."""
    w, h = width / 2, head
    return _poly([(-length, -w), (length - h, -w), (length - h, -w - h * 0.5), (length, 0),
                  (length - h, w + h * 0.5), (length - h, w), (-length, w)])


def _double_arrow():
    return _poly([(-1, 0), (-0.55, -0.4), (-0.55, -0.15), (0.55, -0.15), (0.55, -0.4), (1, 0),
                  (0.55, 0.4), (0.55, 0.15), (-0.55, 0.15), (-0.55, 0.4)])


def _four_arrows():
    # one arm along +X, from the inner corner below it to just before the inner corner above it
    # (that corner is where the next arm, a quarter turn on, starts)
    arm = ((0.15, -0.15), (0.6, -0.15), (0.6, -0.35), (1.0, 0.0), (0.6, 0.35), (0.6, 0.15))
    corners = []
    for quarter in range(4):
        c, s = math.cos(math.pi / 2 * quarter), math.sin(math.pi / 2 * quarter)
        corners.extend((x * c - z * s, x * s + z * c) for x, z in arm)
    return _poly(corners)


def _curved_arrow():
    arc = _arc(1.0, 30, 150, 14)
    tip = arc.points[-1]
    head_angle = math.radians(150)
    tangent = (-math.sin(head_angle), math.cos(head_angle))      # along the arc, onward
    normal = (math.cos(head_angle), math.sin(head_angle))
    back = (tip[0] - tangent[0] * 0.3, tip[2] - tangent[1] * 0.3)
    head = Curve([(back[0] + normal[0] * 0.18, 0.0, back[1] + normal[1] * 0.18), (tip[0], 0.0, tip[2]),
                  (back[0] - normal[0] * 0.18, 0.0, back[1] - normal[1] * 0.18)], 1, False)
    return [arc, head]


def _rotate_arrows():
    curves = []
    for start in (20, 200):
        arc = _arc(1.0, start, start + 140, 12)
        end = math.radians(start + 140)
        tip = arc.points[-1]
        tangent = (-math.sin(end), math.cos(end))
        normal = (math.cos(end), math.sin(end))
        back = (tip[0] - tangent[0] * 0.28, tip[2] - tangent[1] * 0.28)
        curves.append(arc)
        curves.append(Curve([(back[0] + normal[0] * 0.16, 0.0, back[1] + normal[1] * 0.16), (tip[0], 0.0, tip[2]),
                             (back[0] - normal[0] * 0.16, 0.0, back[1] - normal[1] * 0.16)], 1, False))
    return curves


def _pin():
    head = _ring(0.35, 8, 0.0, "XY")
    head = Curve([(x, y + 0.65, z) for x, y, z in head.points], 3, True)
    return [Curve([(0.0, 0.0, 0.0), (0.0, 0.3, 0.0)], 1, False), head]


def _lollipop_square():
    return [Curve([(0.0, 0.0, 0.0), (0.0, 0.4, 0.0)], 1, False),
            Curve([(-0.3, 0.4, 0.0), (0.3, 0.4, 0.0), (0.3, 1.0, 0.0), (-0.3, 1.0, 0.0)], 1, True)]


def _eye():
    meet = math.degrees(math.asin(0.55))        # where the two lids' arcs cross the middle line
    upper = _arc(1.0, meet, 180 - meet, 10, center=(0.0, -0.55))
    lower = _arc(1.0, 180 + meet, 360 - meet, 10, center=(0.0, 0.55))
    return [upper, lower, _ring(0.22, 8)]


def _cog():
    return [_gear(6, 1.0, 0.82), _ring(0.4, 8)]


def _smooth(points, closed=True):
    """A cubic curve in the XZ plane from (x, z) CVs."""
    return Curve([(float(x), 0.0, float(z)) for x, z in points], 3, closed)


def _line(a, b):
    return Curve([tuple(float(v) for v in a), tuple(float(v) for v in b)], 1, False)


def _regular(count, radius=1.0, phase=0.0):
    return _poly([(math.cos(2 * math.pi * i / count + phase) * radius, math.sin(2 * math.pi * i / count + phase) * radius)
                  for i in range(count)])


def _head(tip, direction, size=0.3, spread=0.5):
    """An open arrow head (two strokes) at `tip`, pointing along `direction` — (x, z) pairs."""
    length = math.hypot(*direction) or 1.0
    dx, dz = direction[0] / length, direction[1] / length
    nx, nz = -dz, dx
    back = (tip[0] - dx * size, tip[1] - dz * size)
    return _poly([(back[0] + nx * size * spread, back[1] + nz * size * spread), tip,
                  (back[0] - nx * size * spread, back[1] - nz * size * spread)], closed=False)


def _capsule_flat(length=1.0, radius=0.45, count=8):
    corners = []
    for index in range(count + 1):
        angle = -math.pi / 2 + math.pi * index / count
        corners.append((length - radius + math.cos(angle) * radius, math.sin(angle) * radius))
    for index in range(count + 1):
        angle = math.pi / 2 + math.pi * index / count
        corners.append((-length + radius + math.cos(angle) * radius, math.sin(angle) * radius))
    return _poly(corners)


def _circle_pointer():
    """A ring with a notch pointing +X: which way a control faces."""
    ring = [(math.cos(math.radians(angle)) * 0.8, math.sin(math.radians(angle)) * 0.8) for angle in range(15, 346, 15)]
    return _poly([(1.15, 0.0)] + ring)


def _burst(rays=12, outer=1.0, inner=0.7):
    return _poly([(math.cos(math.pi * i / rays) * (outer if i % 2 == 0 else inner),
                   math.sin(math.pi * i / rays) * (outer if i % 2 == 0 else inner)) for i in range(rays * 2)])


def _arrow_thin():
    return [_line((-1, 0, 0), (1, 0, 0)), _head((1.0, 0.0), (1, 0), 0.35)]


def _double_arrow_thin():
    return [_line((-1, 0, 0), (1, 0, 0)), _head((1.0, 0.0), (1, 0), 0.35), _head((-1.0, 0.0), (-1, 0), 0.35)]


def _four_arrows_thin():
    return [_line((-1, 0, 0), (1, 0, 0)), _line((0, 0, -1), (0, 0, 1)), _head((1.0, 0.0), (1, 0), 0.3),
            _head((-1.0, 0.0), (-1, 0), 0.3), _head((0.0, 1.0), (0, 1), 0.3), _head((0.0, -1.0), (0, -1), 0.3)]


def _arc_arrows(start, end, both=True):
    """An arc of the unit circle with an arrow head at its end (and at its start)."""
    curves = [_arc(1.0, start, end, 18)]
    for angle, sign in ((end, 1),) + (((start, -1),) if both else ()):
        a = math.radians(angle)
        curves.append(_head((math.cos(a), math.sin(a)), (-math.sin(a) * sign, math.cos(a) * sign), 0.3))
    return curves


def _chevrons(count=1):
    curves = []
    for index in range(count):
        dx = (index - (count - 1) / 2) * 0.7
        curves.append(_poly([(-0.4 + dx, -0.8), (0.4 + dx, 0.0), (-0.4 + dx, 0.8)], closed=False))
    return curves


def _half_ring(radius, plane, y=0.0, up=True, count=8):
    """Half a circle standing on the XZ plane (in the plane "XY" or "ZY"), bulging up or down."""
    points = []
    for index in range(count + 1):
        angle = math.pi * index / count
        a, b = math.cos(angle) * radius, math.sin(angle) * radius * (1 if up else -1)
        points.append((a, y + b, 0.0) if plane == "XY" else (0.0, y + b, a))
    return Curve(points, 1, False)


def _dome():
    return [_ring(1.0, 8, 0.0), _half_ring(1.0, "XY", count=12), _half_ring(1.0, "ZY", count=12)]


def _ball():
    return [_ring(1.0, 8, 0.0, "XZ"), _ring(1.0, 8, 0.0, "XY"), _ring(1.0, 8, 0.0, "YZ"),
            _ring(0.8, 8, 0.6), _ring(0.8, 8, -0.6)]


def _capsule():
    curves = [_ring(0.5, 8, 0.5), _ring(0.5, 8, -0.5)]
    for plane in ("XY", "ZY"):
        curves.append(_half_ring(0.5, plane, 0.5, True))
        curves.append(_half_ring(0.5, plane, -0.5, False))
    curves += [_line((sx, 0.5, sz), (sx, -0.5, sz)) for sx, sz in ((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))]
    return curves


def _prism():
    a, b, c = (-1, -0.6, 1), (1, -0.6, 1), (0, 0.9, 1)
    d, e, f = (-1, -0.6, -1), (1, -0.6, -1), (0, 0.9, -1)
    return [Curve([a, b, c, a, d, e, f, d, e, b, c, f], 1, False)]


def _tetrahedron():
    a, b, c = (1, -0.6, 0), (-0.5, -0.6, 0.87), (-0.5, -0.6, -0.87)
    top = (0, 1.0, 0)
    return [Curve([a, b, c, a, top, b, c, top], 1, False)]


def _crystal():
    ring = [(math.cos(math.pi / 3 * i) * 0.6, 0.0, math.sin(math.pi / 3 * i) * 0.6) for i in range(6)]
    top, bottom = (0, 1.0, 0), (0, -1.0, 0)
    curves = [Curve(ring, 1, True)]
    for index in range(0, 6, 2):
        curves.append(Curve([top, ring[index], bottom, ring[index + 1], top], 1, False))
    return curves


def _slab():
    h, t = 1.0, 0.2
    corners = [(-h, -t, -h), (h, -t, -h), (h, -t, h), (-h, -t, h), (-h, t, -h), (h, t, -h), (h, t, h), (-h, t, h)]
    walk = [0, 1, 2, 3, 0, 4, 5, 1, 5, 6, 2, 6, 7, 3, 7, 4]
    return [Curve([corners[index] for index in walk], 1, False)]


def _cube_base():
    """A cube standing ON its pivot (feet, props on the ground)."""
    return [Curve([(x, y + 1.0, z) for x, y, z in _box()[0].points], 1, False)]


def _arrow_3d():
    """A stick up the +Y axis with a cone on top."""
    curves = [_line((0, 0, 0), (0, 0.6, 0)), _ring(0.25, 8, 0.6)]
    curves += [_line((sx, 0.6, sz), (0, 1.0, 0)) for sx, sz in ((0.25, 0), (-0.25, 0), (0, 0.25), (0, -0.25))]
    return curves


def _axes():
    curves = []
    for axis in range(3):
        tip = [0.0, 0.0, 0.0]
        tip[axis] = 1.0
        side = [0.0, 0.0, 0.0]
        side[(axis + 1) % 3] = 0.12
        back = [value * 0.75 for value in tip]
        curves.append(Curve([(0.0, 0.0, 0.0), tuple(tip), tuple(b + s for b, s in zip(back, side)), tuple(tip),
                             tuple(b - s for b, s in zip(back, side))], 1, False))
    return curves


def _spiral(turns=2.5, count=40):
    return Curve([(math.cos(2 * math.pi * turns * i / count) * i / count, 0.0,
                   math.sin(2 * math.pi * turns * i / count) * i / count) for i in range(count + 1)], 3, False)


def _spring(turns=4, count=48):
    return Curve([(math.cos(2 * math.pi * turns * i / count) * 0.5, -1.0 + 2.0 * i / count,
                   math.sin(2 * math.pi * turns * i / count) * 0.5) for i in range(count + 1)], 3, False)


def _root():
    """A ring with four arrow heads outside it: the rig's root / world control."""
    curves = [_ring(0.72)]
    for quarter in range(4):
        c, s = math.cos(math.pi / 2 * quarter), math.sin(math.pi / 2 * quarter)
        curves.append(_poly([(x * c - z * s, x * s + z * c) for x, z in ((0.8, -0.16), (1.0, 0.0), (0.8, 0.16))]))
    return curves


def _saddle(count=16):
    """A ring bent like a saddle: around the hips or the chest."""
    return Curve([(math.cos(2 * math.pi * i / count), 0.3 * math.cos(4 * math.pi * i / count),
                   math.sin(2 * math.pi * i / count)) for i in range(count)], 3, True)


def _foot():
    """A sole: the toes toward +Z, the pivot under the ankle."""
    return _smooth([(-0.28, -0.95), (0.28, -0.95), (0.36, -0.4), (0.42, 0.25), (0.5, 0.75), (0.2, 1.05),
                    (-0.25, 1.0), (-0.5, 0.6), (-0.38, 0.1), (-0.34, -0.45)])


def _hand():
    """A hand: the fingers toward +X, the wrist at the pivot."""
    outline = [(-0.3, 0), (0.3, 0), (0.45, 0.4), (0.45, 0.78), (0.32, 0.78), (0.32, 0.5), (0.27, 0.5), (0.27, 0.95),
               (0.13, 0.95), (0.13, 0.5), (0.08, 0.5), (0.08, 1.0), (-0.06, 1.0), (-0.06, 0.5), (-0.11, 0.5),
               (-0.11, 0.92), (-0.25, 0.92), (-0.25, 0.45), (-0.5, 0.62), (-0.6, 0.52), (-0.35, 0.25)]
    return _poly([(along, across) for across, along in outline])


def _bone():
    """Like a joint's bone: wide at the pivot, a point at +X."""
    w = 0.18
    ring = [(0.2, w, w), (0.2, w, -w), (0.2, -w, -w), (0.2, -w, w)]
    start, tip = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0)
    return [Curve([start, ring[0], tip, ring[2], start, ring[1], tip, ring[3], start], 1, False),
            Curve(ring, 1, True)]


def _stick(head):
    """A stick along +X from the pivot with a flat head on its end."""
    return [_line((0, 0, 0), (0.6, 0, 0)), head]


def _lips():
    upper = _smooth([(-1.0, 0.0), (-0.5, -0.3), (-0.15, -0.38), (0.0, -0.28), (0.15, -0.38), (0.5, -0.3), (1.0, 0.0)],
                    closed=False)
    lower = _smooth([(-1.0, 0.0), (-0.5, 0.38), (0.0, 0.48), (0.5, 0.38), (1.0, 0.0)], closed=False)
    return [upper, lower, _poly([(-1.0, 0.0), (1.0, 0.0)], closed=False)]


def _heart():
    points = []
    for index in range(32):
        t = 2 * math.pi * index / 32
        points.append((16 * math.sin(t) ** 3,
                       -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))))
    return _poly(points)


def _moon():
    outer = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(60, 301, 20)]
    inner = [(0.5 + math.cos(math.radians(a)) * 0.87, math.sin(math.radians(a)) * 0.87) for a in range(275, 84, -19)]
    return _poly(outer + inner)


def _sun(rays=8):
    curves = [_ring(0.5)]
    for index in range(rays):
        c, s = math.cos(2 * math.pi * index / rays), math.sin(2 * math.pi * index / rays)
        curves.append(_poly([(c * 0.68, s * 0.68), (c, s)], closed=False))
    return curves


_LETTERS = {     # stroke letters, (x, z) — z grows down the page
    "letter_l": [[(-0.5, -1), (-0.5, 1), (0.6, 1)]],
    "letter_r": [[(-0.5, 1), (-0.5, -1), (0.3, -1), (0.6, -0.75), (0.6, -0.25), (0.3, 0), (-0.5, 0)], [(0.1, 0), (0.6, 1)]],
    "letter_ik": [[(-0.9, -1), (-0.9, 1)], [(-0.3, -1), (-0.3, 1)], [(0.8, -1), (-0.3, 0.1), (0.9, 1)]],
    "letter_fk": [[(-0.2, -1), (-1.0, -1), (-1.0, 1)], [(-1.0, 0), (-0.4, 0)], [(0.1, -1), (0.1, 1)],
                  [(1.0, -1), (0.1, 0.1), (1.0, 1)]],
}


def _shapes() -> list:
    s = []
    add = lambda name, category, curves: s.append(Shape(name, normalized(curves if isinstance(curves, list)
                                                                         else [curves]), category))
    # Basic
    add("circle", "Basic", _ring())
    add("square", "Basic", _poly([(-1, -1), (1, -1), (1, 1), (-1, 1)]))
    add("rounded_square", "Basic", Curve([(-1, 0, -1), (0, 0, -1.15), (1, 0, -1), (1.15, 0, 0), (1, 0, 1),
                                           (0, 0, 1.15), (-1, 0, 1), (-1.15, 0, 0)], 3, True))
    add("rectangle", "Basic", _poly([(-1, -0.5), (1, -0.5), (1, 0.5), (-1, 0.5)]))
    add("triangle", "Basic", _poly([(0, -1), (0.87, 0.5), (-0.87, 0.5)]))
    add("diamond", "Basic", _poly([(0, -1), (1, 0), (0, 1), (-1, 0)]))
    add("hexagon", "Basic", _poly([(math.cos(math.pi / 3 * i), math.sin(math.pi / 3 * i)) for i in range(6)]))
    add("octagon", "Basic", _poly([(math.cos(math.pi / 4 * i + math.pi / 8), math.sin(math.pi / 4 * i + math.pi / 8))
                                   for i in range(8)]))
    add("half_circle", "Basic", _arc(1.0, 0, 180, 12))
    add("double_circle", "Basic", [_ring(1.0), _ring(0.8)])
    add("cross", "Basic", _poly([(-0.33, -1), (0.33, -1), (0.33, -0.33), (1, -0.33), (1, 0.33), (0.33, 0.33),
                                 (0.33, 1), (-0.33, 1), (-0.33, 0.33), (-1, 0.33), (-1, -0.33), (-0.33, -0.33)]))
    add("plus", "Basic", [Curve([(-1, 0, 0), (1, 0, 0)], 1), Curve([(0, 0, -1), (0, 0, 1)], 1)])
    add("star", "Basic", _star())
    add("gear", "Basic", _gear())
    add("pentagon", "Basic", _regular(5, phase=-math.pi / 2))
    add("oval", "Basic", Curve([(x, y, z * 0.6) for x, y, z in _ring().points], 3, True))
    add("capsule_flat", "Basic", _capsule_flat())
    add("trapezoid", "Basic", _poly([(-0.6, -0.6), (0.6, -0.6), (1, 0.6), (-1, 0.6)]))
    add("line", "Basic", _line((-1, 0, 0), (1, 0, 0)))
    add("circle_cross", "Basic", [_ring(1.0), _line((-0.83, 0, 0), (0.83, 0, 0)), _line((0, 0, -0.83), (0, 0, 0.83))])
    add("circle_pointer", "Basic", _circle_pointer())
    add("star_four", "Basic", _star(4, 1.0, 0.35))
    add("burst", "Basic", _burst())
    add("frame", "Basic", [_poly([(-1, -1), (1, -1), (1, 1), (-1, 1)]),
                           _poly([(-0.75, -0.75), (0.75, -0.75), (0.75, 0.75), (-0.75, 0.75)])])
    # Arrows
    add("arrow", "Arrows", _arrow())
    add("double_arrow", "Arrows", _double_arrow())
    add("four_arrows", "Arrows", _four_arrows())
    add("curved_arrow", "Arrows", _curved_arrow())
    add("rotate_arrows", "Arrows", _rotate_arrows())
    add("circle_arrow", "Arrows", [_ring(0.75), _arrow(1.0, 0.18, 0.35)])
    add("arrow_thin", "Arrows", _arrow_thin())
    add("double_arrow_thin", "Arrows", _double_arrow_thin())
    add("four_arrows_thin", "Arrows", _four_arrows_thin())
    add("fat_arrow", "Arrows", _poly([(-1, -0.3), (0.1, -0.3), (0.1, -0.7), (1, 0), (0.1, 0.7), (0.1, 0.3), (-1, 0.3)]))
    add("arrow_head", "Arrows", _poly([(-0.7, -0.8), (1, 0), (-0.7, 0.8), (-0.3, 0)]))
    add("chevron", "Arrows", _chevrons(1))
    add("double_chevron", "Arrows", _chevrons(2))
    add("half_turn_arrows", "Arrows", _arc_arrows(0, 180))
    add("quarter_turn_arrows", "Arrows", _arc_arrows(45, 135))
    add("full_turn_arrow", "Arrows", _arc_arrows(20, 340, both=False))
    # 3D
    add("cube", "3D", _box())
    add("sphere", "3D", [_ring(1.0, 8, 0.0, "XZ"), _ring(1.0, 8, 0.0, "XY"), _ring(1.0, 8, 0.0, "YZ")])
    add("cylinder", "3D", _cylinder())
    add("cone", "3D", _cone())
    add("pyramid", "3D", _pyramid())
    add("octahedron", "3D", _octahedron())
    add("locator", "3D", [Curve([(-1, 0, 0), (1, 0, 0)], 1), Curve([(0, -1, 0), (0, 1, 0)], 1),
                          Curve([(0, 0, -1), (0, 0, 1)], 1)])
    add("ball", "3D", _ball())
    add("dome", "3D", _dome())
    add("capsule", "3D", _capsule())
    add("prism", "3D", _prism())
    add("tetrahedron", "3D", _tetrahedron())
    add("crystal", "3D", _crystal())
    add("slab", "3D", _slab())
    add("cube_base", "3D", _cube_base())
    add("arrow_3d", "3D", _arrow_3d())
    add("axes", "3D", _axes())
    add("spring", "3D", _spring())
    # Rig
    add("root", "Rig", _root())
    add("saddle", "Rig", _saddle())
    add("foot", "Rig", _foot())
    add("hand", "Rig", _hand())
    add("bone", "Rig", _bone())
    add("pointer", "Rig", _stick(_poly([(0.6, -0.25), (1.0, 0.0), (0.6, 0.25)])))
    add("pin_flat", "Rig", _stick(Curve([(x * 0.2 + 0.8, y, z * 0.2) for x, y, z in _ring().points], 3, True)))
    add("square_stick", "Rig", _stick(_poly([(0.6, -0.2), (1.0, -0.2), (1.0, 0.2), (0.6, 0.2)])))
    add("brow", "Rig", _smooth([(-1.0, 0.25), (-0.5, -0.15), (0.0, -0.25), (0.5, -0.15), (1.0, 0.25)], closed=False))
    add("lips", "Rig", _lips())
    for letter, strokes in _LETTERS.items():
        add(letter, "Rig", [_poly(stroke, closed=False) for stroke in strokes])
    # Symbols
    add("pin", "Symbols", _pin())
    add("lollipop", "Symbols", _lollipop_square())
    add("eye", "Symbols", _eye())
    add("cog", "Symbols", _cog())
    add("target", "Symbols", [_ring(1.0), _ring(0.5), Curve([(-1.2, 0, 0), (1.2, 0, 0)], 1),
                              Curve([(0, 0, -1.2), (0, 0, 1.2)], 1)])
    add("heart", "Symbols", _heart())
    add("moon", "Symbols", _moon())
    add("drop", "Symbols", _smooth([(0.0, -1.0), (0.12, -0.6), (0.5, -0.05), (0.55, 0.45), (0.0, 0.85), (-0.55, 0.45),
                                    (-0.5, -0.05), (-0.12, -0.6)]))
    add("sun", "Symbols", _sun())
    add("crown", "Symbols", _poly([(-1, 0.6), (-1, -0.5), (-0.5, 0.0), (0, -0.7), (0.5, 0.0), (1, -0.5), (1, 0.6)]))
    add("bolt", "Symbols", _poly([(0.15, -1.0), (-0.55, 0.1), (-0.05, 0.1), (-0.2, 1.0), (0.55, -0.2), (0.05, -0.2)]))
    add("flag", "Symbols", [_line((-0.6, 0, 1.0), (-0.6, 0, -1.0)), _poly([(-0.6, -1.0), (0.8, -0.6), (-0.6, -0.2)])])
    add("bubble", "Symbols", _smooth([(-1.0, -0.2), (-0.7, -0.75), (0.0, -0.85), (0.7, -0.75), (1.0, -0.2),
                                      (0.75, 0.35), (0.0, 0.45), (-0.35, 0.45), (-0.75, 0.9), (-0.7, 0.35)]))
    add("infinity", "Symbols", Curve([(math.cos(2 * math.pi * i / 24), 0.0, math.sin(4 * math.pi * i / 24) * 0.45)
                                      for i in range(24)], 3, True))
    add("house", "Symbols", _poly([(-0.8, 1.0), (-0.8, -0.1), (-1.0, -0.1), (0.0, -1.0), (1.0, -0.1), (0.8, -0.1),
                                   (0.8, 1.0)]))
    add("spiral", "Symbols", _spiral())
    add("asterisk", "Symbols", [_line((math.cos(math.pi / 3 * i), 0, math.sin(math.pi / 3 * i)),
                                      (-math.cos(math.pi / 3 * i), 0, -math.sin(math.pi / 3 * i))) for i in range(3)])
    return s


BUILT_IN = {shape.name: shape for shape in _shapes()}


# ------------------------------------------------------------------ the library

class ShapeLibrary:
    """The built-in shapes + the user's own, which live in a config node (`{name: shape dict}`).

    An entry under a BUILT-IN shape's name is the user's correction of that shape (`update`): it is
    shown in the built-in one's place and category, is not one of the user's own (`mine`, the file),
    and `restore` takes it away again."""

    def __init__(self, store):
        self._store = store      # a ConfigNode / dict: name -> Shape.to_dict()

    def all(self) -> dict:
        shapes = dict(BUILT_IN)
        for name, data in dict(self._store).items():
            try:
                shape = Shape.from_dict(name, dict(data))
            except (TypeError, ValueError, AttributeError):
                continue    # a broken entry is skipped, never raised
            if name in BUILT_IN:
                if not shape.curves:
                    continue
                shape = Shape(name, shape.curves, BUILT_IN[name].category, False, True)
            shapes[name] = shape
        return shapes

    def update(self, name: str, curves: list) -> bool:
        """The shape `name` gets these curves (normalized) and stays what and where it is: one of the
        user's own is saved over, a built-in one is corrected for this user (see `restore`)."""
        shape = self.get(name)
        if shape is None or not curves:
            return False
        self._store[name] = Shape(name, normalized(curves), shape.category, shape.user).to_dict()
        return True

    def restore(self, name: str) -> bool:
        """A corrected built-in shape is as it was made again."""
        if name in BUILT_IN and name in dict(self._store):
            del self._store[name]
            return True
        return False

    def get(self, name: str) -> "Shape | None":
        return self.all().get(name)

    def free_name(self, wanted: str) -> str:
        names = set(self.all())
        base = "".join(char if char.isalnum() else "_" for char in wanted.strip().lower()).strip("_") or "shape"
        name, number = base, 2
        while name in names:
            name, number = f"{base}_{number}", number + 1
        return name

    def add(self, name: str, curves: list) -> str:
        """Saves curves as the user's shape (normalized); returns the name it got."""
        name = self.free_name(name)
        self._store[name] = Shape(name, normalized(curves), "Mine", True).to_dict()
        return name

    def remove(self, name: str) -> bool:
        if name in dict(self._store) and name not in BUILT_IN:
            del self._store[name]
            return True
        return False

    def mine(self) -> dict:
        return {name: shape for name, shape in self.all().items() if shape.user}

    def export_file(self, path) -> int:
        """The user's shapes into a file to hand to someone else; how many."""
        from msl_tools.msl.core.fs.safe_json import write_json_atomic
        shapes = {name: shape.to_dict() for name, shape in self.mine().items()}
        write_json_atomic(path, {"msl_control_shapes": 1, "shapes": shapes})
        return len(shapes)

    def import_file(self, path) -> list:
        """Shapes from a file made by `export_file` join the user's own — a shape that is here
        already (same name, same curves) is skipped, a name that is taken gets a number. Returns
        the names added. Raises ValueError when the file isn't a shapes file."""
        import json
        try:
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            entries = dict(data["shapes"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f"Not a shapes file: {error}")
        added = []
        mine = {name: shape.to_dict() for name, shape in self.mine().items()}
        for name, entry in entries.items():
            try:
                shape = Shape.from_dict(str(name), dict(entry))
            except (TypeError, ValueError, AttributeError):
                continue
            if not shape.curves or mine.get(name, {}).get("curves") == shape.to_dict()["curves"]:
                continue
            added.append(self.add(str(name), shape.curves))
        return added
