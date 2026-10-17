# tools/maya/animation/scene.py
"""The Maya side of the sliders: WHAT they act on, and a drag that ends as one undo step.

What a slider acts on (`find_targets`), the first that applies:
    1. keys selected in a Graph Editor that is on screen (keys stay selected after it is closed -
       a slider meant for the pose must not reach them then);
    2. the selected objects' keys inside the range highlighted on the timeline;
    3. the selected objects' keys on the current frame - a channel without a key there gets one.
In 2 and 3 only the curves the Graph Editor on screen shows count (a channel picked in its list:
that one alone), else the channels picked in the Channel Box when some are. Only curves of
time (animCurveTA / TL / TU / TT) are touched; driven keys are not.

A drag (`Drag`): keys that must be added are added with the undo queue off, then every move of the
slider sets the values through the API (nothing reaches the undo queue, the viewport follows at
once); `commit()` puts everything back as it was and does the final change again with maya.cmds in
ONE undo chunk ("MSL Animation"), rotations Euler-filtered over the changed range. `cancel()` only
puts it back. Values are worked in the units the Graph Editor shows (degrees, the scene's length
unit); the API's own units (radians, centimetres) only at the moment a value is set.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from msl_tools.msl.tools.maya.animation import curves as cv

UNDO_NAME = "MSL Animation"
TIME_CURVES = ("animCurveTA", "animCurveTL", "animCurveTU", "animCurveTT")
ROTATIONS = ("rotateX", "rotateY", "rotateZ", "rx", "ry", "rz")
SAME_TIME = 1e-3         # a key this close to the current frame IS on it
SAMPLE_STEP = 0.05       # frames between the samples the time offset reads the original curve from
SAMPLE_MARGIN = 2 * cv.OFFSET_FRAMES + 2


@dataclass
class CurveTarget:
    """One curve a slider acts on: which of its keys, and what it held before the drag."""

    curve: str
    node: str = ""
    attribute: str = ""
    indices: list = field(default_factory=list)   # the keys acted on (after any were added)
    times: list = field(default_factory=list)     # every key of the curve, before the drag
    values: list = field(default_factory=list)
    added: list = field(default_factory=list)     # times of keys this drag added
    default: float = 0.0
    factor: float = 1.0                           # the window's unit -> the API's
    order: int = 0
    rotation: bool = False
    _fn: object = None
    _samples: object = None                       # (start, step, values) of the original curve

    def fn(self) -> "oma.MFnAnimCurve":
        if self._fn is None:
            self._fn = oma.MFnAnimCurve(_depend_node(self.curve))
        return self._fn

    def evaluate(self, time: float) -> float:
        """The ORIGINAL curve's value at `time` (sampled before the drag changed it)."""
        start, step, values = self._samples
        position = (time - start) / step
        if position <= 0:
            return values[0]
        if position >= len(values) - 1:
            return values[-1]
        low = int(position)
        part = position - low
        return values[low] + (values[low + 1] - values[low]) * part

    def sample(self) -> None:
        if self._samples is not None or not self.times:
            return
        unit = om.MTime.uiUnit()
        start = min(self.times) - SAMPLE_MARGIN
        count = int((max(self.times) + SAMPLE_MARGIN - start) / SAMPLE_STEP) + 2
        fn = self.fn()
        values = [fn.evaluate(om.MTime(start + i * SAMPLE_STEP, unit)) / self.factor for i in range(count)]
        self._samples = (start, SAMPLE_STEP, values)


def _depend_node(name: str):
    selection = om.MSelectionList()
    selection.add(name)
    return selection.getDependNode(0)


def _factor(curve_type: str) -> float:
    if curve_type == "animCurveTA":
        return om.MAngle(1.0, om.MAngle.uiUnit()).asRadians()
    if curve_type == "animCurveTL":
        return om.MDistance(1.0, om.MDistance.uiUnit()).asCentimeters()
    return 1.0


# --------------------------------------------------------------------------- what is acted on

def graph_editor_panel() -> str:
    """The Graph Editor panel on screen ("" when none is)."""
    for panel in cmds.getPanel(visiblePanels=True) or []:
        try:
            if cmds.getPanel(typeOf=panel) == "scriptedPanel" and \
                    cmds.scriptedPanel(panel, query=True, type=True) == "graphEditor":
                return panel
        except RuntimeError:
            continue
    return ""


def graph_editor_on_screen() -> bool:
    return bool(graph_editor_panel())


def graph_editor_curves() -> set:
    """The curves the Graph Editor on screen SHOWS - what is picked in its list (one channel picked:
    that curve alone; an object: all of its). Empty when none is on screen."""
    panel = graph_editor_panel()
    if not panel:
        return set()
    try:
        return set(cmds.animCurveEditor(panel + "GraphEd", query=True, curvesShown=True) or [])
    except RuntimeError:
        return set()


def timeline_range() -> "tuple | None":
    """The range highlighted on the timeline (start, end - the end is NOT in it), or None."""
    try:
        from maya import mel
        slider = mel.eval("$_msl_tc = $gPlayBackSlider")
        if not cmds.timeControl(slider, query=True, rangeVisible=True):
            return None
        start, end = cmds.timeControl(slider, query=True, rangeArray=True)
        return float(start), float(end)
    except Exception:
        return None


def channel_box_attributes() -> set:
    """The attributes picked in the Channel Box (short and long names), empty when none is."""
    picked = set()
    for flag in ("selectedMainAttributes", "selectedShapeAttributes", "selectedHistoryAttributes",
                 "selectedOutputAttributes"):
        try:
            picked.update(cmds.channelBox("mainChannelBox", query=True, **{flag: True}) or [])
        except RuntimeError:
            pass
    return picked


def selected_objects() -> list:
    return cmds.ls(orderedSelection=True, long=True) or []


def _driven(curve: str) -> tuple:
    """(node, attribute) the curve animates, through anim layers / pair blends too ("", "" if unknown)."""
    plugs = cmds.listConnections(curve + ".output", source=False, destination=True, plugs=True,
                                 skipConversionNodes=True) or []
    for plug in plugs:
        node, _, attribute = plug.partition(".")
        if cmds.nodeType(node) not in ("animBlendNodeAdditiveRotation", "animBlendNodeAdditiveDL",
                                       "animBlendNodeAdditiveDA", "animBlendNodeAdditiveScale",
                                       "animBlendNodeAdditive", "animBlendNodeBoolean", "pairBlend"):
            return cmds.ls(node, long=True)[0], attribute
    return "", ""


def _default(node: str, attribute: str) -> float:
    if not node or not attribute:
        return 0.0
    try:
        found = cmds.attributeQuery(attribute.split("[")[0], node=node, listDefault=True)
        return float(found[0]) if found else 0.0
    except (RuntimeError, TypeError, ValueError):
        return 0.0


def _read(target: CurveTarget) -> None:
    target.times = [float(t) for t in cmds.keyframe(target.curve, query=True, timeChange=True) or []]
    target.values = [float(v) for v in cmds.keyframe(target.curve, query=True, valueChange=True) or []]


def _target(curve: str, order: int = 0) -> "CurveTarget | None":
    kind = cmds.nodeType(curve)
    if kind not in TIME_CURVES:
        return None
    node, attribute = _driven(curve)
    short = cmds.attributeName(f"{node}.{attribute}", short=True) if node and attribute else ""
    return CurveTarget(curve=curve, node=node, attribute=attribute, factor=_factor(kind), order=order,
                       default=_default(node, attribute), rotation=attribute in ROTATIONS or short in ROTATIONS)


def _object_curves(objects: list) -> list:
    """[(curve, the object's place in the selection)] of the selected objects' time curves - only
    those the Graph Editor on screen shows, else only the Channel Box's picked channels if any."""
    shown = graph_editor_curves()
    picked = set() if shown else channel_box_attributes()
    found, seen = [], set()
    for order, node in enumerate(objects):
        for curve in cmds.keyframe(node, query=True, name=True) or []:
            if curve in seen or cmds.nodeType(curve) not in TIME_CURVES:
                continue
            if shown and curve not in shown:
                continue
            if picked:
                _node, attribute = _driven(curve)
                names = {attribute}
                if _node and attribute:
                    names.add(cmds.attributeName(f"{_node}.{attribute}", short=True))
                if not names & picked:
                    continue
            seen.add(curve)
            found.append((curve, order))
    return found


def find_targets(add_keys: bool = True) -> tuple:
    """(targets, where) - what a slider acts on now, and in words ("Graph Editor" / "frames 10-24" /
    "frame 12"). With `add_keys` False nothing is added (for describing it): channels without a key
    on the current frame are listed with no indices."""
    if graph_editor_on_screen():
        curves = cmds.keyframe(query=True, selected=True, name=True) or []
        targets = []
        for curve in curves:
            target = _target(curve)
            if target is None:
                continue
            target.indices = [int(i) for i in cmds.keyframe(curve, query=True, selected=True,
                                                           indexValue=True) or []]
            if target.indices:
                _read(target)
                targets.append(target)
        if targets:
            return targets, "Graph Editor"
    objects = selected_objects()
    pairs = _object_curves(objects)
    span = timeline_range()
    targets = []
    if span is not None:
        start, end = span
        for curve, order in pairs:
            target = _target(curve, order)
            if target is None:
                continue
            _read(target)
            target.indices = [i for i, t in enumerate(target.times) if start - SAME_TIME <= t < end - SAME_TIME]
            if target.indices:
                targets.append(target)
        _counted(targets, objects)
        return targets, f"frames {start:g}-{end - 1:g}"
    now = float(cmds.currentTime(query=True))
    for curve, order in pairs:
        target = _target(curve, order)
        if target is None:
            continue
        _read(target)
        index = next((i for i, t in enumerate(target.times) if abs(t - now) < SAME_TIME), None)
        if index is None and add_keys:
            target.added.append(now)
        elif index is not None:
            target.indices = [index]
        targets.append(target)
    _counted(targets, objects)
    return targets, f"frame {now:g}"


def _counted(targets: list, objects: list) -> None:
    for target in targets:
        target.order = min(target.order, max(0, len(objects) - 1))


def describe() -> str:
    """What the sliders would act on now, in a few words (the window's line)."""
    try:
        targets, where = find_targets(add_keys=False)
    except Exception:
        return ""
    if not targets:
        return "Nothing animated is selected" if where != "Graph Editor" else ""
    keys = sum(max(1, len(target.indices)) for target in targets)
    return f"{where} · {keys} key{'s' if keys != 1 else ''} on {len(targets)} curve{'s' if len(targets) != 1 else ''}"


def default_tangents() -> tuple:
    """Maya's default in / out tangent types (Preferences > Animation; "auto" out of the box)."""
    try:
        return (cmds.keyTangent(query=True, g=True, inTangentType=True)[0],
                cmds.keyTangent(query=True, g=True, outTangentType=True)[0])
    except (RuntimeError, TypeError, IndexError):
        return "auto", "auto"


def _add_key(curve: str, time: float) -> None:
    """A key added where a channel has none. Inserted, it keeps the curve's shape - with FIXED
    tangents as steep as the curve there (measured, Maya 2025: -51 degrees on a bouncing ball), so
    moving its value made the curve shoot past its neighbors. It gets Maya's default tangents (auto
    out of the box) instead, as the reference tool does (measured: auto)."""
    cmds.setKeyframe(curve, insert=True, time=time)
    in_type, out_type = default_tangents()
    try:
        cmds.keyTangent(curve, time=(time, time), inTangentType=in_type, outTangentType=out_type)
    except RuntimeError:
        pass


# --------------------------------------------------------------------------- undo

class _NoUndo:
    """The undo queue off for what is inside, then put back as it WAS."""

    def __enter__(self):
        self._was = cmds.undoInfo(query=True, stateWithoutFlush=True)
        cmds.undoInfo(stateWithoutFlush=False)
        return self

    def __exit__(self, *_exc):
        cmds.undoInfo(stateWithoutFlush=self._was)
        return False


class _Chunk:
    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
        return self

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)
        return False


# --------------------------------------------------------------------------- Maya's buffer curve

def buffer_values(curve: str, times) -> "list | None":
    """Maya's buffer curve (the Graph Editor's Curves > Buffer Curve Snapshot) read at these times, or
    None when the curve has none. Maya keeps it out of reach of any query - it is read by SWAPPING it
    with the curve, evaluating, and swapping back, with the undo queue off and the scene's modified mark
    put back (measured, Maya 2025: the swaps leave the undo queue and the snapshot as they were)."""
    try:
        if not cmds.bufferCurve(curve, query=True, exists=True):
            return None
    except RuntimeError:
        return None
    modified = cmds.file(query=True, modified=True)
    values = None
    with _NoUndo():
        cmds.bufferCurve(curve, swap=True)
        try:
            values = [float(cmds.keyframe(curve, query=True, eval=True, time=(t, t))[0]) for t in times]
        finally:
            cmds.bufferCurve(curve, swap=True)
    cmds.file(modified=modified)
    return values


# --------------------------------------------------------------------------- a drag

class Drag:
    """A slider pressed: `update(weight)` while it moves, `commit(weight)` when let go, or `cancel()`."""

    # the values before the last change, per curve {time: value} - for Blend to Undo
    _last_change: dict = {}

    def __init__(self, mode: str, frame: "float | None" = None, frame_right: "float | None" = None):
        self.mode = cv.BY_KEY[mode]
        self.frame = frame
        self.frame_right = frame_right
        self.targets, self.where = find_targets(add_keys=True)
        self._done = False
        if self.targets:
            with _NoUndo():
                for target in self.targets:
                    for time in target.added:
                        _add_key(target.curve, time)
                    if target.added:
                        _read(target)
                        target.indices = sorted({i for i, t in enumerate(target.times)
                                                 if any(abs(t - a) < SAME_TIME for a in target.added)}
                                                | set(target.indices))
        self._blocks = self._make_blocks()

    def __bool__(self) -> bool:
        return bool(self.targets)

    def _make_blocks(self) -> list:
        blocks = []
        needs_curve = self.mode.key in ("time_offset", "stagger") or self.frame is not None \
            or self.frame_right is not None
        self.buffered = 0      # curves that have a buffer curve (Blend to Buffer)
        ranks = cv.chain_ranks(target.node for target in self.targets)
        for number, target in enumerate(self.targets):
            if needs_curve:
                target.sample()
            buffered = buffer_values(target.curve, target.times) if self.mode.key == "buffer" else None
            if buffered is not None:
                self.buffered += 1
            frame_value = target.evaluate(self.frame) if (self.frame is not None and target._samples) else None
            frame_right = target.evaluate(self.frame_right) if (self.frame_right is not None and target._samples) \
                else None
            remembered = self._last_change.get(target.curve, {})
            for run in cv.split_runs(target.indices):
                undo = [remembered.get(round(target.times[i], 3)) for i in run]
                block = cv.block_from_keys(
                    target.times, target.values, run, default=target.default, frame_value=frame_value,
                    frame_value_right=frame_right,
                    buffer_values=[buffered[i] for i in run] if buffered is not None else None,
                    undo_values=undo if all(v is not None for v in undo) else None,
                    evaluate=target.evaluate if target._samples else None,
                    order=ranks.get(target.node, 0), count=max(1, len(ranks)), seed=number * 7919 + run[0])
                blocks.append((target, run, block))
        return blocks

    def _new_values(self, weight: float) -> list:
        return [(target, run, cv.apply(self.mode, block, weight)) for target, run, block in self._blocks]

    def update(self, weight: float) -> None:
        """The curves as this weight would leave them - live, outside the undo queue."""
        for target, run, values in self._new_values(weight):
            fn = target.fn()
            for index, value in zip(run, values):
                fn.setValue(index, value * target.factor)
        cmds.refresh(currentView=True)   # the viewport follows during the drag

    def _restore(self) -> None:
        for target in self.targets:
            fn = target.fn()
            for index, value in enumerate(target.values):
                if index < fn.numKeys:
                    fn.setValue(index, value * target.factor)
        with _NoUndo():
            for target in self.targets:
                for time in target.added:
                    cmds.cutKey(target.curve, time=(time, time), clear=True)

    def cancel(self) -> None:
        if self.targets and not self._done:
            self._restore()
            self._done = True

    def commit(self, weight: float, euler: bool = True) -> str:
        """Ends the drag: the change made again as ONE undo step. Returns what was done, in words."""
        if not self.targets or self._done:
            return ""
        changes = self._new_values(weight)
        self._restore()
        self._done = True
        remembered = {}
        changed = 0
        rotated, low, high = set(), None, None
        with _Chunk():
            for target in self.targets:
                for time in target.added:
                    _add_key(target.curve, time)
            for target, run, values in changes:
                before = remembered.setdefault(target.curve, {})
                for index, value in zip(run, values):
                    old = target.values[index]
                    before[round(target.times[index], 3)] = old
                    if abs(value - old) > 1e-9 or target.added:
                        cmds.keyframe(target.curve, edit=True, index=(index, index), absolute=True,
                                      valueChange=value)
                        changed += 1
                if target.rotation:
                    rotated.add(target.curve)
                    times = [target.times[i] for i in run]
                    low = min(times + ([low] if low is not None else []))
                    high = max(times + ([high] if high is not None else []))
            if euler and rotated and low is not None:
                _euler(sorted(rotated), low, high)
        Drag._last_change = remembered
        keys = sum(len(run) for _t, run, _v in changes)
        curves = len(self.targets)
        return (f"{self.mode.title} {cv.weight_text(self.mode, weight)} · {keys} key{'s' if keys != 1 else ''} "
                f"on {curves} curve{'s' if curves != 1 else ''} ({self.where})")


def _picked_keys() -> dict:
    """{curve: [indices]} of the keys selected now (in any curve)."""
    return {curve: [int(i) for i in cmds.keyframe(curve, query=True, selected=True, indexValue=True) or []]
            for curve in cmds.keyframe(query=True, selected=True, name=True) or []}


def _pick_keys(picked: dict) -> None:
    cmds.selectKey(clear=True)
    for curve, indices in picked.items():
        if indices and cmds.objExists(curve):
            cmds.selectKey(curve, add=True, index=[(i, i) for i in indices])


def _euler(curves: list, low: float, high: float) -> None:
    """An Euler filter over the changed range, plus a key either side (so the range joins the rest).
    filterCurve leaves only the filtered curves' keys selected (measured, Maya 2025) - the next drag
    would then act on them alone - so the key selection is put back after it."""
    picked = _picked_keys()
    try:
        cmds.filterCurve(curves, filter="euler", startTime=low - 1, endTime=high + 1)
    except RuntimeError:
        try:
            cmds.filterCurve(curves, filter="euler")
        except RuntimeError:
            pass
    if _picked_keys() != picked:
        _pick_keys(picked)


# --------------------------------------------------------------------------- keys added / removed

def _key_data(curve: str, time: float) -> dict:
    """All a key is, read so it can be made again exactly: value and tangents (types, angles, weights,
    locks), in the units the Graph Editor shows."""
    span = (time, time)

    def query(**flag):
        found = cmds.keyTangent(curve, time=span, query=True, **flag)
        return found[0] if found else None

    return {"time": time, "value": cmds.keyframe(curve, time=span, query=True, valueChange=True)[0],
            "itt": query(inTangentType=True), "ott": query(outTangentType=True),
            "ia": query(inAngle=True), "oa": query(outAngle=True),
            "iw": query(inWeight=True), "ow": query(outWeight=True),
            "lock": query(lock=True), "weightLock": query(weightLock=True)}


def _remake_key(curve: str, data: dict) -> None:
    time = data["time"]
    cmds.setKeyframe(curve, time=time, value=data["value"])
    span = (time, time)
    cmds.keyTangent(curve, time=span, lock=False)
    try:
        cmds.keyTangent(curve, time=span, weightLock=False)
    except RuntimeError:
        pass
    flags = {"inTangentType": data["itt"], "outTangentType": data["ott"]}
    if data["itt"] in ("fixed",) or data["ott"] in ("fixed",):
        flags.update(inAngle=data["ia"], outAngle=data["oa"])
    cmds.keyTangent(curve, time=span, **{k: v for k, v in flags.items() if v is not None})
    if data["itt"] == "fixed" and data["iw"] is not None:
        cmds.keyTangent(curve, time=span, inWeight=data["iw"])
    if data["ott"] == "fixed" and data["ow"] is not None:
        cmds.keyTangent(curve, time=span, outWeight=data["ow"])
    if data["lock"] is not None:
        cmds.keyTangent(curve, time=span, lock=bool(data["lock"]))
    if data["weightLock"] is not None:
        try:
            cmds.keyTangent(curve, time=span, weightLock=bool(data["weightLock"]))
        except RuntimeError:
            pass


class KeysDrag:
    """A slider whose mode adds or removes keys (Simplify | Bake): every move puts the curves back as
    they were - keys it added taken out, keys it removed made again with their exact tangents - and
    does the new weight's change, all outside the undo queue; `commit()` puts them back once more and
    does the final change as ONE undo step. On a single key (the current frame) it works on the whole
    curve. The same face as Drag."""

    buffered = 0

    def __init__(self, mode: str, frame: "float | None" = None, frame_right: "float | None" = None):
        self.mode = cv.BY_KEY[mode]
        self.targets, self.where = find_targets(add_keys=False)
        self._runs = []          # (target, the run's key times, values, the keys' full data)
        for target in self.targets:
            indices = target.indices if len(target.indices) > 1 else list(range(len(target.times)))
            if len(indices) < 2:
                continue
            target.sample()
            times = [target.times[i] for i in indices]
            values = [target.values[i] for i in indices]
            self._runs.append((target, times, values, {}))
        self._changed = []       # (curve, times removed, times added) of the change on screen
        self._done = False
        # keys made again are made UNPICKED: the Graph Editor's pick is put back after (else the next drag
        # works on the keys that happened to stay picked - it did: Simplify after an Esc took 31 keys to 5)
        self._picked = _picked_keys() if self.where == "Graph Editor" else {}

    def __bool__(self) -> bool:
        return bool(self._runs)

    def _plan(self, weight: float) -> list:
        plan = []
        for target, times, values, saved in self._runs:
            if weight < 0:
                keep = set(cv.simplify_keep(times, values, weight))
                removed = [times[i] for i in range(len(times)) if i not in keep]
                plan.append((target, removed, []))
            else:
                plan.append((target, [], cv.bake_times(times, weight)))
        return plan

    def _do(self, weight: float) -> int:
        count = 0
        for target, removed, added in self._plan(weight):
            saved = next(run[3] for run in self._runs if run[0] is target)
            for time in removed:
                if time not in saved:
                    saved[time] = _key_data(target.curve, time)
                cmds.cutKey(target.curve, time=(time, time), clear=True)
            in_type, out_type = default_tangents()
            for time in added:
                cmds.setKeyframe(target.curve, time=time, value=target.evaluate(time))
                try:
                    cmds.keyTangent(target.curve, time=(time, time), inTangentType=in_type, outTangentType=out_type)
                except RuntimeError:
                    pass
            self._changed.append((target.curve, removed, added, saved))
            count += len(removed) + len(added)
        return count

    def _undo_change(self) -> None:
        for curve, removed, added, saved in reversed(self._changed):
            for time in added:
                cmds.cutKey(curve, time=(time, time), clear=True)
            for time in removed:
                _remake_key(curve, saved[time])
        self._changed = []

    def update(self, weight: float) -> None:
        with _NoUndo():
            self._undo_change()
            self._do(weight)
        cmds.refresh(currentView=True)

    def cancel(self) -> None:
        if not self._done:
            with _NoUndo():
                self._undo_change()
                if self._picked:
                    _pick_keys(self._picked)
            self._done = True

    def commit(self, weight: float, euler: bool = True) -> str:
        if not self._runs or self._done:
            return ""
        with _NoUndo():
            self._undo_change()
        self._done = True
        with _Chunk():
            count = self._do(weight)
            if self._picked:            # what is left of the picked runs, the baked keys included
                cmds.selectKey(clear=True)
                for target, times, _values, _saved in self._runs:
                    cmds.selectKey(target.curve, add=True, time=(times[0], times[-1]))
        self._changed = []
        verb = "removed" if weight < 0 else "added"
        return (f"{self.mode.title} {cv.weight_text(self.mode, weight)} · {count} key{'s' if count != 1 else ''} "
                f"{verb} on {len(self._runs)} curve{'s' if len(self._runs) != 1 else ''} ({self.where})")


def make_drag(mode: str, frame: "float | None" = None, frame_right: "float | None" = None):
    """The drag that does this mode: a KeysDrag for the modes that add / remove keys, else a Drag."""
    if mode in cv.STRUCTURE_MODES:
        return KeysDrag(mode, frame, frame_right)
    return Drag(mode, frame, frame_right)


def apply_once(mode: str, weight: float, frame: "float | None" = None, say: bool = False) -> str:
    """One change without a drag (a click on a mark, a hotkey): one undo step. Returns it in words."""
    drag = make_drag(mode, frame)
    if not drag:
        text = "Nothing to act on: select animated objects (or keys in the Graph Editor)"
    else:
        text = drag.commit(weight)
    if say:
        cmds.inViewMessage(amg=f"MSL: {text}", pos="topCenter", fade=True, fadeStayTime=900)
    return text
