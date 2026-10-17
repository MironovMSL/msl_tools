# tools/maya/hotkey_set.py
"""Inside Maya: the keys Maya Gate's Hotkeys tab gives our commands, as Maya's hotkey set "MSL".

The user's own set (the one they were on - with animBot's keys and their own) is NEVER changed. At every
start from Maya Gate (MSL_GATE_HOTKEYS present, core/link/hotkey_keys.py) `start()`, run by
hub_link.start(), REBUILDS the set "MSL" as a copy of that BASE set and puts our keys on top of it:
everything the base set does still works, a key of ours wins where both use it. When Maya quits, the base
set is made current again (a quitApplication job) - so Maya started any other way is on the user's own
set, and a key changed in the Hotkey Editor while "MSL" is current is lost at the next start (it belongs
in the base set). The base set is remembered in the optionVar mslHotkeyBaseSet - for a Maya that crashed
while on "MSL".

All measured with Maya 2026 (CLAUDE.md, Hotkeys tab): a copy with -source carries the base's keys;
deleting the current set falls back to Maya_Default; quit(force=True) still saves the sets and the
current one; a real key press right after the start runs the command. mayapy has no hotkey sets at all.

Also what the hub may ask (tools/maya/hub_link.py, FIXED requests, nothing received is run as code):
`state()` - the base set, the current one, what each key does in the base set (for clashes), our keys
now; `apply(keys)` - the same rebuild for a running Maya; `run(name)` - one of OUR commands, by name.

Python 3.9-valid, no Qt; never raises out of start().
"""
from __future__ import annotations

import os

from msl_tools.msl.core.link import hotkey_keys

SET = "MSL"
DEFAULT_SET = "Maya_Default"
BASE_OPTION = "mslHotkeyBaseSet"
_QUIT_JOB = "_msl_hotkey_quit_job"     # kept on maya.cmds: outlives a reload of this module

# every key the state looks at (Maya's own names), with each of the 8 modifier combinations
SCANNED = ([chr(code) for code in range(ord("a"), ord("z") + 1)] + [str(digit) for digit in range(10)]
           + list(hotkey_keys.PUNCTUATION) + list(hotkey_keys.MAYA_NAMES.values()))


def _known() -> dict:
    from msl_tools.msl.tools.maya import hotkey_catalog
    return hotkey_catalog.by_name()


def name_command(name: str) -> str:
    """The nameCommand a key of ours calls: Maya's own convention (the Hotkey Editor makes the same)."""
    return name + "NameCommand"


def start() -> bool:
    """Makes the set MSL for this launch's keys. False when this Maya wasn't started from Maya Gate (nothing is
    touched then) or something failed (said in the Script Editor, Maya's start goes on)."""
    keys = hotkey_keys.from_environment(os.environ)
    if keys is None:
        return False
    try:
        report = apply(keys, hotkey_keys.release_from_environment(os.environ))
        if report["clashes"]:
            print("MSL hotkeys: %d key(s) of ours replace another in the set %s: %s"
                  % (len(report["clashes"]), report["base"],
                     ", ".join("%s (was %s)" % (text, label) for text, label in sorted(report["clashes"].items()))))
        return True
    except Exception as error:
        try:
            import maya.cmds as cmds
            cmds.warning("MSL hotkeys: the set %s could not be made: %s" % (SET, error))
        except Exception:
            pass
        return False


def base_set(cmds) -> str:
    """The user's own set: the current one unless it is ours; else the one remembered; else Maya's default."""
    current = cmds.hotkeySet(query=True, current=True) or DEFAULT_SET
    if current != SET:
        cmds.optionVar(stringValue=(BASE_OPTION, current))
        return current
    remembered = cmds.optionVar(query=BASE_OPTION) if cmds.optionVar(exists=BASE_OPTION) else ""
    if remembered and remembered != SET and cmds.hotkeySet(remembered, query=True, exists=True):
        return remembered
    return DEFAULT_SET


def apply(keys: dict, release=()) -> dict:
    """Rebuilds the set MSL from the base set with `keys` ({command: "Ctrl+Alt+R"}, only our commands) and makes it
    current; no keys = the base set made current and MSL removed. Commands in `release` that are on / off toggles
    run again when their key is let go (releaseName - measured: auto-repeat of a held key doesn't run it again,
    and Alt let go first still counts). Returns {"base", "current", "applied",
    "clashes": {key text: what the base set used it for}, "skipped": [commands not ours / keys Maya can't take]}."""
    import maya.cmds as cmds
    known = _known()
    _register(cmds)
    base = base_set(cmds)
    keys = hotkey_keys.cleaned(keys)
    skipped = [name for name in keys if name not in known]
    keys = {name: text for name, text in keys.items() if name in known}
    cmds.hotkeySet(base, edit=True, current=True)        # never delete the set Maya is on
    if cmds.hotkeySet(SET, query=True, exists=True):
        cmds.hotkeySet(SET, edit=True, delete=True)
    if not keys:
        _watch_quit(cmds)
        return {"base": base, "current": base, "applied": 0, "clashes": {}, "skipped": skipped}
    cmds.hotkeySet(SET, source=base, current=True)
    labels = _labels(cmds)
    clashes, applied = {}, 0
    for name, text in sorted(keys.items()):
        flags = hotkey_keys.to_maya(text)
        if flags is None:
            skipped.append(name)
            continue
        key = flags.pop("keyShortcut")
        before = cmds.hotkey(key, query=True, name=True, **flags) or ""
        if before and before != name_command(name):
            clashes[text] = labels.get(before, before)
        cmds.nameCommand(name_command(name), annotation=name, command=name, sourceType="mel")
        if name in release and known[name].toggle:
            cmds.hotkey(keyShortcut=key, name=name_command(name), releaseName=name_command(name), **flags)
        else:
            cmds.hotkey(keyShortcut=key, name=name_command(name), **flags)
        applied += 1
    _watch_quit(cmds)
    return {"base": base, "current": SET, "applied": applied, "clashes": clashes, "skipped": skipped}


def state() -> dict:
    """{"base", "current", "sets", "ours": {command: key text now in MSL}, "release": [ours that run again when let
    go], "bindings": {key text: {"command",
    "label", "from": "maya" | "set"}}} - the bindings are the BASE set's (what a key of ours would shadow)."""
    import maya.cmds as cmds
    current = cmds.hotkeySet(query=True, current=True) or DEFAULT_SET
    base = base_set(cmds) if current == SET else current
    labels = _labels(cmds)
    ours_by_nc = {name_command(name): name for name in _known()}
    try:
        cmds.hotkeySet(DEFAULT_SET, edit=True, current=True)
        defaults = _scan(cmds)
        cmds.hotkeySet(base, edit=True, current=True)
        in_base = _scan(cmds) if base != DEFAULT_SET else defaults
        mine, released = {}, []
        if cmds.hotkeySet(SET, query=True, exists=True):
            cmds.hotkeySet(SET, edit=True, current=True)
            mine = {ours_by_nc[nc]: text for text, nc in _scan(cmds).items() if nc in ours_by_nc}
            for name, text in mine.items():
                flags = hotkey_keys.to_maya(text)
                key = flags.pop("keyShortcut")
                if cmds.hotkey(key, query=True, releaseName=True, **flags) == name_command(name):
                    released.append(name)
    finally:
        cmds.hotkeySet(current, edit=True, current=True)
    bindings = {}
    for text, nc in in_base.items():
        command = ours_by_nc.get(nc, nc)
        bindings[text] = {"command": command, "label": _label_of(command, nc, labels),
                          "from": "maya" if defaults.get(text) == nc else "set"}
    return {"base": base, "current": current, "sets": list(cmds.hotkeySet(query=True, hotkeySetArray=True) or []),
            "ours": mine, "release": sorted(released), "bindings": bindings}


def run(name: str) -> str:
    """Runs one of OUR commands by name (the hub's "try"); anything else is refused."""
    if name not in _known():
        raise ValueError("not a command of MSL Tools: %s" % name)
    import maya.cmds as cmds
    import maya.mel as mel
    _register(cmds)
    mel.eval(name)
    return name


# --- helpers -------------------------------------------------------------------------------------------

def _register(cmds) -> None:
    """Our runtime commands exist before a key is given to them (bootstrap made them, unless the environment's
    userSetup doesn't call it)."""
    if not all(cmds.runTimeCommand(name, query=True, exists=True) for name in _known()):
        from msl_tools.msl.tools.maya import hotkeys
        hotkeys.register()


def _scan(cmds) -> dict:
    """{key text: nameCommand} of every Global binding of the CURRENT set."""
    found = {}
    for key in SCANNED:
        for ctl in (False, True):
            for alt in (False, True):
                for sht in (False, True):
                    try:
                        nc = cmds.hotkey(key, query=True, name=True, ctl=ctl, alt=alt, sht=sht)
                    except Exception:
                        nc = ""
                    if nc:
                        text = hotkey_keys.from_maya(key, ctl, alt, sht)
                        if text:
                            found[text] = str(nc)
    return found


def _labels(cmds) -> dict:
    """{nameCommand: its annotation} of every named command Maya knows."""
    labels = {}
    try:
        for index in range(1, (cmds.assignCommand(query=True, numElements=True) or 0) + 1):
            name = cmds.assignCommand(index, query=True, name=True)
            if name:
                labels[str(name)] = str(cmds.assignCommand(index, query=True, annotation=True) or "")
    except Exception:
        pass
    return labels


def _label_of(command: str, nc: str, labels: dict) -> str:
    known = _known()
    if command in known:
        return known[command].label
    label = labels.get(nc) or nc
    return label[:-len("NameCommand")] if label.endswith("NameCommand") else label


def _watch_quit(cmds) -> None:
    """When Maya quits, the base set is current again: Maya saves it as the one to start with."""
    old = getattr(cmds, _QUIT_JOB, None)
    if old is not None:
        try:
            if cmds.scriptJob(exists=old):
                cmds.scriptJob(kill=old, force=True)
        except Exception:
            pass
    setattr(cmds, _QUIT_JOB, cmds.scriptJob(event=["quitApplication", _on_quit], protected=True))


def _on_quit() -> None:
    try:
        import maya.cmds as cmds
        if (cmds.hotkeySet(query=True, current=True) or "") == SET:
            cmds.hotkeySet(base_set(cmds), edit=True, current=True)
    except Exception:
        pass
