# tools/maya/scripts/reset_attributes.py
"""Reset Attributes: values back to their defaults — the user's old Attribute Resetter, rewritten.

What is reset, by what is picked (the first that holds):
    1. keys picked in a Graph Editor that is on screen      -> those keys' values
    2. channels picked in the Channel Box (any section: the object, its shape, inputs, outputs)
                                                             -> those channels, on their objects
    3. the selected objects                                  -> a transform (or joint): its move /
       rotate / scale; a shape or another node selected by itself: its keyable attributes
`run(transforms_only=False)` makes 3 take a transform's other keyable attributes too,
`keyable_only=False` the ones shown in the Channel Box but not keyable as well.

A node's attribute `default_<name>` (say `default_rotateY`) is that attribute's default — whatever
Maya's own default is. Angles: Maya hands defaults, values and key values in the same UI unit, so
nothing is converted (measured, Maya 2026: a 30 degree default reads 30).

Left alone, and counted: locked attributes, attributes another node drives (a constraint, an
expression — keys are no such driver: a keyed channel gets the value), keys whose curve drives no
attribute or drives it through a blend node. One undo step; the outcome is said in the viewport.
"""
from maya import cmds

PREFIX = "default_"
TRANSFORM_PARTS = ("translate", "rotate", "scale")
UNDO_NAME = "MSL Reset Attributes"
BLENDS = ("pairBlend", "blendWeighted")   # a curve into one of these: its own default means nothing
SECTIONS = (("selectedMainAttributes", "mainObjectList"), ("selectedShapeAttributes", "shapeObjectList"),
            ("selectedHistoryAttributes", "historyObjectList"), ("selectedOutputAttributes", "outputObjectList"))


class Outcome:
    """What a reset did, for the message."""

    def __init__(self):
        self.reset = 0       # values changed
        self.same = 0        # already at the default
        self.locked = 0
        self.driven = 0
        self.other = 0       # no default / not a value / a blend in between
        self.nodes = set()
        self.what = "attributes"

    def text(self) -> str:
        if not (self.reset or self.same or self.locked or self.driven or self.other):
            return "Reset: nothing to reset there"
        parts = [f"{self.reset} {self.what} back to default" + (f" on {len(self.nodes)} object(s)" if self.nodes else "")]
        if self.same:
            parts.append(f"{self.same} already there")
        left = []
        if self.locked:
            left.append(f"{self.locked} locked")
        if self.driven:
            left.append(f"{self.driven} driven")
        if self.other:
            left.append(f"{self.other} with no default")
        if left:
            parts.append(", ".join(left) + " - left")
        return "Reset: " + " · ".join(parts)


def run(transforms_only: bool = True, keyable_only: bool = True) -> Outcome:
    """Resets what is picked (see the module) as one undo step and says so. Returns the outcome."""
    keys = picked_keys()
    channels = [] if keys else picked_channels()
    nodes = [] if keys or channels else (cmds.ls(selection=True, objectsOnly=True, long=True) or [])
    if not (keys or channels or nodes):
        _say("Reset: select objects, or pick channels / keys first")
        return Outcome()
    cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        if keys:
            outcome = reset_keys(keys)
        elif channels:
            outcome = reset_plugs(channels)
        else:
            outcome = reset_nodes(nodes, transforms_only, keyable_only)
    finally:
        cmds.undoInfo(closeChunk=True)
    _say(outcome.text())
    return outcome


# --- what is picked ------------------------------------------------------------------------------

def picked_keys() -> list:
    """The anim curves with picked keys — only while a Graph Editor with picked curves is ON
    SCREEN: keys stay picked after the editor is closed, and a reset meant for the object must not
    reach them."""
    try:
        visible = set(cmds.getPanel(visiblePanels=True) or [])
        for panel in cmds.getPanel(scriptType="graphEditor") or []:
            editor = panel + "GraphEd"
            if panel in visible and cmds.animCurveEditor(editor, exists=True) and \
                    cmds.animCurveEditor(editor, query=True, areCurvesSelected=True):
                return cmds.keyframe(query=True, name=True, selected=True) or []
    except RuntimeError:
        pass
    return []


def picked_channels() -> list:
    """[(node, attribute)] picked in the Channel Box, every section, on the objects it lists there."""
    picked = []
    try:
        for attributes_flag, objects_flag in SECTIONS:
            attributes = cmds.channelBox("mainChannelBox", query=True, **{attributes_flag: True}) or []
            objects = (cmds.channelBox("mainChannelBox", query=True, **{objects_flag: True}) or []) if attributes else []
            picked += [(node, attribute) for node in objects for attribute in attributes]
    except RuntimeError:     # no Channel Box (mayapy)
        return []
    return list(dict.fromkeys(picked))


# --- defaults ------------------------------------------------------------------------------------

def default_of(node: str, attribute: str):
    """The value `attribute` goes back to: the node's `default_<attribute>` if it has one, else
    Maya's default (a number, or a tuple for a compound); None = none to be had."""
    long_name = attribute
    try:
        long_name = cmds.attributeQuery(attribute, node=node, longName=True)
    except RuntimeError:
        return None
    for name in (PREFIX + long_name, PREFIX + attribute):
        if cmds.attributeQuery(name, node=node, exists=True):
            try:
                return cmds.getAttr(f"{node}.{name}")
            except (RuntimeError, ValueError):
                break
    try:
        values = cmds.attributeQuery(attribute, node=node, listDefault=True)
    except RuntimeError:
        return None
    if not values:
        return None
    return values[0] if len(values) == 1 else tuple(values)


# --- resetting -----------------------------------------------------------------------------------

def _driver(plug: str) -> str:
    """What drives `plug` other than keys ("" = nothing / only keys)."""
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    for source in sources:
        if not cmds.nodeType(source).startswith("animCurve"):
            return source
    return ""


def reset_plug(node: str, attribute: str, outcome: Outcome) -> None:
    plug = f"{node}.{attribute}"
    if not cmds.attributeQuery(attribute, node=node, exists=True):
        outcome.other += 1
        return
    try:
        if cmds.getAttr(plug, lock=True):
            outcome.locked += 1
            return
        if _driver(plug):
            outcome.driven += 1
            return
        default = default_of(node, attribute)
        current = cmds.getAttr(plug)
    except (RuntimeError, ValueError):
        outcome.other += 1
        return
    if isinstance(current, list) and len(current) == 1 and isinstance(current[0], tuple):
        current = current[0]                            # a compound reads [(x, y, z)]
    if default is None or isinstance(current, str):
        outcome.other += 1
        return
    if _same(current, default):
        outcome.same += 1
        return
    try:
        if isinstance(default, tuple):
            cmds.setAttr(plug, *default)
        else:
            cmds.setAttr(plug, default)
    except (RuntimeError, ValueError, TypeError):
        outcome.other += 1
        return
    outcome.reset += 1
    outcome.nodes.add(node)


def _same(current, default) -> bool:
    if isinstance(default, tuple) or isinstance(current, (tuple, list)):
        current = tuple(current) if isinstance(current, (tuple, list)) else (current,)
        default = default if isinstance(default, tuple) else (default,)
        return len(current) == len(default) and all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(current, default))
    try:
        return abs(float(current) - float(default)) < 1e-9
    except (TypeError, ValueError):
        return current == default


def reset_plugs(channels) -> Outcome:
    """[(node, attribute)] back to their defaults."""
    outcome = Outcome()
    outcome.what = "channel(s)"
    for node, attribute in channels:
        reset_plug(node, attribute, outcome)
    return outcome


def attributes_to_reset(node: str, transforms_only: bool = True, keyable_only: bool = True) -> list:
    """What resetting `node` itself covers: a transform's move / rotate / scale (all its keyable
    ones with `transforms_only` off), any other node's keyable attributes; with `keyable_only` off
    also what the Channel Box shows without keys."""
    attributes = cmds.listAttr(node, keyable=True) or []   # locked ones too: they are counted as left
    if not keyable_only:
        attributes += [name for name in cmds.listAttr(node, channelBox=True) or [] if name not in attributes]
    if transforms_only and cmds.objectType(node, isAType="transform"):
        attributes = [name for name in attributes if name.startswith(TRANSFORM_PARTS)]
    return attributes


def reset_nodes(nodes, transforms_only: bool = True, keyable_only: bool = True) -> Outcome:
    outcome = Outcome()
    for node in nodes:
        for attribute in attributes_to_reset(node, transforms_only, keyable_only):
            if "." in attribute:          # a multi's element listAttr hands out (weights.w0): not a channel
                continue
            reset_plug(node, attribute, outcome)
    return outcome


def reset_keys(curves) -> Outcome:
    """The picked keys of `curves` to the default of the attribute each curve drives."""
    outcome = Outcome()
    outcome.what = "key(s)"
    for curve in curves:
        targets = cmds.listConnections(curve + ".output", source=False, destination=True, plugs=True,
                                       skipConversionNodes=True) or []
        times = cmds.keyframe(curve, query=True, selected=True, timeChange=True) or []
        values = cmds.keyframe(curve, query=True, selected=True, valueChange=True) or []
        if not targets or cmds.nodeType(targets[0].split(".", 1)[0]) in BLENDS:
            outcome.other += len(times)
            continue
        node, attribute = targets[0].split(".", 1)
        default = default_of(node, attribute)
        if default is None or isinstance(default, tuple):
            outcome.other += len(times)
            continue
        for time, value in zip(times, values):
            if abs(value - default) < 1e-9:
                outcome.same += 1
                continue
            cmds.keyframe(curve, edit=True, time=(time, time), valueChange=default)
            outcome.reset += 1
        outcome.nodes.add(node)
    return outcome


def _say(text: str) -> None:
    print("MSL " + text)
    try:
        cmds.inViewMessage(assistMessage=text, position="topCenter", fade=True, fadeStayTime=1400)
    except RuntimeError:
        pass
