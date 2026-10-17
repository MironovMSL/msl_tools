# tools/maya/animation/world.py
"""World space blending: the pose sliders working on where the objects ARE in the world, not on
their channels - the hierarchy is ignored. A control in a hierarchy (a hand under an arm that moves,
a foot under a moving root) is put where it was in the world on the neighboring keys / the frames
picked, and its own channels are worked out from that.

`WorldDrag(mode, frame, frame_right)` behaves as scene.Drag: `update(weight)` live (undo queue off),
`commit(weight)` = ONE undo step, `cancel()`. It acts on the selected transforms on the current
frame: at the press it reads each object's world matrix on its key before and after the current
frame (keys of its translate / rotate channels) or on the frames picked, and every move:
    Tweener          between the two by the weight (0 = half way)
    Blend to Neighbors / Frame   from where it is now toward one of them
— translation and scale in a straight line, rotation along the shortest arc (a quaternion slerp),
then `xform -worldSpace -matrix` turns that into the object's translate / rotate (its pivots, joint
orient and rotate order included) and those are keyed on the current frame. Parents go before
their children, so a child's world place counts its parent's new pose.
"""
from __future__ import annotations

from maya import cmds
from maya.api import OpenMaya as om

from msl_tools.msl.tools.maya.animation import curves as cv
from msl_tools.msl.tools.maya.animation.scene import _Chunk, _NoUndo, _euler

WORLD_MODES = ("tween", "neighbors", "frame")
CHANNELS = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")
ROTATIONS = ("rotateX", "rotateY", "rotateZ")
SAME_TIME = 1e-3


def _matrix(node: str, time: float) -> om.MMatrix:
    return om.MMatrix(cmds.getAttr(node + ".worldMatrix[0]", time=time))


def _parts(matrix: om.MMatrix) -> tuple:
    tm = om.MTransformationMatrix(matrix)
    return (tm.translation(om.MSpace.kWorld), tm.rotation(asQuaternion=True), tm.scale(om.MSpace.kWorld))


def blend(a: om.MMatrix, b: om.MMatrix, part: float) -> om.MMatrix:
    """A matrix `part` of the way from a to b (0 = a, 1 = b, past them too): translation and scale
    in a straight line, rotation along the shortest arc."""
    (ta, qa, sa), (tb, qb, sb) = _parts(a), _parts(b)
    if qa.x * qb.x + qa.y * qb.y + qa.z * qb.z + qa.w * qb.w < 0:   # the shorter way round
        qb = om.MQuaternion(-qb.x, -qb.y, -qb.z, -qb.w)
    tm = om.MTransformationMatrix()
    tm.setScale([sa[i] + (sb[i] - sa[i]) * part for i in range(3)], om.MSpace.kWorld)
    tm.setRotation(om.MQuaternion.slerp(qa, qb, part))
    tm.setTranslation(ta + (tb - ta) * part, om.MSpace.kWorld)
    return tm.asMatrix()


def _channels(node: str) -> list:
    """The translate / rotate channels a pose can go into: keyable, not locked, not driven by anything
    but an animation curve."""
    out = []
    for channel in CHANNELS:
        plug = f"{node}.{channel}"
        try:
            if cmds.getAttr(plug, lock=True) or not cmds.getAttr(plug, keyable=True):
                continue
        except (RuntimeError, ValueError):
            continue
        sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
        if any(not cmds.nodeType(source).startswith("animCurve") and
               not cmds.nodeType(source).startswith("animBlendNode") for source in sources):
            continue
        out.append(channel)
    return out


def _key_times(node: str, channels: list) -> list:
    times = set()
    for channel in channels:
        times.update(cmds.keyframe(f"{node}.{channel}", query=True, timeChange=True) or [])
    return sorted(times)


class _Object:
    def __init__(self, node: str, now: float, frames: tuple):
        self.node = node
        self.channels = _channels(node)
        times = _key_times(node, self.channels)
        before = [t for t in times if t < now - SAME_TIME]
        after = [t for t in times if t > now + SAME_TIME]
        self.now = _matrix(node, now)
        self.before = _matrix(node, before[-1]) if before else None
        self.after = _matrix(node, after[0]) if after else None
        self.frame_left = _matrix(node, frames[0]) if frames[0] is not None else None
        self.frame_right = _matrix(node, frames[1]) if frames[1] is not None else None
        # what each channel holds on the current frame: (had a key there, its value)
        self.held = {}
        for channel in self.channels:
            plug = f"{node}.{channel}"
            keyed = cmds.keyframe(plug, time=(now, now), query=True, valueChange=True)
            self.held[channel] = (bool(keyed), keyed[0] if keyed else cmds.getAttr(plug))

    def target(self, mode: str, weight: float) -> "om.MMatrix | None":
        if mode == "tween":
            if self.before is None or self.after is None:
                return None
            return blend(self.before, self.after, (weight + 1.0) / 2.0)
        if mode == "neighbors":
            side = self.before if weight < 0 else self.after
        else:   # frame
            side = self.frame_left if weight < 0 else self.frame_right
        if side is None:
            return None
        return blend(self.now, side, abs(weight))


def _depth(node: str) -> int:
    return (cmds.ls(node, long=True) or [node])[0].count("|")


class WorldDrag:
    """A pose slider in world space (see the module): the same face as scene.Drag."""

    buffered = 0

    def __init__(self, mode: str, frame: "float | None" = None, frame_right: "float | None" = None):
        self.mode = cv.BY_KEY[mode]
        self.now = float(cmds.currentTime(query=True))
        nodes = cmds.ls(orderedSelection=True, type="transform", long=True) or []
        nodes = sorted(nodes, key=_depth)                  # parents before their children
        self.objects = [obj for obj in (_Object(node, self.now, (frame, frame_right)) for node in nodes)
                        if obj.channels]
        self.where = f"frame {self.now:g}, world space"
        self._done = False

    def __bool__(self) -> bool:
        return bool(self.objects)

    def _pose(self, weight: float) -> int:
        """Puts every object where this weight says, keyed on the current frame; returns how many moved."""
        moved = 0
        for obj in self.objects:
            target = obj.target(self.mode.key, weight)
            if target is None:
                continue
            cmds.xform(obj.node, worldSpace=True, matrix=list(target))
            for channel in obj.channels:
                value = cmds.getAttr(f"{obj.node}.{channel}")
                cmds.setKeyframe(obj.node, attribute=channel, time=self.now, value=value)
            moved += 1
        return moved

    def update(self, weight: float) -> None:
        with _NoUndo():
            self._pose(weight)
        cmds.refresh(currentView=True)

    def _restore(self) -> None:
        with _NoUndo():
            for obj in self.objects:
                for channel, (keyed, value) in obj.held.items():
                    plug = f"{obj.node}.{channel}"
                    if keyed:
                        cmds.setKeyframe(obj.node, attribute=channel, time=self.now, value=value)
                    else:
                        cmds.cutKey(plug, time=(self.now, self.now), clear=True)
                        cmds.setAttr(plug, value)

    def cancel(self) -> None:
        if self.objects and not self._done:
            self._restore()
            self._done = True

    def commit(self, weight: float, euler: bool = True) -> str:
        if not self.objects or self._done:
            return ""
        self._restore()
        self._done = True
        with _Chunk():
            moved = self._pose(weight)
            if euler:
                curves = [curve for obj in self.objects for channel in ROTATIONS if channel in obj.channels
                          for curve in (cmds.keyframe(f"{obj.node}.{channel}", query=True, name=True) or [])]
                if curves:
                    _euler(curves, self.now, self.now)
        return (f"{self.mode.title} (world) {cv.weight_text(self.mode, weight)} · {moved} "
                f"object{'s' if moved != 1 else ''} ({self.where})")

