# tools/maya/controls/attributes.py
"""Channels and attributes of the selected objects (maya.cmds, no Qt): which of the ten transform
channels are open, locked or locked + hidden; values back to their defaults; the rotate order; the
objects' OWN attributes — read in the Channel Box's order, added (number, whole number, on / off,
a list of names, a separator line), removed, copied to other objects and put in another order.
Every change is ONE undo step."""
from maya import cmds

UNDO_NAME = "MSL Controls"

MOVE, TURN, SCALE = ("tx", "ty", "tz"), ("rx", "ry", "rz"), ("sx", "sy", "sz")
CHANNELS = MOVE + TURN + SCALE + ("v",)
OPEN, LOCKED, HIDDEN, MIXED = "open", "locked", "hidden", "mixed"
ROTATE_ORDERS = ("xyz", "yzx", "zxy", "xzy", "yxz", "zyx")

# the ready sets of the CHANNELS card: what stays open (the rest is locked and hidden)
QUICK = {"Move": MOVE, "Rotate": TURN, "Move + rotate": MOVE + TURN, "All": MOVE + TURN + SCALE + ("v",)}

FLOAT, WHOLE, SWITCH, LIST, SEPARATOR = "Number", "Whole number", "On / off", "List", "Separator"
KINDS = (FLOAT, WHOLE, SWITCH, LIST, SEPARATOR)
_TYPE_OF = {FLOAT: "double", WHOLE: "long", SWITCH: "bool", LIST: "enum"}
_KIND_OF = {"double": FLOAT, "float": FLOAT, "doubleLinear": FLOAT, "doubleAngle": FLOAT, "long": WHOLE,
            "short": WHOLE, "byte": WHOLE, "bool": SWITCH, "enum": LIST}
SEPARATOR_PREFIX = "sep"           # a separator is an enum of one name, locked, shown: sep, sep1, sep2…


class _Chunk:
    def __enter__(self):
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)

    def __exit__(self, *_exc):
        cmds.undoInfo(closeChunk=True)
        return False


def _ours(node: str, attr: str) -> bool:
    """Can we change this attribute's lock / visibility: it is there and the node isn't referenced
    with the attribute locked in the reference."""
    return cmds.attributeQuery(attr, node=node, exists=True)


# ------------------------------------------------------------------ channels

def channel_state(node: str, attr: str) -> str:
    plug = f"{node}.{attr}"
    locked = cmds.getAttr(plug, lock=True)
    shown = cmds.getAttr(plug, keyable=True) or cmds.getAttr(plug, channelBox=True)
    if locked and not shown:
        return HIDDEN
    return LOCKED if locked else OPEN


def channel_states(nodes: list) -> dict:
    """{channel: "open" / "locked" / "hidden" — or "mixed" when the objects differ}."""
    found = {}
    for attr in CHANNELS:
        states = {channel_state(node, attr) for node in nodes if _ours(node, attr)}
        found[attr] = states.pop() if len(states) == 1 else (MIXED if states else OPEN)
    return found


def _set_state(node: str, attr: str, state: str) -> bool:
    plug = f"{node}.{attr}"
    try:
        if state == OPEN:
            cmds.setAttr(plug, lock=False)
            cmds.setAttr(plug, keyable=True)
        elif state == LOCKED:
            cmds.setAttr(plug, keyable=True)
            cmds.setAttr(plug, lock=True)
        else:
            cmds.setAttr(plug, lock=True)
            cmds.setAttr(plug, keyable=False)
            cmds.setAttr(plug, channelBox=False)
        return True
    except RuntimeError:
        return False            # a referenced node's locked attribute: not ours to change


def set_channels(nodes: list, attrs, state: str) -> int:
    """The channels put into `state` on every object. One undo step; how many plugs were set."""
    count = 0
    with _Chunk():
        for node in nodes:
            for attr in attrs:
                if _ours(node, attr):
                    count += _set_state(node, attr, state)
    return count


def keep_open(nodes: list, attrs) -> int:
    """Only these channels stay open; the others of the ten are locked and hidden."""
    count = 0
    with _Chunk():
        for node in nodes:
            for attr in CHANNELS:
                if _ours(node, attr):
                    count += _set_state(node, attr, OPEN if attr in attrs else HIDDEN)
    return count


def reset_values(nodes: list, own: bool = True) -> tuple:
    """Move and rotate back to 0, scale to 1, visibility on, and (`own`) each of the objects' own
    attributes to its default. A locked or driven channel is left alone. One undo step;
    (how many were set, how many were left)."""
    done = left = 0
    with _Chunk():
        for node in nodes:
            wanted = {attr: (1.0 if attr in SCALE or attr == "v" else 0.0) for attr in CHANNELS}
            if own:
                for attr in cmds.listAttr(node, userDefined=True, scalar=True) or []:
                    try:
                        wanted[attr] = cmds.attributeQuery(attr, node=node, listDefault=True)[0]
                    except (RuntimeError, TypeError, IndexError):
                        continue
            for attr, value in wanted.items():
                plug = f"{node}.{attr}"
                if not _ours(node, attr):
                    continue
                if cmds.getAttr(plug, lock=True) or cmds.listConnections(plug, source=True, destination=False):
                    left += 1
                    continue
                try:
                    if abs(cmds.getAttr(plug) - value) > 1e-9:
                        cmds.setAttr(plug, value)
                        done += 1
                except (RuntimeError, TypeError):
                    left += 1
    return done, left


def rotate_order(nodes: list) -> str:
    """The objects' rotate order ("" when they differ or none has one)."""
    orders = {ROTATE_ORDERS[cmds.getAttr(node + ".rotateOrder")] for node in nodes
              if cmds.attributeQuery("rotateOrder", node=node, exists=True)}
    return orders.pop() if len(orders) == 1 else ""


def set_rotate_order(nodes: list, order: str) -> int:
    """The rotate order changed WITHOUT turning the object: its rotation is written again in the new
    order (`xform -preserve`). One undo step; how many."""
    count = 0
    with _Chunk():
        for node in nodes:
            if not cmds.attributeQuery("rotateOrder", node=node, exists=True):
                continue
            try:
                cmds.xform(node, preserve=True, rotateOrder=order)
                count += 1
            except RuntimeError:
                continue
    return count


# ------------------------------------------------------------------ the objects' own attributes

def is_separator(node: str, attr: str) -> bool:
    """A separator line: a locked list of one name called sep, sep1, sep2… (what this tool makes)."""
    if not attr.startswith(SEPARATOR_PREFIX):
        return False
    number = attr[len(SEPARATOR_PREFIX):]
    return ((not number or number.isdigit())
            and cmds.attributeQuery(attr, node=node, attributeType=True) == "enum"
            and bool(cmds.getAttr(f"{node}.{attr}", lock=True)))


def describe(node: str, attr: str) -> "dict | None":
    """What an attribute of the object's own is, in plain data: name, nice (as the Channel Box shows
    it), kind (KINDS, or "" for a type this tool doesn't make: text, a compound…), type (Maya's),
    minimum / maximum (None = none), default, names (a list's), keyable, shown, locked, keyed (it
    has keys), driven (something else feeds it), drives (it feeds something), value."""
    if not cmds.attributeQuery(attr, node=node, exists=True):
        return None
    plug = f"{node}.{attr}"
    kind_of = cmds.attributeQuery(attr, node=node, attributeType=True)
    if cmds.attributeQuery(attr, node=node, listParent=True):
        return None                                   # a child of a compound: its parent stands for it
    info = {"name": attr, "nice": cmds.attributeQuery(attr, node=node, niceName=True), "type": kind_of,
            "kind": _KIND_OF.get(kind_of, ""), "minimum": None, "maximum": None, "default": None, "names": [],
            "keyable": False, "shown": False, "locked": False, "driven": False, "drives": False, "keyed": False,
            "value": None}
    try:
        info["keyable"] = bool(cmds.getAttr(plug, keyable=True))
        info["shown"] = info["keyable"] or bool(cmds.getAttr(plug, channelBox=True))
        info["locked"] = bool(cmds.getAttr(plug, lock=True))
        sources = cmds.listConnections(plug, source=True, destination=False) or []
        info["keyed"] = any(cmds.nodeType(source).startswith("animCurve") for source in sources)
        info["driven"] = bool(sources) and not info["keyed"]       # fed by something that is no key
        info["drives"] = bool(cmds.listConnections(plug, source=False, destination=True))
    except (RuntimeError, ValueError):
        pass
    if info["kind"]:
        if cmds.attributeQuery(attr, node=node, minExists=True):
            info["minimum"] = cmds.attributeQuery(attr, node=node, minimum=True)[0]
        if cmds.attributeQuery(attr, node=node, maxExists=True):
            info["maximum"] = cmds.attributeQuery(attr, node=node, maximum=True)[0]
        info["default"] = (cmds.attributeQuery(attr, node=node, listDefault=True) or [0])[0]
        info["value"] = cmds.getAttr(plug)
        if kind_of == "enum":
            info["names"] = (cmds.attributeQuery(attr, node=node, listEnum=True) or [""])[0].split(":")
            if is_separator(node, attr):
                info["kind"] = SEPARATOR
    return info


def own_attributes(node: str) -> list:
    """The object's own attributes, described, in the order the Channel Box lists them (the order
    they were made in)."""
    found = []
    for attr in cmds.listAttr(node, userDefined=True) or []:
        info = describe(node, attr)
        if info is not None:
            found.append(info)
    return found


def summary(info: dict) -> str:
    """One quiet line about an attribute: its kind and range, or its names."""
    kind = info["kind"]
    if kind == SEPARATOR:
        return ""
    if kind == SWITCH:
        return "on / off"
    if kind == LIST:
        return " · ".join(info["names"][:4]) + ("…" if len(info["names"]) > 4 else "")
    if not kind:
        return info["type"]

    def number(value):
        return f"{value:g}"
    low, high = info["minimum"], info["maximum"]
    span = (f"{number(low)}…{number(high)}" if low is not None and high is not None else
            f"from {number(low)}" if low is not None else f"up to {number(high)}" if high is not None else "any")
    return ("whole · " if kind == WHOLE else "") + span


def free_name(node: str, wanted: str) -> str:
    base = "".join(char if char.isalnum() or char == "_" else "_" for char in wanted.strip()) or "attribute"
    if base[0].isdigit():
        base = "_" + base
    name, number = base, 1
    while cmds.attributeQuery(name, node=node, exists=True):
        name, number = f"{base}{number}", number + 1
    return name


def _make(node: str, name: str, kind: str, minimum=None, maximum=None, default=0.0, names=(), nice: str = "",
          keyable: bool = True, shown: bool = True, locked: bool = False) -> None:
    """One attribute made on one node (the name must be free)."""
    if kind == SEPARATOR:
        label = (names[0] if names else "") or " "
        cmds.addAttr(node, longName=name, niceName=nice or "__________", attributeType="enum", enumName=label)
        cmds.setAttr(f"{node}.{name}", channelBox=True)
        cmds.setAttr(f"{node}.{name}", lock=True)
        return
    flags = {"longName": name, "attributeType": _TYPE_OF[kind]}
    if nice:
        flags["niceName"] = nice
    if kind == LIST:
        flags["enumName"] = ":".join(names) or "off:on"
        flags["defaultValue"] = int(default or 0)
    elif kind == SWITCH:
        flags["defaultValue"] = bool(default)
    else:
        value = float(default or 0.0)
        if minimum is not None:
            flags["minValue"] = int(minimum) if kind == WHOLE else float(minimum)
            value = max(value, minimum)
        if maximum is not None:
            flags["maxValue"] = int(maximum) if kind == WHOLE else float(maximum)
            value = min(value, maximum)
        flags["defaultValue"] = int(round(value)) if kind == WHOLE else value
    cmds.addAttr(node, **flags)
    plug = f"{node}.{name}"
    if keyable:
        cmds.setAttr(plug, keyable=True)
    elif shown:
        cmds.setAttr(plug, channelBox=True)
    if locked:
        cmds.setAttr(plug, lock=True)


def add_attribute(nodes: list, name: str, kind: str, minimum=None, maximum=None, default=0.0, names=()) -> tuple:
    """An attribute of this kind on every object that doesn't have one of that name (a separator
    always gets a free name of its own; its `name` is the text it shows). One undo step;
    (the name it got on the first object, how many objects got it, how many had it already)."""
    made, had, first = 0, 0, ""
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    with _Chunk():
        for node in nodes:
            if kind == SEPARATOR:
                attr = free_name(node, SEPARATOR_PREFIX)
                _make(node, attr, kind, names=[name.strip()])
            else:
                attr = "".join(char if char.isalnum() or char == "_" else "_" for char in name.strip())
                if not attr:
                    continue
                if attr[0].isdigit():
                    attr = "_" + attr
                if cmds.attributeQuery(attr, node=node, exists=True):
                    had += 1
                    continue
                _make(node, attr, kind, minimum, maximum, default, names)
            first = first or attr
            made += 1
    return first, made, had


def remove_attributes(nodes: list, names) -> int:
    """These attributes of the objects' own removed (unlocked first). One undo step; how many."""
    count = 0
    with _Chunk():
        for node in nodes:
            own = set(cmds.listAttr(node, userDefined=True) or [])
            for name in names:
                if name not in own:
                    continue
                try:
                    cmds.setAttr(f"{node}.{name}", lock=False)
                    cmds.deleteAttr(node, attribute=name)
                    count += 1
                except RuntimeError:
                    continue
    return count


def set_flags(nodes: list, names, keyable: "bool | None" = None, locked: "bool | None" = None,
              hidden: bool = False) -> int:
    """Keyable (in the Channel Box, can be keyed) / shown only (not keyable) / `hidden` (out of the
    Channel Box) and locked / unlocked for these attributes. One undo step; how many plugs."""
    count = 0
    with _Chunk():
        for node in nodes:
            for name in names:
                if not cmds.attributeQuery(name, node=node, exists=True):
                    continue
                plug = f"{node}.{name}"
                try:
                    if keyable is not None or hidden:
                        was = cmds.getAttr(plug, lock=True)
                        cmds.setAttr(plug, lock=False)
                        cmds.setAttr(plug, keyable=bool(keyable) and not hidden)
                        if hidden or not keyable:
                            cmds.setAttr(plug, channelBox=not hidden)
                        cmds.setAttr(plug, lock=was)
                    if locked is not None:
                        cmds.setAttr(plug, lock=bool(locked))
                    count += 1
                except RuntimeError:
                    continue
    return count


def valid_name(wanted: str) -> str:
    name = "".join(char if char.isalnum() or char == "_" else "_" for char in wanted.strip())
    return ("_" + name) if name and name[0].isdigit() else name


def rename_attribute(nodes: list, old: str, new: str) -> tuple:
    """The attribute called `old` gets the name `new` on every object that has it (its connections,
    keys, value and place in the Channel Box stay). A separator's NAME is the text it shows: that is
    changed instead. One undo step; (the name it has now, how many objects, why not — "" when done)."""
    done, name = 0, valid_name(new)
    with _Chunk():
        for node in nodes:
            if not cmds.attributeQuery(old, node=node, exists=True):
                continue
            plug = f"{node}.{old}"
            if is_separator(node, old):
                cmds.setAttr(plug, lock=False)
                cmds.addAttr(plug, edit=True, enumName=new.strip() or " ")
                cmds.setAttr(plug, lock=True)
                done, name = done + 1, old
                continue
            if not name:
                return old, 0, "a name is letters, digits and _"
            if name == old:
                continue
            if cmds.attributeQuery(name, node=node, exists=True):
                return old, done, f"“{name}” is there already on {node.rpartition('|')[2]}"
            locked = cmds.getAttr(plug, lock=True)
            try:
                cmds.setAttr(plug, lock=False)
                cmds.renameAttr(plug, name)
                if locked:
                    cmds.setAttr(f"{node}.{name}", lock=True)
                done += 1
            except RuntimeError as error:
                return old, done, str(error).strip()
    return name, done, ""


def can_set(node: str, name: str) -> bool:
    plug = f"{node}.{name}"
    if not cmds.attributeQuery(name, node=node, exists=True) or cmds.getAttr(plug, lock=True):
        return False
    return not any(not cmds.nodeType(source).startswith("animCurve")
                   for source in cmds.listConnections(plug, source=True, destination=False) or [])


def get_values(nodes: list, name: str) -> dict:
    """{node: value} of the objects that have the attribute and where it can be set."""
    return {node: cmds.getAttr(f"{node}.{name}") for node in nodes if can_set(node, name)}


def set_value(nodes: list, name: str, value, undoable: bool = True) -> int:
    """The attribute set to `value` on every object that has it — a locked one, or one fed by a
    connection, is left. One undo step; `undoable=False` leaves no trace in the undo queue (the
    in-between values of a drag: the owner sets the final one undoably). How many were set."""
    count = 0
    if not undoable:
        cmds.undoInfo(stateWithoutFlush=False)
    else:
        cmds.undoInfo(openChunk=True, chunkName=UNDO_NAME)
    try:
        for node in nodes:
            if not can_set(node, name):
                continue
            try:
                cmds.setAttr(f"{node}.{name}", value)
                count += 1
            except (RuntimeError, TypeError):
                continue
    finally:
        if not undoable:
            cmds.undoInfo(stateWithoutFlush=True)
        else:
            cmds.undoInfo(closeChunk=True)
    return count


def restore_values(values: dict, name: str) -> None:
    """Values put back as they were, WITHOUT a trace in the undo queue (the start of a drag)."""
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        for node, value in values.items():
            try:
                cmds.setAttr(f"{node}.{name}", value)
            except (RuntimeError, TypeError):
                continue
    finally:
        cmds.undoInfo(stateWithoutFlush=True)


def to_default(nodes: list, names) -> int:
    """These attributes back to their defaults (locked / driven ones left). One undo step."""
    count = 0
    with _Chunk():
        for node in nodes:
            for name in names:
                if not can_set(node, name):
                    continue
                try:
                    cmds.setAttr(f"{node}.{name}", cmds.attributeQuery(name, node=node, listDefault=True)[0])
                    count += 1
                except (RuntimeError, TypeError, IndexError):
                    continue
    return count


def set_key(nodes: list, names) -> int:
    """A key on these attributes at the current time, on every object that has them. One undo step."""
    count = 0
    with _Chunk():
        for node in nodes:
            for name in names:
                if cmds.attributeQuery(name, node=node, exists=True) and not cmds.getAttr(f"{node}.{name}", lock=True):
                    try:
                        count += int(bool(cmds.setKeyframe(node, attribute=name)))
                    except RuntimeError:
                        continue
    return count


def edit_range(nodes: list, name: str, minimum, maximum, default) -> int:
    """The least, the most and the default of a number that exists (None = no limit / leave the
    default). A value outside the new range is brought into it. One undo step — except that Maya
    does not undo a limit being taken OFF. How many objects."""
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    count = 0
    with _Chunk():
        for node in nodes:
            if not cmds.attributeQuery(name, node=node, exists=True):
                continue
            info = describe(node, name)
            if not info or info["kind"] not in (FLOAT, WHOLE):
                continue
            plug = f"{node}.{name}"
            whole = info["kind"] == WHOLE
            locked = cmds.getAttr(plug, lock=True)
            cmds.setAttr(plug, lock=False)
            try:
                def limit(low: bool) -> None:
                    wanted = minimum if low else maximum
                    had = info["minimum"] if low else info["maximum"]
                    if wanted is None:
                        # measured, Maya 2026: taking a limit OFF is not undone by Ctrl+Z (setting one
                        # is) — so it is only done when there is one to take off
                        if had is not None:
                            cmds.addAttr(plug, edit=True, **{"hasMinValue" if low else "hasMaxValue": False})
                    elif wanted != had:
                        cmds.addAttr(plug, edit=True, **{"minValue" if low else "maxValue":
                                                         int(wanted) if whole else float(wanted)})
                # Maya refuses a minimum above the maximum it has: the far limit goes first then
                top_first = (minimum is not None and info["maximum"] is not None and minimum > info["maximum"])
                for low in ((False, True) if top_first else (True, False)):
                    limit(low)
                if default is not None:
                    value = default
                    if minimum is not None:
                        value = max(value, minimum)
                    if maximum is not None:
                        value = min(value, maximum)
                    cmds.addAttr(plug, edit=True, defaultValue=int(round(value)) if whole else float(value))
                if can_set(node, name):
                    now = cmds.getAttr(plug)
                    fitted = now
                    if minimum is not None:
                        fitted = max(fitted, minimum)
                    if maximum is not None:
                        fitted = min(fitted, maximum)
                    if fitted != now:
                        cmds.setAttr(plug, int(round(fitted)) if whole else fitted)
                count += 1
            except RuntimeError:
                pass
            finally:
                if locked:
                    cmds.setAttr(plug, lock=True)
    return count


COPIED = ("name", "kind", "minimum", "maximum", "default", "names", "keyable", "shown", "locked", "value")


def snapshot(node: str, names=None) -> list:
    """The object's own attributes (all, or `names`) as plain data — what a copy holds and a saved
    set keeps (JSON): kind, range, default, names, how it shows, its lock and the value it has now.
    Attributes of a kind this tool doesn't make are left out."""
    return [{key: info[key] for key in COPIED} for info in own_attributes(node)
            if info["kind"] and (names is None or info["name"] in names)]


def paste(nodes: list, infos: list, values: bool = True) -> tuple:
    """The copied attributes made on every object, in their order — one that is there already is
    LEFT as it is (its value, range and connections are not touched), a separator whose text the
    object already shows is not made twice. `values`: the new ones get the copied value (else their
    default). One undo step; (how many were made, on how many objects, how many were there)."""
    made = touched = had = 0
    with _Chunk():
        for node in nodes:
            texts = {(info["names"][0] if info["names"] else "").strip() for info in own_attributes(node)
                     if info["kind"] == SEPARATOR}
            added = 0
            for info in infos:
                kind = info.get("kind")
                if kind not in KINDS:
                    continue
                label = (list(info.get("names") or [""])[0] or "").strip()
                if kind == SEPARATOR:
                    if label in texts:
                        had += 1
                        continue
                    name = free_name(node, SEPARATOR_PREFIX)
                    texts.add(label)
                else:
                    name = valid_name(str(info.get("name", "")))
                    if not name:
                        continue
                    if cmds.attributeQuery(name, node=node, exists=True):
                        had += 1
                        continue
                try:
                    _make(node, name, kind, info.get("minimum"), info.get("maximum"), info.get("default") or 0,
                          list(info.get("names") or []), keyable=bool(info.get("keyable", True)),
                          shown=bool(info.get("shown", True)))
                except (RuntimeError, TypeError, ValueError):
                    continue
                if kind != SEPARATOR:
                    if values and info.get("value") is not None:
                        try:
                            cmds.setAttr(f"{node}.{name}", info["value"])
                        except (RuntimeError, TypeError):
                            pass
                    if info.get("locked"):
                        cmds.setAttr(f"{node}.{name}", lock=True)
                added += 1
            made += added
            touched += bool(added)
    return made, touched, had


def copy_attributes(source: str, targets: list, names=None) -> tuple:
    """The source's own attributes (all, or `names`) made on the other objects too (see `paste`).
    (how many attributes were made, on how many objects)."""
    made, touched, _had = paste([target for target in targets if target != source], snapshot(source, names))
    return made, touched


def reorder(node: str, order: list) -> str:
    """The object's own attributes put in this order in the Channel Box. Maya has no command for it:
    the Channel Box lists attributes in the order they were MADE, so every attribute from the first
    one out of place on is taken off and made again — with its kind, range, default, names, value,
    lock, keyable state and every connection in and out (keys are connections too). An attribute of a
    kind this tool doesn't make (text, a compound, a message) standing among those to be moved makes
    the change impossible: nothing is done and the reason is returned ("" = done). One undo step."""
    current = [info["name"] for info in own_attributes(node)]
    wanted = [name for name in order if name in current] + [name for name in current if name not in order]
    if wanted == current:
        return ""
    # everything from the first one out of place on is made again, in the wanted order …
    first = next(index for index, (a, b) in enumerate(zip(current, wanted)) if a != b)
    moving = wanted[first:]
    described = {name: describe(node, name) for name in moving}
    blocked = [name for name, info in described.items() if not info or not info["kind"]]
    if blocked:
        # … unless one of those can't be made again: then only what MUST move does — the longest
        # start of the wanted order that already stands in that order stays, the rest goes after it
        # (an undo of this one may bring the moved ones back in another order among themselves)
        place, kept_count = 0, 0
        for name in wanted:
            if name in current[place:]:
                place = current.index(name, place) + 1
                kept_count += 1
            else:
                break
        moving = wanted[kept_count:]
        described = {name: describe(node, name) for name in moving}
        blocked = [name for name, info in described.items() if not info or not info["kind"]]
    if blocked:
        return (f"“{blocked[0]}” is of a kind that can't be made again ({(described[blocked[0]] or {}).get('type', '?')})"
                " — it stays where it is, and so does everything after it")
    if cmds.referenceQuery(node, isNodeReferenced=True):
        return "A referenced object's attributes can't be put in another order"
    with _Chunk():
        kept = {}
        # taken off last first: an undo puts deleted attributes back in the reverse of the order they
        # were deleted in, and that must be the order they stood in (measured, Maya 2026)
        for name in sorted(moving, key=current.index, reverse=True):
            plug = f"{node}.{name}"
            sources = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
            targets = cmds.listConnections(plug, source=False, destination=True, plugs=True) or []
            kept[name] = (sources, targets)
            cmds.setAttr(plug, lock=False)
            for source in sources:
                cmds.disconnectAttr(source, plug)
            for target in targets:
                # a locked target can't be disconnected: it is unlocked for the moment
                locked = cmds.getAttr(target, lock=True)
                if locked:
                    cmds.setAttr(target, lock=False)
                cmds.disconnectAttr(plug, target)
                if locked:
                    cmds.setAttr(target, lock=True)
            cmds.deleteAttr(node, attribute=name)
        for name in moving:
            info = described[name]
            nice = info["nice"] if info["kind"] == SEPARATOR else ""
            _make(node, name, info["kind"], info["minimum"], info["maximum"], info["default"], info["names"],
                  nice=nice, keyable=info["keyable"], shown=info["shown"])
            plug = f"{node}.{name}"
            sources, targets = kept[name]
            if info["kind"] != SEPARATOR:
                if not sources and info["value"] is not None:
                    cmds.setAttr(plug, info["value"])
                for source in sources:
                    cmds.connectAttr(source, plug, force=True)
                for target in targets:
                    locked = cmds.getAttr(target, lock=True)
                    if locked:
                        cmds.setAttr(target, lock=False)
                    cmds.connectAttr(plug, target, force=True)
                    if locked:
                        cmds.setAttr(target, lock=True)
                if info["locked"]:
                    cmds.setAttr(plug, lock=True)
    return ""
