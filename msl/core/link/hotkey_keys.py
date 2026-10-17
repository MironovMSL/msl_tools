# core/link/hotkey_keys.py
"""Keyboard shortcuts as text, for Maya Gate's Hotkeys tab and for Maya: "Ctrl+Alt+R" <-> what
`cmds.hotkey` takes (keyShortcut + ctl / alt / sht), the launch variable that carries an
environment's keys (MSL_GATE_HOTKEYS) and the file a set of keys is exported to.

A key's text: the modifiers in the order Ctrl, Alt, Shift, then ONE key - a letter (upper case),
a digit, F1..F12, a named key (Up, PageUp, Enter, Space...) or a sign of PUNCTUATION.
`normalize()` takes any order / case / spelling Maya or a person uses and gives that text; "" for
anything else.

Measured with Maya 2026 (see CLAUDE.md, Hotkeys tab): `sht` works for letters and other keys alike
("k" + sht + ctl is the binding "K" + ctl), and Maya ACCEPTS loose names silently ("PageUp",
"Enter") - so only Maya's own names (MAYA_NAMES) are ever handed to it.

No Qt, no Maya, Python 3.9-valid: both sides import it.
"""
from __future__ import annotations

import json

from msl_tools.msl.core.link import variables

MODIFIERS = ("Ctrl", "Alt", "Shift")
# our name -> Maya's keyShortcut
MAYA_NAMES = {"Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right", "Home": "Home", "End": "End",
              "PageUp": "Page_Up", "PageDown": "Page_Down", "Insert": "Insert", "Delete": "Delete",
              "Enter": "Return", "Space": "Space", "Tab": "Tab", "Backspace": "Backspace"}
MAYA_NAMES.update({"F%d" % number: "F%d" % number for number in range(1, 13)})
PUNCTUATION = "`-=[]\\;',./"
# other spellings that mean one of ours (lower case)
_ALIASES = {"control": "Ctrl", "ctl": "Ctrl", "ctrl": "Ctrl", "alt": "Alt", "option": "Alt", "shift": "Shift",
            "sht": "Shift", "return": "Enter", "page_up": "PageUp", "pgup": "PageUp", "page_down": "PageDown",
            "pgdown": "PageDown", "pgdn": "PageDown", "del": "Delete", "ins": "Insert", "spacebar": "Space",
            "back": "Backspace", "backspace": "Backspace"}
_BY_LOWER = {name.lower(): name for name in MAYA_NAMES}
_FROM_MAYA = {maya: ours for ours, maya in MAYA_NAMES.items()}

FILE_FORMAT = "msl_hotkeys"
FILE_VERSION = 1


def _key_name(text: str) -> str:
    """One key's canonical name, or ""."""
    if len(text) == 1:
        if text.isalpha() and text.isascii():
            return text.upper()
        if text.isdigit() or text in PUNCTUATION:
            return text
        return ""
    lower = text.lower()
    alias = _ALIASES.get(lower)
    if alias and alias not in MODIFIERS:
        return alias
    return _BY_LOWER.get(lower, _FROM_MAYA.get(text, ""))


def parse(text) -> tuple | None:
    """("Ctrl" / "Alt" / "Shift" present as a set, the key) or None when `text` is no shortcut."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    if text.endswith("++"):          # "Ctrl++": not a key of ours (it is Shift+= on most keyboards)
        return None
    parts = [part.strip() for part in text.split("+")]
    if any(not part for part in parts):
        return None
    *modifier_parts, key_part = parts
    modifiers = set()
    for part in modifier_parts:
        modifier = _ALIASES.get(part.lower())
        if modifier not in MODIFIERS or modifier in modifiers:
            return None
        modifiers.add(modifier)
    key = _key_name(key_part)
    if not key:
        return None
    return frozenset(modifiers), key


def compose(modifiers, key: str) -> str:
    """The canonical text of `modifiers` (any of MODIFIERS) + `key` ("" when the key is none of ours)."""
    key = _key_name(key)
    if not key:
        return ""
    return "+".join([modifier for modifier in MODIFIERS if modifier in modifiers] + [key])


def normalize(text) -> str:
    """"alt+ctrl+r" -> "Ctrl+Alt+R"; "" when it is no shortcut."""
    parsed = parse(text)
    return compose(*parsed) if parsed else ""


def parts(text) -> list:
    """The caps to draw: ["Ctrl", "Alt", "R"] ([] for no shortcut)."""
    normalized = normalize(text)
    return normalized.split("+") if normalized else []


def has_modifier(text) -> bool:
    parsed = parse(text)
    return bool(parsed and parsed[0] & {"Ctrl", "Alt"})


def to_maya(text) -> dict | None:
    """The flags of `cmds.hotkey` / `cmds.hotkey(q=True)`: {"keyShortcut", "ctl", "alt", "sht"}. A letter is
    always given in lower case with `sht` for Shift (measured: the same binding as the upper-case letter)."""
    parsed = parse(text)
    if not parsed:
        return None
    modifiers, key = parsed
    return {"keyShortcut": MAYA_NAMES.get(key, key.lower() if key.isalpha() else key),
            "ctl": "Ctrl" in modifiers, "alt": "Alt" in modifiers, "sht": "Shift" in modifiers}


def from_maya(key_shortcut: str, ctl: bool = False, alt: bool = False, sht: bool = False) -> str:
    """The text of a binding as Maya keeps it; an upper-case letter is Shift + that letter."""
    key = str(key_shortcut or "")
    if len(key) == 1 and key.isalpha() and key.isupper():
        sht = True
    modifiers = {name for name, on in (("Ctrl", ctl), ("Alt", alt), ("Shift", sht)) if on}
    return compose(modifiers, _FROM_MAYA.get(key, key))


def cleaned(keys, known=None) -> dict:
    """{command: key text} with every key normalized; unknown commands (when `known` names them) and texts
    that are no shortcut are left out."""
    result = {}
    if not isinstance(keys, dict):
        return result
    for name, text in keys.items():
        name = str(name)
        if known is not None and name not in known:
            continue
        normalized = normalize(text)
        if normalized:
            result[name] = normalized
    return result


def clashes(keys: dict) -> dict:
    """{key text: [commands]} for keys given to more than one command."""
    users = {}
    for name, text in keys.items():
        normalized = normalize(text)
        if normalized:
            users.setdefault(normalized, []).append(name)
    return {text: sorted(names) for text, names in users.items() if len(names) > 1}


def copied(source: dict, target: dict, names=None, replace: bool = True) -> tuple:
    """`target` with `source`'s keys of `names` (all when None) copied in. A key another command of the
    target already has is taken from that one (replace=True) or not copied (replace=False).
    Returns (the new target, [commands copied], [commands skipped])."""
    result = cleaned(target)
    copied_names, skipped = [], []
    for name, text in cleaned(source).items():
        if names is not None and name not in names:
            continue
        holders = [other for other, other_text in result.items() if other_text == text and other != name]
        if holders and not replace:
            skipped.append(name)
            continue
        for other in holders:
            del result[other]
        result[name] = text
        copied_names.append(name)
    return result, copied_names, skipped


# the combinations free keys are looked for in, in this order (Maya keeps most bare and Shift keys for itself)
FREE_MODIFIERS = (("Ctrl", "Alt"), ("Alt", "Shift"), ("Ctrl", "Shift"), ("Ctrl", "Alt", "Shift"))


def free_keys(label: str, taken, limit: int = 12) -> list:
    """Keys nobody uses, for a command named `label`: its words' first letters first ("Rename window" -> R, W),
    then its other letters, then the rest of the alphabet and the digits; per key the first free combination of
    FREE_MODIFIERS - one suggestion per key, so the list reads as different keys. `taken`: key texts in use."""
    taken = {normalize(text) for text in taken}
    words = [word for word in "".join(ch if ch.isalnum() else " " for ch in label.upper()).split() if word]
    order = []
    for letter in [word[0] for word in words] + list("".join(words)) + [chr(code) for code in range(65, 91)]             + [str(digit) for digit in range(1, 10)] + ["0"]:
        if letter.isascii() and letter.isalnum() and letter not in order:
            order.append(letter)
    found = []
    for key in order:
        for modifiers in FREE_MODIFIERS:
            text = compose(modifiers, key)
            if text and text not in taken:
                found.append(text)
                break
        if len(found) >= limit:
            break
    return found


# --- the launch ---------------------------------------------------------------------------------------

def to_environment(keys: dict, release=()) -> dict:
    """The launch's variables: the keys ALWAYS (an empty set too - its presence is what tells Maya to keep the
    hotkey set "MSL", tools/maya/hotkey_set.py), and the commands that run again when their key is let go."""
    keys = cleaned(keys)
    launch = {variables.HOTKEYS: json.dumps(keys, sort_keys=True, separators=(",", ":"))}
    released = sorted(name for name in release if name in keys)
    if released:
        launch[variables.HOTKEYS_RELEASE] = ",".join(released)
    return launch


def release_from_environment(environ) -> set:
    """The commands a launch says run again on their key's release."""
    return {name for name in str(environ.get(variables.HOTKEYS_RELEASE) or "").split(",") if name}


def from_environment(environ) -> dict | None:
    """The keys a launch carries, or None when it carries none (not started from Maya Gate)."""
    raw = environ.get(variables.HOTKEYS)
    if raw is None:
        return None
    try:
        return cleaned(json.loads(raw))
    except ValueError:
        return {}


# --- a file of keys -------------------------------------------------------------------------------------

def export_data(keys: dict, environment: str = "", release=()) -> dict:
    keys = cleaned(keys)
    return {"format": FILE_FORMAT, "version": FILE_VERSION, "environment": environment, "keys": keys,
            "release": sorted(name for name in release if name in keys)}


def import_release(data, known=None) -> set:
    """The release commands of an exported file's data (a file from before they existed: none)."""
    names = data.get("release") if isinstance(data, dict) else None
    return {str(name) for name in (names if isinstance(names, list) else [])
            if known is None or str(name) in known}


def import_data(data, known=None) -> dict:
    """The keys of an exported file's data; ValueError for data that is no file of ours."""
    if not isinstance(data, dict) or data.get("format") != FILE_FORMAT or not isinstance(data.get("keys"), dict):
        raise ValueError("this is not a file of MSL hotkeys")
    return cleaned(data["keys"], known)
