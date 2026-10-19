# tools/maya/animation/keys_scene.py
"""Keys and timing in the scene: the commands of the Animation tool's KEYS row (and their hotkeys).

What a command acts on (`Scope`), the first that applies - the sliders' order:
    picked   keys picked in a Graph Editor that is on screen (each curve with ITS picked keys);
    range    the range highlighted on the timeline, on the selected objects' curves;
    frame    the current frame, on the selected objects' curves.
"The selected objects' curves" are scene.py's: only those the Graph Editor on screen shows, else only the
Channel Box's picked channels when some are. Only curves of time (animCurveTA / TL / TU / TT).

Every command is ONE undo step ("MSL Animation") and returns what it did in words (or why it did nothing).
The arithmetic is keys.py's; values a new key gets are read from the curve BEFORE anything changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from maya import cmds
from maya.api import OpenMaya as om

from msl_tools.msl.tools.maya.animation import keys as ky
from msl_tools.msl.tools.maya.animation import scene

NOTHING = "Nothing to act on: select animated objects (or pick keys in the Graph Editor)"
SAMPLE = 0.25          # frames between the samples that tell whether a key changes the curve
FLAT = 1e-5            # a curve that moves less than this (x its size, at least this) is not moving


TANGENTS = ("type", "shape", "step")    # how keys a bake / a share adds get their tangents (the row's options)
INFINITY = ("crop", "extend")           # what a baked infinity is left as


def options() -> dict:
    """The KEYS row's choices, kept in the Animation settings (configsMayaMng "animation"): bake_tangents,
    share_tangents ("type" = the reference's default), infinity ("crop")."""
    try:
        from msl_tools.msl.core.resources import Resources
        config = Resources().configsMayaMng.get_config("animation", defaults={"settings": {}})
        data = config.data.get("settings") or {}
    except Exception:
        data = {}

    def pick(key: str, allowed: tuple) -> str:
        return data.get(key) if data.get(key) in allowed else allowed[0]

    return {"bake_tangents": pick("bake_tangents", TANGENTS), "share_tangents": pick("share_tangents", TANGENTS),
            "infinity": pick("infinity", INFINITY)}


@dataclass
class Scope:
    """What a command acts on now."""

    kind: str = ""                                  # "picked" / "range" / "frame"
    picked: dict = field(default_factory=dict)      # picked: {curve: [indices]}
    curves: list = field(default_factory=list)      # range / frame: the selected objects' curves
    span: tuple = ()                                # range: (first frame, last frame)
    now: float = 0.0

    def all_curves(self) -> list:
        return list(self.picked) if self.kind == "picked" else list(self.curves)

    def chosen(self, curve: str) -> list:
        """The indices of `curve`'s keys in play: the picked ones, the ones in the range, the one on the frame."""
        if self.kind == "picked":
            return list(self.picked.get(curve, []))
        times = _times(curve)
        if self.kind == "range":
            low, high = self.span
            return [i for i, t in enumerate(times) if low - ky.SAME <= t <= high + ky.SAME]
        return [i for i, t in enumerate(times) if ky.same(t, self.now)]

    def where(self) -> str:
        if self.kind == "picked":
            return "Graph Editor"
        if self.kind == "range":
            return f"frames {self.span[0]:g}-{self.span[1]:g}"
        return f"frame {self.now:g}"


def find_scope() -> Scope:
    now = float(cmds.currentTime(query=True))
    if scene.graph_editor_on_screen():
        picked = {}
        for curve in cmds.keyframe(query=True, selected=True, name=True) or []:
            if cmds.nodeType(curve) in scene.TIME_CURVES:
                indices = [int(i) for i in cmds.keyframe(curve, query=True, selected=True, indexValue=True) or []]
                if indices:
                    picked[curve] = indices
        if picked:
            return Scope("picked", picked=picked, now=now)
    curves = selection_curves()
    span = scene.timeline_range()
    if span is not None:
        return Scope("range", curves=curves, span=(span[0], span[1] - 1), now=now)
    return Scope("frame", curves=curves, now=now)


def selection_curves() -> list:
    return [curve for curve, _order in scene._object_curves(scene.selected_objects())]


def scene_curves() -> list:
    return [c for c in cmds.ls(type=list(scene.TIME_CURVES)) or [] if not cmds.referenceQuery(c, isNodeReferenced=True)]


# --------------------------------------------------------------------------- reading and writing keys

def _times(curve: str) -> list:
    return [float(t) for t in cmds.keyframe(curve, query=True, timeChange=True) or []]


def _values(curve: str) -> list:
    return [float(v) for v in cmds.keyframe(curve, query=True, valueChange=True) or []]


def _eval(curve: str, time: float) -> float:
    return float(cmds.keyframe(curve, query=True, eval=True, time=(time, time))[0])


def _set_key(curve: str, time: float, value: float) -> None:
    """A key with Maya's default tangents (what the reference's new keys get: auto out of the box)."""
    cmds.setKeyframe(curve, time=time, value=value)
    in_type, out_type = scene.default_tangents()
    try:
        cmds.keyTangent(curve, time=(time, time), inTangentType=in_type, outTangentType=out_type)
    except RuntimeError:
        pass


def _segments(curve: str) -> list:
    """[(time, out tangent type)] of the curve's keys as they are now - read BEFORE keys are added, so a new
    key knows what kind of segment it lands in."""
    return list(zip(_times(curve), cmds.keyTangent(curve, query=True, outTangentType=True) or []))


def _segment_type(segments: list, time: float) -> str:
    before = [kind for t, kind in segments if t <= time + ky.SAME]
    return before[-1] if before else (segments[0][1] if segments else "")


def _new_key(curve: str, time: float, value: float, tangents: str, segments: list) -> None:
    """A key a bake or a share adds, its tangents by the option (measured on the reference for "type"):
    "type" = what the segment it lands in is - linear stays linear, a stepped one stays stepped, anything else
    gets Maya's default; "shape" = Maya's insert, its tangents as steep as the curve there; "step" = stepped."""
    if tangents == "shape":
        cmds.setKeyframe(curve, time=time, insert=True)
        return
    cmds.setKeyframe(curve, time=time, value=value)
    in_type, out_type = scene.default_tangents()
    kind = _segment_type(segments, time)
    if tangents == "step" or kind in ("step", "stepnext"):
        out_type = "step"
    elif kind == "linear":
        in_type = out_type = "linear"
    try:
        cmds.keyTangent(curve, time=(time, time), inTangentType=in_type, outTangentType=out_type)
    except RuntimeError:
        pass


def _cut(curve: str, times) -> None:
    for time in sorted(times, reverse=True):
        cmds.cutKey(curve, time=(time - ky.SAME, time + ky.SAME), clear=True)


def _retime(curve: str, new_times: list) -> None:
    """Every key of `curve` to its new time (the same order, no two on one time): the ones going later
    are moved last-first, the ones going earlier first-last, so no key ever lands on another on the way."""
    old = _times(curve)
    later = [i for i in range(len(old)) if new_times[i] > old[i] + ky.SAME]
    earlier = [i for i in range(len(old)) if new_times[i] < old[i] - ky.SAME]
    for index in sorted(later, reverse=True) + sorted(earlier):
        cmds.keyframe(curve, edit=True, index=(index, index), absolute=True, timeChange=new_times[index])


def _shift_all(curves: list, offset: float) -> None:
    for curve in curves:
        cmds.keyframe(curve, edit=True, relative=True, timeChange=offset, option="over")


def _flags(curve: str) -> list:
    """[(breakdown, special)] per key."""
    count = len(_times(curve))
    return [(bool(cmds.getAttr(f"{curve}.keyBreakdown[{i}]")), bool(cmds.getAttr(f"{curve}.keyTickDrawSpecial[{i}]")))
            for i in range(count)]


def _moving(samples) -> bool:
    if not samples:
        return False
    size = max(abs(v) for v in samples)
    return max(samples) - min(samples) > FLAT * max(1.0, size)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _done(text: str, say: bool) -> str:
    if say:
        try:
            cmds.inViewMessage(amg=f"MSL: {text}", pos="topCenter", fade=True, fadeStayTime=1100)
        except RuntimeError:
            pass
    return text


# --------------------------------------------------------------------------- nudge

def nudge(frames: float, reach: str = "", say: bool = False) -> str:
    """Keys moved by `frames` (negative = left). `reach` "" = what is in play (picked keys / the range /
    the keys on the current frame - an empty frame pulls the nearest key on the other side to it), "all" =
    every key of the selected objects, "scene" = every key in the scene."""
    if reach == "scene":
        curves = scene_curves()
        if not curves:
            return _done("No animation in the scene", say)
        with scene._Chunk():
            _shift_all(curves, frames)
        return _done(f"Every key in the scene {frames:+g} frames ({_plural(len(curves), 'curve')})", say)
    scope = find_scope()
    if reach == "all":
        curves = scope.curves if scope.kind != "picked" else selection_curves()
        if not curves:
            return _done(NOTHING, say)
        with scene._Chunk():     # the time is in Maya's undo queue too: one Ctrl+Z puts both back
            _shift_all(curves, frames)
            cmds.currentTime(scope.now + frames)
        return _done(f"All keys of the selection {frames:+g} frames ({_plural(len(curves), 'curve')})", say)
    if scope.kind == "frame" and not any(scope.chosen(c) for c in scope.curves):
        return _pull_nearest(scope, frames, say)
    plans = {}
    for curve in scope.all_curves():
        chosen = scope.chosen(curve)
        if not chosen:
            continue
        plan = ky.nudge(_times(curve), chosen, frames)
        if plan is None:
            return _done("Not moved: a key would pass another one - nudge by fewer frames", say)
        plans[curve] = plan
    if not plans:
        return _done(NOTHING, say)
    count = 0
    with scene._Chunk():
        for curve, plan in plans.items():
            times = _times(curve)
            landed = [times[i] for i, new in plan.items() if new is None]
            moves = {times[i]: new for i, new in plan.items() if new is not None}
            _cut(curve, landed)
            current = _times(curve)
            _retime(curve, [next((n for o, n in moves.items() if ky.same(o, t)), t) for t in current])
            count += len(moves)
        if scope.kind == "frame":       # the time follows the keys - inside the undo step
            cmds.currentTime(scope.now + frames)
    return _done(f"Nudged {_plural(count, 'key')} {frames:+g} ({scope.where()})", say)


def _pull_nearest(scope: Scope, frames: float, say: bool) -> str:
    """An empty current frame: the nearest key on the far side comes to it (Left takes the one after it,
    Right the one before) - on every curve that has a key at that time."""
    direction = 1 if frames < 0 else -1
    every = [t for c in scope.curves for t in _times(c)]
    target = ky.nearest_key(every, scope.now, direction)
    if target is None:
        return _done(NOTHING if not scope.curves else "No key on that side of the current frame", say)
    count = 0
    with scene._Chunk():
        for curve in scope.curves:
            times = _times(curve)
            index = next((i for i, t in enumerate(times) if ky.same(t, target)), None)
            if index is None:
                continue
            new = list(times)
            new[index] = scope.now
            _retime(curve, new)
            count += 1
    return _done(f"The key at frame {target:g} came to frame {scope.now:g} ({_plural(count, 'curve')})", say)


def time_offset(frames: float, say: bool = False) -> str:
    """The keys in play stay where they are and take the curve's value `frames` later (negative: earlier) -
    the motion slides under them (the reference's "Nudge ... Time Offsetter": Left = +N)."""
    scope = find_scope()
    changes = []
    for curve in scope.all_curves():
        times = _times(curve)
        for index in scope.chosen(curve):
            changes.append((curve, index, _eval(curve, times[index] + frames)))
    if not changes:
        return _done(NOTHING, say)
    with scene._Chunk():
        for curve, index, value in changes:
            cmds.keyframe(curve, edit=True, index=(index, index), absolute=True, valueChange=value)
    return _done(f"Motion slid {-frames:+g} frames under {_plural(len(changes), 'key')} ({scope.where()})", say)


# --------------------------------------------------------------------------- inbetweens

def inbetween(frames: float, everywhere: bool = False, say: bool = False) -> str:
    """`frames` empty frames put in (negative: taken out): after the current frame, after each picked key
    (on its curve), or after every key time inside the highlighted range (on all the selection's curves).
    `everywhere`: after the current frame, on every curve in the scene."""
    scope = find_scope()
    if everywhere:
        curves = scene_curves()
        anchors = {curve: [scope.now] for curve in curves}
    elif scope.kind == "picked":
        anchors = {curve: [_times(curve)[i] for i in scope.picked[curve]] for curve in scope.picked}
    elif scope.kind == "range":
        low, high = scope.span
        inside = [t for c in scope.curves for t in _times(c) if low - ky.SAME <= t <= high + ky.SAME]
        shared = ky.union(inside) or [low]
        anchors = {curve: shared for curve in scope.curves}
    else:
        anchors = {curve: [scope.now] for curve in scope.curves}
    if not anchors:
        return _done(NOTHING, say)
    plans = {}
    for curve, points in anchors.items():
        new = ky.inbetween(_times(curve), points, frames)
        if new is None:
            return _done("Not taken out: a key would reach the key before it", say)
        plans[curve] = new
    with scene._Chunk():
        for curve, new in plans.items():
            _retime(curve, new)
    word = "put in" if frames > 0 else "taken out"
    where = "the whole scene" if everywhere else scope.where()
    return _done(f"{_plural(int(abs(frames)), 'frame')} {word} ({where}, {_plural(len(plans), 'curve')})", say)


def set_spacing(step: float, say: bool = False) -> str:
    """The key times in play (picked keys, or the keys in the highlighted range) laid out `step` frames apart
    from the first one - the keys after them stay ("Set Inbetween")."""
    scope = find_scope()
    if scope.kind == "frame":
        return _done("Pick keys in the Graph Editor or highlight a range on the timeline", say)
    curves = [c for c in scope.all_curves() if scope.chosen(c)]
    times_in_play = [_times(c)[i] for c in curves for i in scope.chosen(c)]
    mapping = ky.spaced(times_in_play, step)
    plans = {}
    for curve in curves:
        times = _times(curve)
        mine = {t: n for t, n in mapping.items() if any(ky.same(t, times[i]) for i in scope.chosen(curve))}
        new = ky.remap(times, mine)
        if new is None:
            return _done(f"Not spaced: on {step:g}s the keys would pass the ones after them", say)
        plans[curve] = new
    if not plans:
        return _done(NOTHING, say)
    with scene._Chunk():
        for curve, new in plans.items():
            _retime(curve, new)
    return _done(f"{_plural(len(mapping), 'key time')} spaced {step:g} apart ({scope.where()})", say)


# --------------------------------------------------------------------------- key times

class _Copied:
    times: list = []     # the key times copied last (kept for the Maya session)
    colors: dict = {}    # time -> the color its key had (measured: a plain copy keeps them too)


def _add_times(curve: str, times, tangents: str = "type") -> int:
    """Keys at `times` the curve has no key on, each with the value the curve had there (read first), their
    tangents by the option."""
    present = _times(curve)
    wanted = [t for t in times if not any(ky.same(t, p) for p in present)]
    read = {t: _eval(curve, t) for t in wanted}
    segments = _segments(curve)
    for time in wanted:
        _new_key(curve, time, read[time], tangents, segments)
    return len(wanted)


def share_times(from_last: bool = False, say: bool = False) -> str:
    """Every curve of the selected objects gets a key at every key time any of them has - or, `from_last`,
    at the key times of the object selected LAST (its own keys stay as they are). The curves keep their shape:
    a new key holds the value the curve had there."""
    objects = scene.selected_objects()
    pairs = scene._object_curves(objects)
    if not pairs:
        return _done(NOTHING, say)
    if from_last:
        if len(objects) < 2:
            return _done("Select two or more objects: the last one gives its key times", say)
        last = len(objects) - 1
        times = ky.union(*[_times(c) for c, order in pairs if order == last])
        curves = [c for c, order in pairs if order != last]
    else:
        curves = [c for c, _order in pairs]
        times = ky.union(*[_times(c) for c in curves])
    with scene._Chunk():
        tangents = options()["share_tangents"]
        added = sum(_add_times(curve, times, tangents) for curve in curves)
    return _done(f"Key times shared: {_plural(added, 'key')} added on {_plural(len(curves), 'curve')}", say)


def _colored_times(curves, chosen=None) -> list:
    """[(time, color)] of the keys of these curves (only the indices `chosen(curve)` gives, if given)."""
    out = []
    for curve in curves:
        indices = chosen(curve) if chosen else None
        for index, (time, (breakdown, special)) in enumerate(zip(_times(curve), _flags(curve))):
            if indices is None or index in indices:
                out.append((time, ky.color_of(breakdown, special)))
    return out


def copy_times(color: bool = False, say: bool = False) -> str:
    """The key times in play are kept to be pasted - the picked keys', the range's, else every key time of the
    selected objects - each with its key's color. `color`: only the times of the keys of ONE color, the color
    of the key on the current frame (red when there is none) - "Copy Color Key Times"."""
    scope = find_scope()
    if scope.kind == "frame":
        pairs = _colored_times(scope.curves)
    else:
        pairs = _colored_times(scope.all_curves(), scope.chosen)
    wanted = ky.RED
    if color:
        here = [kind for time, kind in _colored_times(scope.all_curves()) if ky.same(time, scope.now)]
        wanted = here[0] if here else ky.RED
        pairs = [(time, kind) for time, kind in pairs if kind == wanted]
    if not pairs:
        return _done(f"No {wanted} key on the selection" if color else NOTHING, say)
    colors = {}
    for time, kind in pairs:
        if not any(ky.same(time, known) for known in colors):
            colors[round(time, 6)] = kind
    _Copied.times = sorted(colors)
    _Copied.colors = colors
    what = f"{wanted} key time" if color else "key time"
    return _done(f"Copied {_plural(len(_Copied.times), what)} ({_Copied.times[0]:g}-{_Copied.times[-1]:g})", say)


def _copied_color(time: float) -> str:
    return next((kind for known, kind in _Copied.colors.items() if ky.same(known, time)), ky.RED)


def _tint(curve: str, time: float, color: str) -> None:
    index = next((i for i, t in enumerate(_times(curve)) if ky.same(t, time)), None)
    if index is not None:
        _color_key(curve, index, color)


def _color_key(curve: str, index: int, color: str) -> None:
    """One key's color: Maya's breakdown flag through `keyframe -e`, the special tick through setAttr on the
    curve's keyTickDrawSpecial[i] - measured (Maya 2025): `keyframe -e -tickDrawSpecial` is NOT in the undo
    queue at all, setting or clearing; the setAttr is."""
    breakdown, special = ky.COLOR_FLAGS[color]
    cmds.keyframe(curve, edit=True, index=(index, index), breakdown=breakdown)
    cmds.setAttr(f"{curve}.keyTickDrawSpecial[{index}]", special)


def paste_tint(say: bool = False) -> str:
    """The selected objects' keys AT the copied times take the color copied with them - no key is added
    ("Paste Tint Key Times"; measured: a copied red time turned a yellow key red)."""
    if not _Copied.times:
        return _done("Copy key times first", say)
    jobs = []
    for curve in selection_curves():
        hits = [(t, _copied_color(t)) for t in _times(curve) if any(ky.same(t, c) for c in _Copied.times)]
        if hits:
            jobs.append((curve, hits))
    if not jobs:
        return _done("No key of the selection is on a copied time", say)
    with scene._Chunk():
        for curve, hits in jobs:
            for time, color in hits:
                _tint(curve, time, color)
    return _done(f"Tinted {_plural(sum(len(h) for _c, h in jobs), 'key')} as copied", say)


def paste_times(mode: str = ky.MERGE, say: bool = False) -> str:
    """The copied key times onto the selected objects' curves: merge adds them; replace also takes away the
    keys inside their span that are not on one of them; insert does replace with the first copied time on the
    current frame."""
    if not _Copied.times:
        return _done("Copy key times first", say)
    curves = selection_curves()
    if not curves:
        return _done(NOTHING, say)
    now = float(cmds.currentTime(query=True))
    plans = []
    for curve in curves:
        times = _times(curve)
        added, removed = ky.paste_times(_Copied.times, times, mode, now)
        plans.append((curve, {t: _eval(curve, t) for t in added}, [times[i] for i in removed]))
    shift = (now - _Copied.times[0]) if mode == ky.INSERT else 0.0
    count = 0
    with scene._Chunk():
        for curve, added, removed in plans:
            for time, value in added.items():     # added first: a curve whose every key goes is deleted by Maya
                _set_key(curve, time, value)
                color = _copied_color(time - shift)
                if color != ky.RED:                # measured: a new key takes its copied key's color
                    _tint(curve, time, color)
            _cut(curve, removed)
            count += len(added)
    return _done(f"Key times pasted ({mode}): {_plural(count, 'key')} on {_plural(len(plans), 'curve')}", say)


# --------------------------------------------------------------------------- bake

def bake(step: float, say: bool = False) -> str:
    """A key every `step` frames, the curve's own value (Maya's default tangents); the keys between them go.
    Over the span of the picked keys (each curve its own), the highlighted range, else the animation range
    (the timeline's outer range) - keys outside stay."""
    if step <= 0:
        return _done("Bake every 1 frame or more", say)
    scope = find_scope()
    jobs = []
    for curve in scope.all_curves():
        times = _times(curve)
        if scope.kind == "picked":
            chosen = [times[i] for i in scope.chosen(curve)]
            start, end = min(chosen), max(chosen)
        elif scope.kind == "range":
            start, end = scope.span
        else:
            start = float(cmds.playbackOptions(query=True, animationStartTime=True))
            end = float(cmds.playbackOptions(query=True, animationEndTime=True))
        grid, removed = ky.bake_plan(times, start, end, step)
        jobs.append((curve, {t: _eval(curve, t) for t in grid}, [times[i] for i in removed], _segments(curve),
                     start, end))
    if not jobs:
        return _done(NOTHING, say)
    tangents = options()["bake_tangents"]
    with scene._Chunk():
        for curve, grid, removed, segments, start, end in jobs:
            _key_on(curve, grid, tangents, segments)  # keyed first: a curve whose every key goes is deleted by Maya
            _cut(curve, removed)
            if tangents == "step":                    # a baked span on steps holds every key, the old ones too
                cmds.keyTangent(curve, time=(start - ky.SAME, end + ky.SAME), outTangentType="step")
    every = {1: "ones", 2: "twos", 3: "threes", 4: "fours"}.get(step, f"every {step:g} frames")
    return _done(f"Baked on {every} ({_plural(len(jobs), 'curve')}, {scope.where() if scope.kind != 'frame' else 'animation range'})", say)


def _key_on(curve: str, values: dict, tangents: str, segments: list) -> None:
    """Keys at the times of `values` (read before anything changed) - a key already there stays as it is."""
    present = _times(curve)
    for time, value in values.items():
        if not any(ky.same(time, t) for t in present):
            _new_key(curve, time, value, tangents, segments)


def _bake_span(scope: Scope) -> tuple:
    if scope.kind == "range":
        return scope.span
    return (float(cmds.playbackOptions(query=True, animationStartTime=True)),
            float(cmds.playbackOptions(query=True, animationEndTime=True)))


def _driven_channels(node: str) -> list:
    """The keyable channels of `node` a constraint drives (they get baked, the constraint goes)."""
    out = []
    for attribute in cmds.listAttr(node, keyable=True) or []:
        plug = f"{node}.{attribute}"
        sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
        if any(cmds.objectType(source, isAType="constraint") for source in sources):
            out.append(attribute)
    return out


def bake_from_last(say: bool = False) -> str:
    """Every selected object but the LAST gets its keys exactly on the last one's key times, inside the
    highlighted range (else the animation range): keys there on other frames go, keys outside stay; channels a
    constraint drives are baked on those times too and the constraint is deleted (measured on the reference)."""
    objects = scene.selected_objects()
    if len(objects) < 2:
        return _done("Select two or more objects: the last one gives the key times", say)
    scope = find_scope()
    start, end = _bake_span(scope) if scope.kind != "picked" else _bake_span(Scope("frame"))
    last_curves = [c for c, _o in scene._object_curves([objects[-1]])]
    times = [t for t in ky.union(*[_times(c) for c in last_curves]) if start - ky.SAME <= t <= end + ky.SAME]
    if not times:
        return _done(f"The last selected has no key in frames {start:g}-{end:g}", say)
    tangents = options()["bake_tangents"]
    curve_jobs, driven_jobs, constraints = [], [], set()
    for node in objects[:-1]:
        for curve, _order in scene._object_curves([node]):
            present = _times(curve)
            removed = [t for t in present if start - ky.SAME <= t <= end + ky.SAME
                       and not any(ky.same(t, k) for k in times)]
            curve_jobs.append((curve, {t: _eval(curve, t) for t in times}, removed, _segments(curve)))
        for attribute in _driven_channels(node):
            plug = f"{node}.{attribute}"
            driven_jobs.append((node, attribute, {t: float(cmds.getAttr(plug, time=t)) for t in times}))
            for source in cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []:
                if cmds.objectType(source, isAType="constraint"):
                    constraints.add(source)
    if not curve_jobs and not driven_jobs:
        return _done(NOTHING, say)
    with scene._Chunk():
        if constraints:
            cmds.delete(sorted(constraints))
        for node, attribute, values in driven_jobs:
            for time, value in values.items():
                cmds.setKeyframe(node, attribute=attribute, time=time, value=value)
        for curve, values, removed, segments in curve_jobs:
            if cmds.objExists(curve):
                _key_on(curve, values, tangents, segments)
                _cut(curve, removed)
    baked = len(curve_jobs) + len(driven_jobs)
    extra = f", {_plural(len(constraints), 'constraint')} baked and deleted" if constraints else ""
    return _done(f"Keys on the last selected's {_plural(len(times), 'time')}: {_plural(baked, 'curve')}{extra}", say)


def bake_infinity(say: bool = False) -> str:
    """A cycling curve's infinity made real keys inside the highlighted range (else the playback range): the
    cycle's keys repeated with their tangents, a key at each end of the range that keeps the curve's shape,
    then the infinity is set to constant. A plain cycle's jump at a seam stays a jump (two keys 0.01 apart)."""
    span = scene.timeline_range()
    if span is not None:
        start, end = span[0], span[1] - 1
    else:
        start = float(cmds.playbackOptions(query=True, minTime=True))
        end = float(cmds.playbackOptions(query=True, maxTime=True))
    scope = find_scope()
    jobs = []
    for curve in scope.all_curves():
        pre, post = cmds.getAttr(curve + ".preInfinity"), cmds.getAttr(curve + ".postInfinity")
        times, values = _times(curve), _values(curve)
        found = ky.infinity_keys(times, values, start, end, pre, post)
        if not found and pre in (ky.CONSTANT, ky.LINEAR) and post in (ky.CONSTANT, ky.LINEAR):
            continue
        sources = [scene._key_data(curve, t) for t in times]
        ends = {t: _eval(curve, t) for t in (start, end)
                if (t < times[0] - ky.SAME or t > times[-1] + ky.SAME)
                and not any(ky.same(t, f[0]) for f in found)}
        jobs.append((curve, found, sources, ends))
    if not jobs:
        return _done("No cycling curve: set a curve's infinity to cycle first", say)
    keep_cycle = options()["infinity"] == "extend"     # the cycle goes on past the range as it did
    count = 0
    with scene._Chunk():
        for curve, found, sources, ends in jobs:
            for time, value, source in found:
                data = dict(sources[source], time=time, value=value)
                scene._remake_key(curve, data)
            for time, value in ends.items():
                _set_key(curve, time, value)
                cmds.keyTangent(curve, time=(time, time), inTangentType="spline", outTangentType="spline")
            if not keep_cycle:
                cmds.setAttr(curve + ".preInfinity", ky.CONSTANT)
                cmds.setAttr(curve + ".postInfinity", ky.CONSTANT)
            count += len(found) + len(ends)
    return _done(f"Infinity baked: {_plural(count, 'key')} on {_plural(len(jobs), 'curve')}, frames {start:g}-{end:g}", say)


# --------------------------------------------------------------------------- clean-up

def smart_snap(say: bool = False) -> str:
    """Keys off whole frames go to the nearest one (half way: down), holding the value the curve had THERE -
    the pose on that frame is kept; two keys on one frame become one. The keys in play, else (nothing picked,
    no range) every key of the selected objects."""
    scope = find_scope()
    jobs = []
    for curve in scope.all_curves():
        times = _times(curve)
        candidates = None if scope.kind == "frame" else scope.chosen(curve)
        groups = ky.snap_plan(times, candidates)
        if groups:
            jobs.append((curve, groups, {frame: _eval(curve, frame) for frame in groups}))
    if not jobs:
        return _done("Every key is on a whole frame already", say)
    count = 0
    with scene._Chunk():
        for curve, groups, values in jobs:
            times = _times(curve)
            keep, drop = {}, []
            for frame, members in groups.items():
                best = min(members, key=lambda i: abs(times[i] - frame))
                keep[best] = frame
                drop += [times[i] for i in members if i != best]
            moved = {times[i]: frame for i, frame in keep.items()}
            _cut(curve, drop)
            current = _times(curve)
            _retime(curve, [next((n for o, n in moved.items() if ky.same(o, t)), t) for t in current])
            for frame, value in values.items():
                cmds.keyframe(curve, edit=True, time=(frame, frame), absolute=True, valueChange=value)
            count += sum(len(m) for m in groups.values())
    return _done(f"Snapped {_plural(count, 'key')} to whole frames ({_plural(len(jobs), 'curve')})", say)


def _samples(curve: str, low: float, high: float) -> list:
    steps = max(1, int((high - low) / SAMPLE))
    return [_eval(curve, low + (high - low) * i / steps) for i in range(steps + 1)]


def remove_redundant(say: bool = False) -> str:
    """Keys whose removal leaves the curve as it was (inside the span of the keys around them). Tried on a
    copy of the curve first, one key at a time; the curve's first and last key stay."""
    scope = find_scope()
    jobs = []
    with scene._NoUndo():
        for curve in scope.all_curves():
            times = _times(curve)
            if len(times) < 3:
                continue
            candidates = range(1, len(times) - 1) if scope.kind == "frame" else \
                [i for i in scope.chosen(curve) if 0 < i < len(times) - 1]
            values = _values(curve)
            size = max(1.0, max(values) - min(values))
            original = {round(t, 4): _eval(curve, t) for t in _grid(times[0], times[-1])}
            copy = cmds.duplicate(curve)[0]
            removed = []
            try:
                for index in candidates:
                    time = times[index]
                    present = _times(copy)
                    at = next(i for i, t in enumerate(present) if ky.same(t, time))
                    low, high = present[max(0, at - 2)], present[min(len(present) - 1, at + 2)]
                    data = scene._key_data(copy, time)
                    cmds.cutKey(copy, time=(time, time), clear=True)
                    if all(abs(_eval(copy, t) - v) <= FLAT * size for t, v in original.items() if low <= t <= high):
                        removed.append(time)
                    else:
                        scene._remake_key(copy, data)
            finally:
                cmds.delete(copy)
            if removed:
                jobs.append((curve, removed))
    if not jobs:
        return _done("No redundant key", say)
    with scene._Chunk():
        for curve, removed in jobs:
            _cut(curve, removed)
    return _done(f"Removed {_plural(sum(len(r) for _c, r in jobs), 'redundant key')} ({_plural(len(jobs), 'curve')})", say)


def _grid(low: float, high: float) -> list:
    steps = max(1, int((high - low) / SAMPLE))
    return [low + (high - low) * i / steps for i in range(steps + 1)]


def remove_static(say: bool = False) -> str:
    """Curves of the selected objects that hold one value all along are deleted - the attribute keeps it."""
    scope = find_scope()
    curves = list(scope.picked) if scope.kind == "picked" else selection_curves()
    static = [c for c in curves if len(_times(c)) and not _moving(_samples(c, _times(c)[0], _times(c)[-1]))]
    if not static:
        return _done("No static curve", say)
    with scene._Chunk():
        cmds.delete(static)
    return _done(f"Removed {_plural(len(static), 'static curve')}", say)


def crop(say: bool = False) -> str:
    """Keys outside the highlighted range (or the span of the picked keys) go; a key that keeps the curve's
    shape is put at each end of it unless the curve holds still there; a curve left with no key is deleted."""
    scope = find_scope()
    if scope.kind == "frame":
        return _done("Highlight the range to keep on the timeline (or pick keys in the Graph Editor)", say)
    if scope.kind == "picked":
        chosen = [_times(c)[i] for c in scope.picked for i in scope.picked[c]]
        start, end = min(chosen), max(chosen)
    else:
        start, end = scope.span
    jobs = []
    for curve in scope.all_curves():
        times = _times(curve)
        inside = [t for t in times if start - ky.SAME <= t <= end + ky.SAME]
        ends = []
        for edge, near in ((start, inside[0] if inside else end), (end, inside[-1] if inside else start)):
            if any(ky.same(edge, t) for t in times) or not (times[0] < edge < times[-1]):
                continue
            low, high = min(edge, near), max(edge, near)
            if _moving(_samples(curve, low, high)):
                ends.append(edge)
        if not inside and not ends:
            jobs.append((curve, None, None))
        else:
            jobs.append((curve, ends, [t for t in times if t < start - ky.SAME or t > end + ky.SAME]))
    if not jobs:
        return _done(NOTHING, say)
    gone = 0
    with scene._Chunk():
        for curve, ends, outside in jobs:
            if ends is None:
                cmds.delete(curve)
                gone += 1
                continue
            for edge in ends:
                cmds.setKeyframe(curve, time=edge, insert=True)
            _cut(curve, outside)
    text = f"Cropped to frames {start:g}-{end:g} ({_plural(len(jobs), 'curve')}"
    return _done(text + (f", {gone} left empty and deleted)" if gone else ")"), say)


def reverse(say: bool = False) -> str:
    """The animation played backwards inside the span of the picked keys, the highlighted range, else the
    playback range: a key at t goes to start + end - t with its value, its tangents turned over."""
    scope = find_scope()
    if scope.kind == "picked":
        chosen = [_times(c)[i] for c in scope.picked for i in scope.picked[c]]
        start, end = min(chosen), max(chosen)
    elif scope.kind == "range":
        start, end = scope.span
    else:
        start = float(cmds.playbackOptions(query=True, minTime=True))
        end = float(cmds.playbackOptions(query=True, maxTime=True))
    curves = [c for c in scope.all_curves() if any(start - ky.SAME <= t <= end + ky.SAME for t in _times(c))]
    if not curves:
        return _done(NOTHING, say)
    with scene._Chunk():
        for curve in curves:     # Maya's own reversal: each key's tangents turn over with it
            cmds.scaleKey(curve, time=(start, end), timeScale=-1.0, timePivot=(start + end) / 2.0, valueScale=1.0)
    return _done(f"Reversed frames {start:g}-{end:g} ({_plural(len(curves), 'curve')})", say)


def clear(say: bool = False) -> str:
    """Every curve of the selected objects deleted; each attribute keeps the value it has now."""
    curves = selection_curves()
    if not curves:
        return _done(NOTHING, say)
    with scene._Chunk():
        cmds.delete(curves)
    return _done(f"Animation cleared ({_plural(len(curves), 'curve')})", say)


# --------------------------------------------------------------------------- color keys

def tint(color: str, say: bool = False) -> str:
    """The keys in play take a color - Maya's own key flags, nothing added to the scene: yellow = its special
    tick, green = its breakdown (a breakdown key keeps its place between its neighbors when they move), red =
    neither. On an empty current frame the selection's curves get a key there first."""
    scope = find_scope()
    with scene._Chunk():
        count = 0
        for curve in scope.all_curves():
            chosen = scope.chosen(curve)
            if not chosen and scope.kind == "frame":
                _set_key(curve, scope.now, _eval(curve, scope.now))
                chosen = scope.chosen(curve)
            for index in chosen:
                _color_key(curve, index, color)
                count += 1
    if not count:
        return _done(NOTHING, say)
    return _done(f"{_plural(count, 'key')} tinted {color} ({scope.where()})", say)


def tint_scene_red(say: bool = False) -> str:
    """Every key of every curve in the scene back to red - the colors cleared ("Tint All Keys Red in the
    Scene")."""
    jobs = [(curve, [i for i, flags in enumerate(_flags(curve)) if any(flags)]) for curve in scene_curves()]
    jobs = [(curve, indices) for curve, indices in jobs if indices]
    if not jobs:
        return _done("Every key in the scene is red already", say)
    with scene._Chunk():
        for curve, indices in jobs:
            for index in indices:
                _color_key(curve, index, ky.RED)
    return _done(f"{_plural(sum(len(i) for _c, i in jobs), 'key')} back to red in the scene", say)


def remove_color(color: str, say: bool = False) -> str:
    """The keys of one color taken off the selected objects' curves (the picked curves' when keys are picked)."""
    scope = find_scope()
    jobs = []
    for curve in scope.all_curves() if scope.kind == "picked" else selection_curves():
        times = _times(curve)
        gone = [times[i] for i, (b, s) in enumerate(_flags(curve)) if ky.color_of(b, s) == color]
        if gone:
            jobs.append((curve, gone))
    if not jobs:
        return _done(f"No {color} key", say)
    with scene._Chunk():
        for curve, gone in jobs:
            _cut(curve, gone)
    return _done(f"Removed {_plural(sum(len(g) for _c, g in jobs), color + ' key')}", say)


# --------------------------------------------------------------------------- playback

class Player:
    """Playback that shows only some frames, holding each: on twos / threes / fours (playbackOptions -by), or
    from key to key (the step changes at every key: each pose held until the next one) - all the selection's
    keys, or only the keys of one color (the color of the key on the current frame, else red). With a range
    highlighted on the timeline only that range plays. Called again while playing, it stops; stopped, the step
    (and the playback range, and - when no range was played - the frame it started from) come back."""

    _time_cb = None
    _stop_cb = None
    _keys: list = []
    _by = 1.0
    _start = 0.0

    _playing = False
    _jumping = False
    _range = None        # the playback range to put back, while a highlighted range is played
    _speed = (1.0, 0.0)  # playbackSpeed, maxPlaybackSpeed to put back

    @classmethod
    def toggle(cls, mode, say: bool = False) -> str:
        if cmds.play(query=True, state=True):
            cmds.play(state=False)
            cls._finish()
            return _done("Playback stopped", say)
        cls._finish()
        cls._playing = True
        cls._by = float(cmds.playbackOptions(query=True, by=True))
        cls._start = float(cmds.currentTime(query=True))
        # measured: the reference plays every step, held to real time (in plain real-time mode Maya shows the
        # frames between the steps too: 3 4 5 6 7 on twos)
        cls._speed = (float(cmds.playbackOptions(query=True, playbackSpeed=True)),
                      float(cmds.playbackOptions(query=True, maxPlaybackSpeed=True)))
        cmds.playbackOptions(playbackSpeed=0, maxPlaybackSpeed=1)
        cls._range = None
        span = scene.timeline_range()
        if span is not None:     # measured: only the highlighted range plays, the playback range comes back after
            cls._range = (float(cmds.playbackOptions(query=True, minTime=True)),
                          float(cmds.playbackOptions(query=True, maxTime=True)))
            cmds.playbackOptions(minTime=span[0], maxTime=span[1] - 1)
            cmds.currentTime(span[0])
            cls._start = None    # measured: the time stays where it stopped
        if isinstance(mode, (int, float)):
            cmds.playbackOptions(by=float(mode))
            text = f"Playing on {({2: 'twos', 3: 'threes', 4: 'fours'}).get(int(mode), mode)}"
        else:
            keys = cls._key_times(mode)
            if not keys:
                return _done(NOTHING if mode == "keys" else "No key of that color on the selection", say)
            cls._keys = keys
            cls._time_cb = om.MDGMessage.addTimeChangeCallback(cls._on_time)
            cmds.playbackOptions(by=cls._step(cls._start))
            text = f"Playing {_plural(len(keys), 'key')}" + ("" if mode == "keys" else f" ({mode})")
        cls._stop_cb = om.MConditionMessage.addConditionCallback("playingBack", cls._on_playing)
        cmds.play(forward=True)
        return _done(text, say)

    @classmethod
    def _key_times(cls, mode: str) -> list:
        curves = selection_curves()
        if mode == "keys":
            return ky.union(*[_times(c) for c in curves])
        now = float(cmds.currentTime(query=True))
        color = ky.RED
        for curve in curves:
            for t, (b, s) in zip(_times(curve), _flags(curve)):
                if ky.same(t, now):
                    color = ky.color_of(b, s)
        return ky.union(*[[t for t, (b, s) in zip(_times(c), _flags(c)) if ky.color_of(b, s) == color]
                          for c in curves])

    @classmethod
    def _step(cls, now: float) -> float:
        low = float(cmds.playbackOptions(query=True, minTime=True))
        high = float(cmds.playbackOptions(query=True, maxTime=True))
        later = [t for t in cls._keys if t > now + ky.SAME and t <= high]
        if later:
            return max(later[0] - now, 0.01)
        first = next((t for t in cls._keys if t >= low), low)    # back round to the first key
        return max(high - now + 1 + (first - low), 1.0)

    @classmethod
    def _on_time(cls, time, *_args) -> None:
        if not cls._playing or cls._jumping:
            return
        try:
            if not cmds.play(query=True, state=True):
                return
            now = time.asUnits(om.MTime.uiUnit())
            first = next((t for t in cls._keys if t >= float(cmds.playbackOptions(query=True, minTime=True))), None)
            if first is not None and now < first - ky.SAME:
                # playback came round to the range's start, which is no key in play: straight on to the first
                # one (else the start frame showed for the whole gap)
                cls._jumping = True
                try:
                    cmds.currentTime(first, update=True)
                finally:
                    cls._jumping = False
                now = first
            cmds.playbackOptions(by=cls._step(now))
        except Exception:
            pass

    @classmethod
    def _on_playing(cls, playing, *_args) -> None:
        if not playing:
            cls._finish()

    @classmethod
    def _finish(cls) -> None:
        """Callbacks off, the step and the start frame back - now and once more when Maya is idle (its own
        stop may still move the time after the condition says playback ended). Nothing when not playing."""
        for name in ("_time_cb", "_stop_cb"):
            callback = getattr(cls, name)
            if callback is not None:
                try:
                    om.MMessage.removeCallback(callback)
                except RuntimeError:
                    pass
                setattr(cls, name, None)
        if not cls._playing:
            return
        cls._playing = False
        cls._restore()
        cmds.evalDeferred(cls._restore, lowestPriority=True)
        cmds.evalDeferred(cls._forget_range, lowestPriority=True)

    @classmethod
    def _restore(cls) -> None:
        try:
            cmds.playbackOptions(by=cls._by, playbackSpeed=cls._speed[0], maxPlaybackSpeed=cls._speed[1])
            if cls._range is not None:
                cmds.playbackOptions(minTime=cls._range[0], maxTime=cls._range[1])
            if cls._start is not None:
                cmds.currentTime(cls._start)
        except RuntimeError:
            pass

    @classmethod
    def _forget_range(cls) -> None:
        cls._range = None


def play(mode, say: bool = False) -> str:
    return Player.toggle(mode, say)
