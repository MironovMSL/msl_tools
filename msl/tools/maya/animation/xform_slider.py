# tools/maya/animation/xform_slider.py
"""The XFORM slider's drag (the modes and what was measured: curves.XFORM_MODES): the selected controls on the
current frame blended toward a pose that is not on their curves - their mirror (now, or at another frame), the last
selected object, the copied relationship or world space. A drag as the other sliders': `update(weight)` changes the
scene live outside the undo queue, `commit(weight)` does it again as ONE undo step ("MSL Xform Slider") and keys the
animated channels on this frame, `cancel()` puts everything back."""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import align_scene as al
from msl_tools.msl.tools.maya.animation import mirror_scene as ms
from msl_tools.msl.tools.maya.animation import mirror as mr
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer as tf
from msl_tools.msl.tools.maya.animation import transfer_scene as ts
from msl_tools.msl.tools.maya.animation import xform as xf

UNDO_NAME = "MSL Xform Slider"
CHANNELS = al.CHANNELS
WORLD_MODES = ("x_align", "x_relationship", "x_world")
TITLES = {"x_mirror": "Blend to Mirror", "x_mirror_frame": "Mirror to Frame", "x_align": "Blend to Align",
          "x_relationship": "Blend to Xform Relationship", "x_world": "Blend to Xform World Space"}


def strength(mode: str, weight: float) -> float:
    """The weight a mode uses: the world blends are half as strong to the left (measured: -1 = -0.5)."""
    if mode in WORLD_MODES and weight < 0:
        return weight * 0.5
    return weight


class _NoUndo:
    def __enter__(self):
        self._was = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)

    def __exit__(self, *_exc):
        cmds.undoInfo(stateWithoutFlush=self._was)


class XformDrag:
    def __init__(self, mode: str, frame: "float | None" = None):
        self.mode = mode
        self.now = float(cmds.currentTime(query=True))
        self.items = []         # mirror: (node, {attr: (now, target)}); world: (node, start values, (q0, p0), (q1, p1))
        self.problem = ""
        self._done = False
        if mode in ("x_mirror", "x_mirror_frame"):
            self._mirror_items(frame if mode == "x_mirror_frame" else None)
        else:
            self._world_items()

    def __bool__(self) -> bool:
        return bool(self.items)

    # ------------------------------------------------------------------ what it blends toward

    def _mirror_items(self, frame) -> None:
        objects = scene.selected_objects()
        sides = ms._sides()
        for node in objects:
            other = ms.opposite(node, sides)
            if not other:
                continue
            signs = ms.signs(other, node, sides)
            animated = ts._curves(node)
            channels = {}
            for attribute in animated:
                if not ts._settable(node, attribute) or not cmds.objExists(f"{other}.{attribute}"):
                    continue
                try:
                    now = float(cmds.getAttr(f"{node}.{attribute}"))
                    there = float(cmds.getAttr(f"{other}.{attribute}", time=frame) if frame is not None
                                  else cmds.getAttr(f"{other}.{attribute}"))
                except (RuntimeError, TypeError, ValueError):
                    continue
                channels[attribute] = (now, there * mr.sign_of(signs, attribute))
            if channels:
                self.items.append((node, channels))
        if objects and not self.items:
            self.problem = "No opposite with keys: select animated controls whose other side is named (lf_ / rt_ ...)"

    def _world_items(self) -> None:
        import maya.api.OpenMaya as om
        objects = [n for n in scene.selected_objects() if cmds.objectType(n, isAType="transform")]
        targets = []
        if self.mode == "x_align":
            if len(objects) < 2:
                self.problem = "Select the objects, then the one to align them to - last"
                return
            goal = al.pivot_matrix(objects[-1])
            targets = [(node, goal) for node in objects[:-1]]
        elif self.mode == "x_world":
            data = ts._fetch(xf.WORLD)
            if not data:
                self.problem = "Nothing copied: Xform > Copy world space first"
                return
            for index, node in tf.pair([i["path"] for i in data["objects"]], objects):
                copied = xf.at(data["objects"][index]["frames"], self.now)
                if copied is not None:
                    targets.append((node, om.MMatrix(copied)))
        else:
            data = ts._fetch(xf.RELATIONSHIP)
            if not data:
                self.problem = "Nothing copied: Xform > Copy relationship first"
                return
            if len(objects) < 2:
                self.problem = "Select the children, then their parent - last"
                return
            parent = al._matrix(f"{objects[-1]}.worldMatrix[0]")
            for index, node in tf.pair([i["path"] for i in data["objects"]], objects[:-1]):
                copied = xf.at(data["objects"][index]["frames"], self.now)
                if copied is not None:
                    targets.append((node, om.MMatrix(copied) * parent))
        for node, goal in targets:
            if not ts._curves(node):
                continue                     # as the reference: only animated controls move
            start = al.pivot_matrix(node)
            values = {c: float(cmds.getAttr(f"{node}.{c}")) for c in CHANNELS}
            q0 = om.MTransformationMatrix(start).rotation(asQuaternion=True)
            q1 = om.MTransformationMatrix(al._turn(goal)).rotation(asQuaternion=True)
            p0 = om.MPoint(start[12], start[13], start[14])
            p1 = om.MPoint(goal[12], goal[13], goal[14])
            self.items.append((node, values, (q0, p0), (q1, p1)))
        if objects and not self.items and not self.problem:
            self.problem = "Nothing animated to move: the objects need keys"

    # ------------------------------------------------------------------ writing

    def _write(self, weight: float) -> list:
        """Everything set for `weight`; [(node, channel)] that were set."""
        import maya.api.OpenMaya as om
        w = strength(self.mode, weight)
        done = []
        if self.mode in ("x_mirror", "x_mirror_frame"):
            for node, channels in self.items:
                for attribute, (now, there) in channels.items():
                    cmds.setAttr(f"{node}.{attribute}", now + w * (there - now))
                    done.append((node, attribute))
            return done
        for node, _values, (q0, p0), (q1, p1) in self.items:
            turn = om.MQuaternion.slerp(q0, q1, w).asMatrix()
            point = p0 + (p1 - p0) * w
            for channel in al.put_to(node, turn, point, ("translate", "rotate")):
                done.append((node, channel))
        return done

    def _restore(self) -> None:
        for item in self.items:
            node = item[0]
            values = {a: v[0] for a, v in item[1].items()} if self.mode in ("x_mirror", "x_mirror_frame") else item[1]
            for attribute, value in values.items():
                try:
                    cmds.setAttr(f"{node}.{attribute}", value)
                except RuntimeError:
                    pass

    def update(self, weight: float) -> None:
        with _NoUndo():
            self._restore()
            self._write(weight)
        cmds.refresh(currentView=True)

    def cancel(self) -> None:
        if self.items and not self._done:
            with _NoUndo():
                self._restore()
            self._done = True

    def commit(self, weight: float, euler: bool = True) -> str:
        if not self.items or self._done:
            return self.problem
        with _NoUndo():
            self._restore()
        self._done = True
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
        try:
            done = self._write(weight)
            for node, channel in done:
                if channel in ts._curves(node):
                    cmds.setKeyframe(node, attribute=channel, time=self.now)
        finally:
            cmds.undoInfo(closeChunk=True)
        count = len(self.items)
        return (f"{TITLES[self.mode]} {round(weight * 100):d} %: {count} object{'s' if count != 1 else ''} on frame "
                f"{self.now:g}")
