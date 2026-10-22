# tools/maya/animation/tangents_scene.py
"""The TANGENTS group in the scene (and its hotkeys): the arithmetic is tangents.py's.

What a tool acts on is the KEYS row's `Scope` (keys_scene.find_scope - keys picked in a Graph Editor on screen,
else the timeline's highlighted range, else the current frame, on the selected objects' curves); the
right-click OPTION (measured on the reference) changes it per curve: "first" / "last" / "both" = that curve's
own end keys, "all" = all its keys - the picked ones only say which curves. SIDES: "in" / "out" / "both".
Every call is ONE undo step ("MSL Tangents") and says what it did.
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import keys_scene
from msl_tools.msl.tools.maya.animation import tangents as tg

UNDO_NAME = "MSL Tangents"
TITLES = {"best_guess": "Best guess", "bounce": "Bounce", "polished": "Polished", "flow": "Flow",
          "auto": "Auto", "spline": "Spline", "clamped": "Clamped", "linear": "Linear", "flat": "Flat",
          "step": "Step", "plateau": "Plateau", "cycle": "Cycle match"}
WHERE = {"first": "first keys", "last": "last keys", "both": "end keys", "all": "every key"}


def _keys(curve: str):
    times = [float(t) for t in cmds.keyframe(curve, query=True, timeChange=True) or []]
    values = [float(v) for v in cmds.keyframe(curve, query=True, valueChange=True) or []]
    ins = [tg.slope(a) for a in cmds.keyTangent(curve, query=True, inAngle=True) or []]
    outs = [tg.slope(a) for a in cmds.keyTangent(curve, query=True, outAngle=True) or []]
    return times, values, ins, outs


def _targets(option: str) -> tuple:
    """(scope, [(curve, indices)]) for `option`."""
    scope = keys_scene.find_scope()
    found = []
    for curve in scope.all_curves():
        count = cmds.keyframe(curve, query=True, keyframeCount=True) or 0
        indices = tg.option_indices(count, scope.chosen(curve) if option == "selected" else [], option)
        if indices:
            found.append((curve, indices))
    return scope, found


def _write(curve: str, index: int, new_in, new_out) -> None:
    """One key's sides: each (type, slope) or None (left as it is). The key's tangent LOCK is kept as it was
    (the reference never breaks a tangent - the user saw ours broken): it is released for the moment of the
    edit, so one side set alone doesn't drag the other with it, and put back after (measured: a locked key
    keeps two different angles that way)."""
    span = dict(index=(index, index))
    flags = {}
    for side, new in (("in", new_in), ("out", new_out)):
        if new is None:
            continue
        kind, value = new
        flags[f"{side}TangentType"] = "fixed" if kind == tg.FIXED else kind
        if kind == tg.FIXED:
            flags[f"{side}Angle"] = tg.angle(value)
    if not flags:
        return
    locked = bool((cmds.keyTangent(curve, query=True, lock=True, **span) or [False])[0])
    if locked:
        cmds.keyTangent(curve, edit=True, lock=False, **span)
    cmds.keyTangent(curve, edit=True, **span, **flags)
    if locked:
        cmds.keyTangent(curve, edit=True, lock=True, **span)


def _say(tool: str, keys: int, curves: int, option: str, scope, say: bool) -> str:
    where = WHERE.get(option) or scope.where()
    return keys_scene._done(f"{TITLES[tool]}: {keys} key{'s' if keys != 1 else ''} on {curves} "
                            f"curve{'s' if curves != 1 else ''} ({where})", say)


def _apply(tool: str, found, sides: str = "both") -> int:
    """Writes `tool` on the keys of `found` ([(curve, indices)]); returns how many keys it changed."""
    keys = 0
    for curve, indices in found:
        times, values, ins, outs = _keys(curve)
        if tool == "best_guess":
            kinds = tg.best_guess(values)
            plan = {i: ((kinds[i], 0.0) if sides != "out" else None,
                        (kinds[i], 0.0) if sides != "in" else None) for i in indices}
        elif tool == "bounce":
            plan = tg.bounce(times, values, indices, ins, outs, sides)
        elif tool == "polished":
            plan = tg.polished(times, values, indices, ins, outs, sides)
        elif tool == "flow":
            plan = tg.flow(times, values, indices, sides)
        else:
            plan = {i: ((tool, 0.0) if sides != "out" else None,
                        (tool, 0.0) if sides != "in" else None) for i in indices}
        for index, (new_in, new_out) in plan.items():
            if new_in is None and new_out is None:
                continue
            _write(curve, index, new_in, new_out)
            keys += 1
    return keys


def tangent(tool: str, option: str = "selected", sides: str = "both", say: bool = False) -> str:
    """Best guess / bounce / polished / flow / a native type (auto, spline, clamped, linear, flat, step,
    plateau) on the keys in play."""
    if tool not in TITLES or tool == "cycle":
        raise ValueError(f"No tangent tool {tool!r}")
    if tool == "step":
        sides = "out"        # the reference: step = the out tangent only
    scope, found = _targets(option)
    if not found:
        return keys_scene._done(keys_scene.NOTHING, say)
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        keys = _apply(tool, found, sides)
    finally:
        cmds.undoInfo(closeChunk=True)
    if not keys:
        return keys_scene._done(f"{TITLES[tool]}: nothing to change on these keys", say)
    return _say(tool, keys, len(found), option, scope, say)


class _NoUndo:
    """Maya's undo queue off for a moment, put back as it WAS."""

    def __enter__(self):
        self._was = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)

    def __exit__(self, *_exc):
        cmds.undoInfo(stateWithoutFlush=self._was)


class TangentDrag:
    """The TANGENT slider pressed (a drag as the other sliders': `update(weight)`, `commit(weight)`, `cancel()`).
    MEASURED on the reference: each picked key's in and out ANGLE goes from what it is toward what the tool would
    give it - `tangents.blend_angle`, held to +-90 -, fixed; at the right end (weight 1) a native kind (auto,
    spline, clamped, linear, flat, plateau) is set as that kind; the tangent lock stays as it was. The target is
    the tool itself, written for a moment outside the undo queue and read back - so it is exactly what the tool's
    button would leave."""

    def __init__(self, tool: str):
        self.tool = tool
        self.native = tool in tg.NATIVE
        self.scope, found = _targets("selected")
        self.where = WHERE.get("selected") or self.scope.where()
        self.keys = []          # [curve, index, lock, (in type, in angle), (out type, out angle), target in, target out]
        self._done = False
        if not found:
            return
        with _NoUndo():
            before = {curve: self._read(curve, indices) for curve, indices in found}
            _apply(tool, found)
            after = {curve: self._read(curve, indices) for curve, indices in found}
            for curve, indices in found:
                for index in indices:
                    lock, now_in, now_out = before[curve][index]
                    _lock, goal_in, goal_out = after[curve][index]
                    self.keys.append([curve, index, lock, now_in, now_out, goal_in, goal_out])
            self._restore()

    def __bool__(self) -> bool:
        return bool(self.keys)

    @staticmethod
    def _read(curve: str, indices) -> dict:
        read = {}
        for index in indices:
            span = dict(index=(index, index))
            query = lambda **flag: (cmds.keyTangent(curve, query=True, **span, **flag) or [None])[0]
            read[index] = (bool(query(lock=True)), (query(inTangentType=True), float(query(inAngle=True))),
                           (query(outTangentType=True), float(query(outAngle=True))))
        return read

    @staticmethod
    def _set(curve: str, index: int, lock: bool, new_in, new_out) -> None:
        """One key's sides as (type, angle): a kind other than fixed is set as that kind (Maya works out its
        angle), the lock kept as it was."""
        span = dict(index=(index, index))
        flags = {}
        for side, (kind, value) in (("in", new_in), ("out", new_out)):
            if kind in (None, "fixed"):
                flags[f"{side}TangentType"] = "fixed"
                flags[f"{side}Angle"] = value
            else:
                flags[f"{side}TangentType"] = kind
        if lock:
            cmds.keyTangent(curve, edit=True, lock=False, **span)
        cmds.keyTangent(curve, edit=True, **span, **flags)
        if lock:
            cmds.keyTangent(curve, edit=True, lock=True, **span)

    def _restore(self) -> None:
        for curve, index, lock, now_in, now_out, _goal_in, _goal_out in self.keys:
            self._set(curve, index, lock, now_in, now_out)

    def _write(self, weight: float) -> None:
        full = abs(weight - 1.0) < 1e-9
        for curve, index, lock, now_in, now_out, goal_in, goal_out in self.keys:
            sides = []
            for now, goal in ((now_in, goal_in), (now_out, goal_out)):
                if full and self.native and goal[0] not in (None, "fixed"):
                    sides.append(goal)
                elif now == goal:
                    sides.append(now)               # a side the tool leaves alone stays as it is
                else:
                    sides.append(("fixed", tg.blend_angle(now[1], goal[1], weight)))
            self._set(curve, index, lock, *sides)

    def update(self, weight: float) -> None:
        with _NoUndo():
            self._write(weight)
        cmds.refresh(currentView=True)

    def cancel(self) -> None:
        if self.keys and not self._done:
            with _NoUndo():
                self._restore()
            self._done = True

    def commit(self, weight: float, euler: bool = True) -> str:
        if not self.keys or self._done:
            return ""
        with _NoUndo():
            self._restore()
        self._done = True
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
        try:
            self._write(weight)
        finally:
            cmds.undoInfo(closeChunk=True)
        curves = len({key[0] for key in self.keys})
        return (f"Blend to {TITLES[self.tool]} {round(weight * 100):d} %: {len(self.keys)} "
                f"key{'s' if len(self.keys) != 1 else ''} on {curves} curve{'s' if curves != 1 else ''} "
                f"({self.where})")


def cycle(to_first: bool = False, say: bool = False) -> str:
    """Cycle match: each curve in play - its last key takes the first key's tangent (`to_first`: the other way)."""
    scope = keys_scene.find_scope()
    curves = scope.all_curves()
    if not curves:
        return keys_scene._done(keys_scene.NOTHING, say)
    done = 0
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for curve in curves:
            times, _values, ins, outs = _keys(curve)
            for index, (new_in, new_out) in tg.cycle_match(len(times), ins, outs, to_first).items():
                _write(curve, index, new_in, new_out)
                done += 1
    finally:
        cmds.undoInfo(closeChunk=True)
    if not done:
        return keys_scene._done("Cycle match: a curve needs two keys at least", say)
    where = "first key takes the last's" if to_first else "last key takes the first's"
    return keys_scene._done(f"Cycle match: {done} curve{'s' if done != 1 else ''} - the {where} tangent", say)


def set_global(tool: str, say: bool = False) -> str:
    """Maya's default tangents for new keys (Preferences > Animation)."""
    if tool not in tg.NATIVE:
        raise ValueError(f"No native tangent {tool!r}")
    if tool == "step":
        cmds.keyTangent(global_=True, outTangentType="step")
    else:
        cmds.keyTangent(global_=True, inTangentType=tool, outTangentType=tool)
    return keys_scene._done(f"New keys now get {TITLES[tool].lower()} tangents (Maya's default)", say)
