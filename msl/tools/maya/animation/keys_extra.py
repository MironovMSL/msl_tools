# tools/maya/animation/keys_extra.py
"""The KEYS group of the Animation tool (and its hotkeys): going key to key, the smart key, copy / cut /
paste / delete keys and the Euler filter - the everyday keys of an animator, each where the hand is.

WHERE IT ACTS (`context`): keys picked in a Graph Editor on screen - wherever the pointer is -, or a Graph
Editor under the pointer (from a button of our window: the panel that had the focus last) mean its PICKED keys
("graph"); otherwise the timeline: the highlighted range, else the current frame, on the selected objects'
curves ("timeline"; scene.py's curves: only those the Graph Editor on screen shows, else the Channel Box's
picked channels when some are). DELIBERATELY NOT the reference's rule (measured 2026-11-10, Maya 2025: its
Delete Keys with keys picked in a Graph Editor on screen but without focus deleted the current frame's keys and
left the picked ones) - the user: the picked key is the one to delete.

Measured and done the same way:
    GO TO KEY     next / previous key of the selected objects' curves inside the playback range, ROUND the
                  ends (20 -> 1 and 1 -> 20); several objects = all their keys; keys picked in the Graph
                  Editor = only those, also outside the range; nothing selected = the next / previous frame.
                  Not in the undo queue.
    GO TO FRAME   one frame on / back, a fraction kept (3.5 -> 4.5), no wrap at the range's end (30 -> 31);
                  not in the undo queue.
    SMART KEY     on the current frame a key on every ANIMATED channel that has none there, INSERTED: the
                  curve keeps its shape (Maya's Insert Key - the new key and its neighbours get fixed tangents
                  as steep as the curve), a linear segment keyed linear, a stepped one stays stepped. (The
                  reference sets the key with Maya's default tangents and the curve moves near it - the user
                  wanted Insert Key's behaviour.) Keys picked / curves selected in a Graph Editor on screen = only
                  those curves get it (ours; the reference keys every animated channel). Keys already there are left;
                  an object with no animated channel gets Maya's own S (every keyable channel). ALL CHANNELS =
                  every keyable channel. A HIGHLIGHTED RANGE = a key on every whole frame of it with the curve's
                  shape kept (an insert) - the reference turns a stepped curve's keys after its step to auto
                  there; ours keeps them stepped.
    DELETE KEYS   graph: the picked keys; timeline: the keys of the range / the current frame.
    EULER FILTER  Maya's own Euler filter (the reference's gives the same numbers) on the rotation curves:
                  graph = only the stretch of the picked keys, else the range, else the whole curves.
Copy / cut / paste keys are ours (the reference's rules were read from its help, not measured): copy keeps the
keys of the context with their tangents (Transfer's rows); paste puts them back from the current frame - in the
graph context at each curve's LAST picked key, or onto the curves it shows - REPLACING the keys over the
pasted stretch; RELATIVE moves the pasted values so the first one lands where the curve was. A copy of one
channel goes onto any one curve (a channel to another).
Every command that changes keys is ONE undo step ("MSL Keys").
"""
from __future__ import annotations

from maya import cmds

from msl_tools.msl.tools.maya.animation import keys as ky
from msl_tools.msl.tools.maya.animation import keys_scene as ks
from msl_tools.msl.tools.maya.animation import scene
from msl_tools.msl.tools.maya.animation import transfer_scene as ts

UNDO_NAME = "MSL Keys"
ROTATIONS = ("animCurveTA",)


class _NoUndo:
    def __enter__(self):
        self._was = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)

    def __exit__(self, *_exc):
        cmds.undoInfo(stateWithoutFlush=self._was)


class _Chunk:
    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)


# --------------------------------------------------------------------------- where it acts

def _is_graph_editor(panel) -> bool:
    try:
        return bool(panel) and cmds.getPanel(typeOf=panel) == "scriptedPanel" and \
            cmds.scriptedPanel(panel, query=True, type=True) == "graphEditor"
    except RuntimeError:
        return False


def context() -> str:
    """"graph" when keys are picked in a Graph Editor on screen (wherever the pointer is - the user: a picked key
    is the one to delete, not the frame's), or a Graph Editor is under the pointer / - the pointer on no Maya
    panel, e.g. our window - has the focus; else "timeline"."""
    if scene.graph_editor_on_screen() and _picked():
        return "graph"
    under = cmds.getPanel(underPointer=True)
    if under:
        return "graph" if _is_graph_editor(under) else "timeline"
    return "graph" if _is_graph_editor(cmds.getPanel(withFocus=True)) else "timeline"


def _picked() -> dict:
    """{curve: [indices]} of the keys picked in the Graph Editor (time curves only)."""
    found = {}
    for curve in cmds.keyframe(query=True, selected=True, name=True) or []:
        if cmds.nodeType(curve) in scene.TIME_CURVES:
            indices = [int(i) for i in cmds.keyframe(curve, query=True, selected=True, indexValue=True) or []]
            if indices:
                found[curve] = indices
    return found


def _scope() -> ks.Scope:
    """The context's scope: graph = its picked keys, timeline = range / frame - also when the pointer is over a
    Graph Editor with nothing picked in it (then the frame's keys are what the hand means)."""
    now = float(cmds.currentTime(query=True))
    picked = _picked() if context() == "graph" else {}
    if picked:
        return ks.Scope("picked", picked=picked, now=now)
    curves = ks.selection_curves()
    span = scene.timeline_range()
    if span is not None:
        return ks.Scope("range", curves=curves, span=(span[0], span[1] - 1), now=now)
    return ks.Scope("frame", curves=curves, now=now)


# --------------------------------------------------------------------------- going key to key

def _set_time(time: float) -> None:
    with _NoUndo():
        cmds.currentTime(time, edit=True)


def go_to_key(direction: int = 1, say: bool = False) -> str:
    now = float(cmds.currentTime(query=True))
    picked = _picked()
    if picked:
        times = [ks._times(c)[i] for c, indices in picked.items() for i in indices]
        where = "picked keys"
    else:
        curves = ks.selection_curves()
        if not cmds.ls(selection=True):
            return go_to_frame(direction, say)
        low = float(cmds.playbackOptions(query=True, minTime=True))
        high = float(cmds.playbackOptions(query=True, maxTime=True))
        times = [t for c in curves for t in ks._times(c) if low - ky.SAME <= t <= high + ky.SAME]
        where = "keys"
    target = ky.step_to_key(times, now, direction)
    if target is None:
        return ks._done("No key in the playback range", say)
    _set_time(target)
    return f"Frame {target:g} ({where})"


def go_to_frame(direction: int = 1, say: bool = False) -> str:
    target = float(cmds.currentTime(query=True)) + (1.0 if direction > 0 else -1.0)
    _set_time(target)
    return f"Frame {target:g}"


def next_key(say: bool = False) -> str:
    return go_to_key(1, say)


def previous_key(say: bool = False) -> str:
    return go_to_key(-1, say)


def next_frame(say: bool = False) -> str:
    return go_to_frame(1, say)


def previous_frame(say: bool = False) -> str:
    return go_to_frame(-1, say)


# --------------------------------------------------------------------------- the smart key

def _keyable(node: str) -> list:
    return [a for a in cmds.listAttr(node, keyable=True, scalar=True) or []
            if cmds.getAttr(f"{node}.{a}", settable=True)]


def _range_key(curve: str, frames: list, segments: list) -> None:
    """Keys on every frame with the curve's shape kept - a stepped segment stays stepped, a linear one linear
    (an insert there turned the linear keys fixed; the reference keeps them linear)."""
    for frame in frames:
        if any(ky.same(frame, t) for t in ks._times(curve)):
            continue
        kind = ks._segment_type(segments, frame)
        if kind == "linear":
            ks._new_key(curve, frame, ks._eval(curve, frame), "type", segments)
            continue
        stepped = kind in ("step", "stepnext")
        cmds.setKeyframe(curve, time=frame, insert=True)
        if stepped:
            cmds.keyTangent(curve, time=(frame, frame), outTangentType="step")


def set_smart_key(all_channels: bool = False, say: bool = False) -> str:
    """Keys picked (or whole curves selected) in a Graph Editor on screen = only THOSE curves get the key (the
    user's ask: the curves the hand is on); else every animated channel of the selected objects."""
    picked = _picked() if not all_channels and scene.graph_editor_on_screen() else {}
    objects = [n for n in scene.selected_objects() if cmds.objExists(n)]
    if not objects and not picked:
        return ks._done("Select the objects to key", say)
    now = float(cmds.currentTime(query=True))
    span = scene.timeline_range()
    frames = ky.whole_frames(span[0], span[1] - 1) if span is not None else [now]
    if picked:
        curves, objects = list(picked), []      # only the picked curves - no fallback onto other channels
    else:
        curves = ks.selection_curves()
    picked_channels = scene.channel_box_attributes()
    keyed = 0
    with _Chunk():
        for curve in curves:
            segments = ks._segments(curve)
            if span is not None:
                before = len(ks._times(curve))
                _range_key(curve, frames, segments)
                keyed += len(ks._times(curve)) - before
            elif not any(ky.same(now, t) for t in ks._times(curve)):
                _range_key(curve, [now], segments)
                keyed += 1
        for node in objects:
            animated = set(ts._curves(node))
            if all_channels or not animated:
                for attribute in _keyable(node):
                    if attribute in animated:
                        continue
                    if picked_channels and attribute not in picked_channels:
                        continue
                    for frame in frames:
                        cmds.setKeyframe(node, attribute=attribute, time=frame)
                    keyed += len(frames)
    where = f"frames {frames[0]:g}-{frames[-1]:g}" if span is not None else f"frame {now:g}"
    if not keyed:
        return ks._done(f"Every channel is keyed on {where} already", say)
    return ks._done(f"Smart key: {ks._plural(keyed, 'key')} on {where}", say)


def set_smart_key_all(say: bool = False) -> str:
    return set_smart_key(True, say)


# --------------------------------------------------------------------------- delete

def delete_keys(say: bool = False) -> str:
    scope = _scope()
    removed = 0
    with _Chunk():
        for curve in scope.all_curves():
            if not cmds.objExists(curve):
                continue
            indices = scope.chosen(curve)
            times = ks._times(curve)
            chosen = [times[i] for i in indices if i < len(times)]
            ks._cut(curve, chosen)
            removed += len(chosen)
    if not removed:
        return ks._done(f"No key to delete on {scope.where()}", say)
    return ks._done(f"Deleted {ks._plural(removed, 'key')} ({scope.where()})", say)


# --------------------------------------------------------------------------- copy / cut / paste

class _Copied:
    """The keys copied last in this Maya: [(node, attribute, rows)], rows with times as they were."""
    channels: list = []
    start: float = 0.0
    end: float = 0.0


def _owner(curve: str) -> tuple:
    node, attribute = scene._driven(curve)
    return node, attribute


def copy_keys(say: bool = False, cut: bool = False) -> str:
    scope = _scope()
    channels = []
    for curve in scope.all_curves():
        times = ks._times(curve)
        chosen = sorted(times[i] for i in scope.chosen(curve) if i < len(times))
        if not chosen:
            continue
        node, attribute = _owner(curve)
        rows = ts._key_rows(curve, chosen[0], chosen[-1])
        rows = [r for r in rows if any(ky.same(r[0], t) for t in chosen)]
        if rows:
            channels.append((node, attribute, rows, curve))
    if not channels:
        return ks._done(f"No key to copy on {scope.where()}", say)
    _Copied.channels = [(n, a, r) for n, a, r, _c in channels]
    _Copied.start = min(r[0][0] for _n, _a, r in _Copied.channels)
    _Copied.end = max(r[-1][0] for _n, _a, r in _Copied.channels)
    count = sum(len(r) for _n, _a, r in _Copied.channels)
    if cut:
        with _Chunk():
            for _n, _a, rows, curve in channels:
                ks._cut(curve, [r[0] for r in rows])
        return ks._done(f"Cut {ks._plural(count, 'key')} of {ks._plural(len(channels), 'channel')}", say)
    return ks._done(f"Copied {ks._plural(count, 'key')} of {ks._plural(len(channels), 'channel')}", say)


def cut_keys(say: bool = False) -> str:
    return copy_keys(say, cut=True)


def _target_curves() -> list:
    """[(node, attribute, curve or None, time)] - where a paste goes."""
    now = float(cmds.currentTime(query=True))
    out = []
    if context() == "graph":
        picked = _picked()
        if picked:
            for curve, indices in picked.items():
                node, attribute = _owner(curve)
                out.append((node, attribute, curve, max(ks._times(curve)[i] for i in indices)))
            return out
        for curve in sorted(scene.graph_editor_curves()):
            if cmds.nodeType(curve) in scene.TIME_CURVES:
                node, attribute = _owner(curve)
                out.append((node, attribute, curve, now))
        return out
    span = scene.timeline_range()
    at = span[0] if span is not None else now
    for node in scene.selected_objects():
        curves = ts._curves(node)
        for copied_node, attribute, _rows in _Copied.channels:
            if cmds.objExists(f"{node}.{attribute}"):
                out.append((node, attribute, curves.get(attribute), at))
    return out


def _rows_for(node: str, attribute: str, one: bool):
    """The copied keys for node.attribute: its own channel, else the same channel of another object, else -
    one channel copied - that one (a channel onto another)."""
    same = [rows for n, a, rows in _Copied.channels if a == attribute]
    for n, a, rows in _Copied.channels:
        if n == node and a == attribute:
            return rows
    if same:
        return same[0]
    return _Copied.channels[0][2] if one else None


def paste_keys(relative: bool = False, say: bool = False) -> str:
    if not _Copied.channels:
        return ks._done("Nothing copied yet: Copy Keys first", say)
    targets = _target_curves()
    if not targets:
        return ks._done("Select where to paste: objects, or curves in the Graph Editor", say)
    one = len(_Copied.channels) == 1
    pasted = 0
    span = _Copied.end - _Copied.start
    seen = set()
    with _Chunk():
        for node, attribute, curve, time in targets:
            rows = _rows_for(node, attribute, one)
            if rows is None or (node, attribute) in seen or not ts._settable(node, attribute):
                continue
            seen.add((node, attribute))
            offset = time - _Copied.start
            shift = 0.0
            if relative:
                now = float(cmds.getAttr(f"{node}.{attribute}", time=time))
                shift = now - rows[0][1]
            if curve is not None and cmds.objExists(curve):
                cmds.cutKey(curve, time=(time - ky.SAME, time + span + ky.SAME), clear=True)
            moved = [[r[0], r[1] + shift] + list(r[2:]) for r in rows]
            pasted += ts._put_keys(node, attribute, {"keys": moved}, offset)
    if not pasted:
        return ks._done("No channel to paste onto - the copied channels aren't on the selection", say)
    kind = "Pasted relative" if relative else "Pasted"
    return ks._done(f"{kind}: {ks._plural(pasted, 'key')} onto {ks._plural(len(seen), 'channel')}", say)


def paste_keys_relative(say: bool = False) -> str:
    return paste_keys(True, say)


# --------------------------------------------------------------------------- Euler filter

def euler_filter(say: bool = False) -> str:
    """Maya's Euler filter, the three rotation curves of an object TOGETHER (a flip is fixed only when the
    filter sees x, y and z at once) over the stretch in play."""
    scope = _scope()
    groups = {}
    for curve in scope.all_curves():
        if cmds.nodeType(curve) not in ROTATIONS or not cmds.objExists(curve):
            continue
        times = ks._times(curve)
        chosen = times if scope.kind == "frame" else sorted(times[i] for i in scope.chosen(curve) if i < len(times))
        if not chosen:
            continue
        node = _owner(curve)[0] or curve
        group = groups.setdefault(node, [[], chosen[0], chosen[-1]])
        group[0].append(curve)
        group[1], group[2] = min(group[1], chosen[0]), max(group[2], chosen[-1])
    done = 0
    with _Chunk():
        for curves, start, end in groups.values():
            if end - start < ky.SAME:
                continue
            cmds.filterCurve(curves, filter="euler", startTime=start, endTime=end)
            done += len(curves)
    if not done:
        return ks._done(f"No rotation curve to filter on {scope.where()}", say)
    return ks._done(f"Euler filter on {ks._plural(done, 'rotation curve')} ({scope.where()})", say)
