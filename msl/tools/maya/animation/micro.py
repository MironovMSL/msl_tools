# tools/maya/animation/micro.py
"""MICRO MANIPULATOR: Maya's own Move / Rotate / Scale tools, but the selected objects take only a PART of each
step the handle makes - the slower the mouse, the smaller the part. The hand drags as always, the object moves
less: a delicate nudge without zooming in.

MEASURED on the reference (2026-10-23, Maya 2025, a real mouse dragging its move handle 100 px in mouse events of
2 / 5 / 10 / 25 / 50 px): the object went 1.9 / 4.6 / 8.7 / 24 / 49 % of what Maya's Move tool gives for the same
drag - each mouse event's step is scaled by its length in pixels over ~108 (`part_of_step`, FULL_SPEED_PX).

HOW: while it is on, every selected transform is watched (an attribute-changed callback). A drag of Maya's handle
writes the channels on every mouse event; each write is read as Maya's step, and the channel is set at once to where
the object was plus the PART of the step (the handle follows the object). Measured (Maya 2025): Rotate and
Scale - and Move - write "the value the channel has + this event's step" as long as the channel is set back with
setAttr (with MPlug.setDouble Maya kept its own value and the handle jumped). Writes with no mouse
button down (the Channel Box, a script, undo) and drags of other tools are not touched. Maya's own handles, modes and
keys (W / E / R, object / world, the middle-button drag) are used as they are - the Rotate tool is put in gimbal
mode while it is on (see `_gimbal`).
THE END OF A DRAG: Maya puts its own step into the undo queue ("move -r <the whole drag>", absolute values - its undo
gives the start back, its redo Maya's full drag). On DragRelease that step (and auto key's) is undone - only if it is
THIS drag's -, and the result set again as ONE undo step "MSL Micro Manipulator"; auto key keys the channels that
have keys. A rotation's step is scaled per Euler channel (exact in gimbal mode), taken the short way round.
"""
from __future__ import annotations

import ctypes
import math

try:
    from maya import cmds
except ImportError:      # the rule's arithmetic is tested without Maya
    cmds = None

FULL_SPEED_PX = 108.0
SLOW_PART = 1.0 / 20.0           # when the mouse can't be read
WATCH_AT_MOST = 200
CHANNELS = {"translate": "translate", "rotate": "rotate", "scale": "scale"}
COMPONENTS = ("X", "Y", "Z")
UNDO_NAME = "MSL Micro Manipulator"
MAYA_STEPS = ("move", "rotate", "scale", "autoKeyframe")     # what Maya's tools leave in the undo queue
MAYA_TOOLS = ("manipMove", "manipRotate", "manipScale")        # the context classes whose drags are taken
_KEEP = "_msl_micro_manipulator"  # the state lives on maya.cmds, so "Reload code" finds and stops the old one


def part_of_step(pixels: float, speed: float = FULL_SPEED_PX) -> float:
    """How much of a handle's step the objects take for a mouse step of `pixels`."""
    return max(0.0, min(1.0, pixels / max(1.0, speed)))


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


try:
    _USER32 = ctypes.WinDLL("user32")
    _USER32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    _USER32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _USER32.GetAsyncKeyState.restype = ctypes.c_short
except (AttributeError, OSError):
    _USER32 = None


def _cursor():
    if _USER32 is None:
        return None
    point = _Point()
    return (point.x, point.y) if _USER32.GetCursorPos(ctypes.byref(point)) else None


def _button_down() -> bool:
    """The left or middle mouse button is held (a handle is being dragged)."""
    if _USER32 is None:
        return True
    return any(_USER32.GetAsyncKeyState(key) & 0x8000 for key in (0x01, 0x04))


def _step(name: str, now: float, before: float) -> float:
    """A channel's step from `before` to `now` - for scale its log (a scale grows by multiplying)."""
    if name.startswith("scale"):
        return math.log(now / before) if before > 1e-12 and now > 1e-12 else 0.0
    if name.startswith("rotate"):        # radians: a step over half a turn is the same turn the short way
        return math.remainder(now - before, 2.0 * math.pi)
    return now - before


def _maya_tool() -> bool:
    """Maya's own Move / Rotate / Scale tool is the one in use."""
    try:
        return cmds.contextInfo(cmds.currentCtx(), c=True) in MAYA_TOOLS
    except RuntimeError:
        return False


def _debug(*what) -> None:
    import os
    if os.environ.get("MSL_MICRO_DEBUG") == "1":
        import builtins
        log = builtins.__dict__.setdefault("_msl_micro_log", [])
        if len(log) < 4000:
            log.append(what)


# --------------------------------------------------------------------------- the watch

class _Watch:
    """One selected transform: where each channel component stood, Maya's last write, and ours."""

    def __init__(self, node, plugs):
        self.node = node
        self.plugs = plugs           # "translateX" -> MPlug
        self.maya = {}               # Maya's last write of a component in this drag
        self.ours = {}               # what the object has
        self.start = {}              # where it was when the drag started
        self.rest()

    def rest(self):
        for name, plug in self.plugs.items():
            value = plug.asDouble()
            self.maya[name] = self.ours[name] = self.start[name] = value

    def path(self) -> str:
        import maya.api.OpenMaya as om
        return om.MFnDagNode(self.node).fullPathName()


class MicroManipulator:
    def __init__(self, speed: float = FULL_SPEED_PX):
        self.speed = speed
        self.watches = {}            # node handle hash -> _Watch
        self._node_callbacks = []
        self._callbacks = []
        self._writing = False
        self._dragging = False
        self._last_cursor = None
        self._event_cursor = None
        self._event_part = 0.0
        self._finals = []
        self._undo_before = ""
        self._rotate_mode = None         # the Rotate tool's mode before it was switched on
        self.on = False

    # -- on / off

    def start(self) -> None:
        import maya.api.OpenMaya as om
        if self.on:
            return
        self.on = True
        self._gimbal()
        self._callbacks = [om.MEventMessage.addEventCallback(name, getattr(self, handler))
                           for name, handler in (("SelectionChanged", "_rewatch"), ("DragRelease", "_released"),
                                                 ("Undo", "_rested"), ("Redo", "_rested"),
                                                 ("timeChanged", "_rested"), ("SceneOpened", "_rewatch"),
                                                 ("NewSceneOpened", "_rewatch"))]
        self._rewatch()

    def stop(self) -> None:
        import maya.api.OpenMaya as om
        self.on = False
        for callback in self._callbacks + self._node_callbacks:
            try:
                om.MMessage.removeCallback(callback)
            except RuntimeError:
                pass
        self._callbacks, self._node_callbacks = [], []
        self.watches = {}
        self._gimbal(back=True)

    def _gimbal(self, back: bool = False) -> None:
        """The Rotate tool in gimbal mode while it is on: a ring then turns
        exactly one rotate channel, so its step is scaled exactly - in object / world mode one ring changes all
        three, and Maya may write another Euler triple of the same turn (a jump). Off: the mode it had, unless
        the user changed it meanwhile."""
        try:
            if back:
                if self._rotate_mode is not None and cmds.manipRotateContext("Rotate", query=True, mode=True) == 2:
                    cmds.manipRotateContext("Rotate", edit=True, mode=self._rotate_mode)
                self._rotate_mode = None
            else:
                self._rotate_mode = cmds.manipRotateContext("Rotate", query=True, mode=True)
                cmds.manipRotateContext("Rotate", edit=True, mode=2)
        except RuntimeError:
            pass

    # -- what is watched

    def _rewatch(self, *_args) -> None:
        import maya.api.OpenMaya as om
        for callback in self._node_callbacks:
            try:
                om.MMessage.removeCallback(callback)
            except RuntimeError:
                pass
        self._node_callbacks, self.watches = [], {}
        selection = om.MGlobal.getActiveSelectionList()
        for index in range(min(selection.length(), WATCH_AT_MOST)):
            try:
                node = selection.getDependNode(index)
            except RuntimeError:
                continue
            if not node.hasFn(om.MFn.kTransform):
                continue
            fn = om.MFnDependencyNode(node)
            plugs = {f"{channel}{axis}": fn.findPlug(f"{channel}{axis}", False)
                     for channel in CHANNELS for axis in COMPONENTS}
            key = om.MObjectHandle(node).hashCode()
            self.watches[key] = _Watch(node, plugs)
            self._node_callbacks.append(om.MNodeMessage.addAttributeChangedCallback(node, self._changed, key))
        self._dragging = False

    def _rested(self, *_args) -> None:
        if not self._dragging:
            for watch in self.watches.values():
                watch.rest()

    # -- a drag

    def _part(self) -> float:
        """The part of this mouse event's step: its length in pixels over the speed (the same for every write
        of one event - one cursor position)."""
        cursor = _cursor()
        if cursor is None:
            return SLOW_PART
        if cursor == self._event_cursor:
            return self._event_part
        last, self._last_cursor = self._last_cursor, cursor
        self._event_cursor = cursor
        if last is None:                  # the drag's first event: where the press was is not known
            self._event_part = SLOW_PART
        else:
            self._event_part = part_of_step(math.hypot(cursor[0] - last[0], cursor[1] - last[1]), self.speed)
        return self._event_part

    def _changed(self, message, plug, _other, key) -> None:
        import maya.api.OpenMaya as om
        if self._writing or not message & om.MNodeMessage.kAttributeSet:
            return
        watch = self.watches.get(key)
        if watch is None:
            return
        names = self._components(plug)
        if not names:
            return
        if not _button_down():
            _debug("outside", names, [watch.plugs[n].asDouble() for n in names])
            if not self._dragging:        # set by a script, the Channel Box ...
                for name in names:
                    value = watch.plugs[name].asDouble()
                    watch.maya[name] = watch.ours[name] = watch.start[name] = value
            return
        if not self._dragging:
            if not _maya_tool():
                return                    # a Channel Box drag, another tool's: left as it is
            self._dragging = True
            self._last_cursor = None
            self._event_cursor = None
            self._undo_before = cmds.undoInfo(query=True, undoName=True) or ""
        part = self._part()
        writes = []
        _debug("maya", [(n, round(watch.plugs[n].asDouble(), 5), round(watch.ours[n], 5)) for n in names])
        for name in names:
            now = watch.plugs[name].asDouble()
            step = _step(name, now, watch.ours[name])     # Maya writes "what the channel has + this event's step"
            watch.maya[name] = now
            if name.startswith("scale"):
                watch.ours[name] *= math.exp(step * part)
            else:
                watch.ours[name] += step * part
            writes.append((name, watch.ours[name]))
        _debug("drag", round(part, 4), writes)
        self._writing = True
        try:
            # setAttr, not MPlug.setDouble: Maya's tool then reads the value back on every event, so it writes
            # "ours + the event's step" and its handle stays on the object. Written with setDouble, Maya kept its
            # own idea of the value, wrote "drag start + all of it" and re-read ours only now and then - the
            # handle ran ahead of the object and jumped back (the user saw it; measured, Maya 2025)
            undo = cmds.undoInfo(query=True, stateWithoutFlush=True)
            cmds.undoInfo(stateWithoutFlush=False)
            try:
                path = watch.path()
                for name, value in writes:
                    cmds.setAttr(f"{path}.{name}", _ui(name, value))
            finally:
                cmds.undoInfo(stateWithoutFlush=undo)
        finally:
            self._writing = False

    @staticmethod
    def _components(plug) -> list:
        name = plug.partialName(useLongNames=True)
        if name in CHANNELS:
            return [f"{name}{axis}" for axis in COMPONENTS]
        if name[:-1] in CHANNELS and name[-1] in COMPONENTS:
            return [name]
        return []

    def _released(self, *_args) -> None:
        _debug("released", self._dragging)
        if not self._dragging:
            return
        self._dragging = False
        self._last_cursor = None
        finals = [(watch, dict(watch.ours), dict(watch.start)) for watch in self.watches.values()
                  if any(abs(watch.ours[n] - watch.start[n]) > 1e-12 for n in watch.plugs)]
        if finals:
            self._finals = finals
            from maya import utils
            utils.executeDeferred(self._finish)

    def _finish(self) -> None:
        finals, self._finals = self._finals, []
        if finals:
            self._commit(finals)

    def _commit(self, finals) -> None:
        """After Maya's own end of the drag: its undo step ("move -r <the whole drag>", and auto key's) taken
        back, the object set where the drag left it as ONE undo step - auto key keys the animated channels."""
        self._writing = True
        try:
            for _ in range(2):
                name = cmds.undoInfo(query=True, undoName=True) or ""
                if (name == self._undo_before or name.split(" ")[0] not in MAYA_STEPS
                        or not cmds.undoInfo(query=True, state=True)):
                    break                 # only what THIS drag left: never an older step of the user's
                _debug("undo", name)
                cmds.undo()
            for watch, _ours, start in finals:     # wherever Maya's undo left them: back to the start
                for name, plug in watch.plugs.items():
                    if abs(plug.asDouble() - start[name]) > 1e-12:
                        plug.setDouble(start[name])
            autokey = cmds.autoKeyframe(query=True, state=True)
            cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
            try:
                for watch, ours, start in finals:
                    path = watch.path()
                    for name, value in ours.items():
                        if abs(value - start[name]) <= 1e-12:
                            continue
                        plug = f"{path}.{name}"
                        _debug("set", plug, _ui(name, value), start[name])
                        cmds.setAttr(plug, _ui(name, value))
                        if autokey and cmds.keyframe(plug, query=True, keyframeCount=True):
                            cmds.setKeyframe(path, attribute=name)
            finally:
                cmds.undoInfo(closeChunk=True)
        except RuntimeError as error:
            _debug("commit failed", str(error))
        finally:
            self._writing = False
            for watch in self.watches.values():
                watch.rest()
        _debug("committed", len(finals))


def _ui(name: str, value: float) -> float:
    """A channel's internal value (cm, radians) in the scene's units, as setAttr takes it."""
    import maya.api.OpenMaya as om
    if name.startswith("translate"):
        return om.MDistance(value).asUnits(om.MDistance.uiUnit())
    if name.startswith("rotate"):
        return om.MAngle(value).asUnits(om.MAngle.uiUnit())
    return value


# --------------------------------------------------------------------------- the switch

LISTENERS = []                    # callables told when it is switched (the window's button)


def _current() -> "MicroManipulator | None":
    return getattr(cmds, _KEEP, None)


def is_on() -> bool:
    current = _current()
    return bool(current and current.on)


def speed() -> float:
    """FULL_SPEED_PX as the Animation window's settings say ("micro_speed")."""
    try:
        from msl_tools.msl.core.resources import Resources
        settings = Resources().configsMayaMng.get_config("animation", defaults={"settings": {}}).data.get("settings")
        return max(1.0, float((settings or {}).get("micro_speed") or FULL_SPEED_PX))
    except (ImportError, TypeError, ValueError, RuntimeError):
        return FULL_SPEED_PX


def set_on(on: bool, fineness: "float | None" = None) -> None:
    current = _current()
    if current is not None:
        current.stop()
        setattr(cmds, _KEEP, None)
    if on:
        manipulator = MicroManipulator(fineness or speed())
        manipulator.start()
        setattr(cmds, _KEEP, manipulator)
    for listener in list(LISTENERS):
        try:
            listener(on)
        except RuntimeError:          # a window that is gone
            LISTENERS.remove(listener)


def set_speed(value: float) -> None:
    """A new fineness for the drags to come."""
    current = _current()
    if current is not None:
        current.speed = max(1.0, float(value))


def toggle(say: bool = False) -> str:
    """On <-> off; Maya's Move tool is picked when switching on while no move / rotate / scale tool is."""
    from msl_tools.msl.tools.maya.animation import keys_scene
    on = not is_on()
    set_on(on)
    if on and not _maya_tool():
        cmds.setToolTo("moveSuperContext")
    return keys_scene._done("Micro manipulator on: drag Maya's handles - the slower, the finer" if on
                            else "Micro manipulator off", say)
