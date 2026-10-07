# tools/maya/rename/rules.py
"""What a rename DOES to names — no Qt, no Maya.

Everything works on `Node`s (what the tool needs to know of a scene object) and returns new short
names, so the window can show "before -> after" for every object before anything is renamed, and
the tests need no Maya. scene.py reads the Nodes from Maya and applies the result.

A name here is always the SHORT name WITHOUT its namespace: "ns:arm_L" is namespace "ns:" + name
"arm_L". The namespace is kept as it is unless the user asks to drop it.

The template (the rename field) takes tokens:
    {name}   the object's current name           {#}    the number (start / step / padding)
    {A} {a}  a letter: A, B ... Z, AA, AB ...     {side} lf / rt / mid from where it stands
    {type}   the suffix of its kind (geo, jnt ...)
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

TOKENS = ("{name}", "{#}", "{A}", "{a}", "{side}", "{type}")
TOKEN_HELP = {"{name}": "the object's current name", "{#}": "a number: start, step and digits are set below",
              "{A}": "a letter: A, B, C ... Z, AA", "{a}": "a small letter: a, b, c",
              "{side}": "lf / rt / mid — from where the object stands", "{type}": "a suffix from its kind: geo, jnt, grp"}
_TOKEN = re.compile(r"\{[^{}]*\}")
_VALID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# The order objects are numbered in.
ORDER_SELECTION = "Selection"
ORDER_NAME = "Name"
ORDER_X, ORDER_Y, ORDER_Z = "Position X", "Position Y", "Position Z"
ORDER_CHAINS = "Chains"   # numbers restart in each chain (parent -> child), letters count the chains
ORDERS = (ORDER_SELECTION, ORDER_CHAINS, ORDER_NAME, ORDER_X, ORDER_Y, ORDER_Z)

LEFT, RIGHT, CENTER = "left", "right", "center"
MIRROR_AXES = ("X", "Y", "Z")
DEFAULT_SIDES = {LEFT: "lf", RIGHT: "rt", CENTER: "mid"}
# What a name may start with that already says its side (taken off before a new side goes on).
KNOWN_SIDES = ("lf", "rt", "mid", "l", "r", "c", "left", "right", "center", "ctr", "lft", "rgt")

# Suffix by kind: the shape's type for a transform that has one, else the node's own type.
DEFAULT_TYPE_SUFFIXES = {
    "transform": "grp", "mesh": "geo", "joint": "jnt", "nurbsCurve": "crv", "nurbsSurface": "srf",
    "locator": "loc", "camera": "cam", "ikHandle": "ikh", "clusterHandle": "cls", "lattice": "lat",
    "follicle": "fol", "directionalLight": "lgt", "pointLight": "lgt", "spotLight": "lgt",
    "areaLight": "lgt", "ambientLight": "lgt", "volumeLight": "lgt",
    "parentConstraint": "parCon", "pointConstraint": "pntCon", "orientConstraint": "oriCon",
    "scaleConstraint": "sclCon", "aimConstraint": "aimCon", "poleVectorConstraint": "pvCon",
}


@dataclass
class Node:
    """A scene object as the rules see it."""
    path: str                      # the long name (scene.py's handle: a uuid there)
    name: str                      # short name without namespace
    namespace: str = ""            # "ns:" / "a:b:" / ""
    type: str = "transform"        # the node's type
    shape_type: str = ""           # the first shape's type ("" = none)
    position: tuple = (0.0, 0.0, 0.0)
    locked: str = ""               # why it can't be renamed ("" = it can): referenced, locked, read-only
    uuid: str = ""
    siblings: tuple = ()           # names of the other objects under the same parent

    @property
    def kind(self) -> str:
        """What the object IS for a suffix: its shape's type if it has one."""
        return self.shape_type or self.type


@dataclass
class Numbering:
    start: int = 1
    step: int = 1
    padding: int = 2
    order: str = ORDER_SELECTION
    end_last: bool = False        # Chains: the last link of a chain gets "end" instead of its number


@dataclass
class Sides:
    axis: str = "X"
    tolerance: float = 0.001
    prefixes: dict = field(default_factory=lambda: dict(DEFAULT_SIDES))
    separator: str = "_"

    def of(self, position) -> str:
        """LEFT / RIGHT / CENTER of a position: + on the mirror axis is the object's left (Maya's
        convention: a character faces +Z, its left arm is at +X)."""
        value = position[MIRROR_AXES.index(self.axis)] if self.axis in MIRROR_AXES else position[0]
        if abs(value) <= self.tolerance:
            return CENTER
        return LEFT if value > 0 else RIGHT

    def text(self, position) -> str:
        return self.prefixes.get(self.of(position), "")

    @classmethod
    def from_settings(cls, saved) -> "Sides":
        """From the tool's stored settings ({axis, tolerance, left, right, center}); anything
        missing or unreadable falls back to the defaults."""
        saved = dict(saved or {})
        prefixes = {side: str(saved.get(side, DEFAULT_SIDES[side])) for side in DEFAULT_SIDES}
        try:
            tolerance = float(saved.get("tolerance", 0.001))
        except (TypeError, ValueError):
            tolerance = 0.001
        axis = saved.get("axis", "X")
        return cls(axis=axis if axis in MIRROR_AXES else "X", tolerance=tolerance, prefixes=prefixes)


# ---------------------------------------------------------------------------- tokens and the template

def letters(index: int, upper: bool = True) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, 27 -> AB (as spreadsheet columns)."""
    index = max(0, int(index))
    text = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        text = chr(65 + rest) + text
    return text if upper else text.lower()


def number_text(value: int, padding: int) -> str:
    sign = "-" if value < 0 else ""
    return sign + str(abs(value)).zfill(max(1, int(padding)))


def unknown_tokens(template: str) -> list[str]:
    return [token for token in _TOKEN.findall(template) if token not in TOKENS]


def uses_number(template: str) -> bool:
    return "{#}" in template or "{A}" in template or "{a}" in template


def order_nodes(nodes: list[Node], order: str) -> list[int]:
    """The indexes of `nodes` in the order they get their numbers."""
    indexes = list(range(len(nodes)))
    if order == ORDER_NAME:
        return sorted(indexes, key=lambda index: natural_key(nodes[index].name))
    if order in (ORDER_X, ORDER_Y, ORDER_Z):
        axis = (ORDER_X, ORDER_Y, ORDER_Z).index(order)
        return sorted(indexes, key=lambda index: nodes[index].position[axis])
    return indexes


def natural_key(text: str):
    """"arm2" before "arm10"."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def chains(nodes: list[Node]) -> list[list[int]]:
    """The nodes as chains (indexes): a node whose parent is listed too — and is that parent's only
    listed child — continues the parent's chain; any other starts one. Chains come in the order
    their first-selected link was selected; inside a chain, from the root down."""
    index_of = {node.path: index for index, node in enumerate(nodes)}
    children: dict = {}
    for index, node in enumerate(nodes):
        parent = node.path.rpartition("|")[0]
        if parent in index_of:
            children.setdefault(index_of[parent], []).append(index)
    continues = {kids[0] for kids in children.values() if len(kids) == 1}
    result = []
    for index in range(len(nodes)):
        if index in continues:
            continue
        chain = [index]
        while True:
            kids = children.get(chain[-1], [])
            if len(kids) != 1:
                break
            chain.append(kids[0])
        result.append(chain)
    result.sort(key=min)
    return result


def expand(template: str, node: Node, position: int, numbering: Numbering, sides: Sides,
           suffixes: dict, letter: "int | None" = None, last: bool = False) -> str:
    """The new name of `node` from the template; `position` = its place in the numbering order,
    `letter` = which letter it gets (default: the same place), `last` = the end of a chain."""
    value = numbering.start + position * numbering.step
    letter = position if letter is None else letter
    side = sides.text(node.position)
    kind = suffixes.get(node.kind, "")
    number = "end" if last and numbering.end_last else number_text(value, numbering.padding)
    replacements = {"{name}": node.name, "{#}": number,
                    "{A}": letters(letter), "{a}": letters(letter, upper=False),
                    "{side}": side, "{type}": kind}
    text = _TOKEN.sub(lambda match: replacements.get(match.group(0), match.group(0)), template)
    return tidy(text)


def tidy(name: str) -> str:
    """What an empty token leaves behind: "__" -> "_", no "_" at either end (unless the user's own
    text is nothing but that)."""
    text = re.sub(r"_{2,}", "_", name)
    stripped = text.strip("_")
    return stripped or text


def from_template(nodes: list[Node], template: str, numbering: Numbering, sides: Sides,
                  suffixes: dict) -> list[str]:
    """Every node's new name from the template (in the nodes' own order)."""
    template = template.replace(" ", "_")
    result = [""] * len(nodes)
    if numbering.order == ORDER_CHAINS:
        for letter, chain in enumerate(chains(nodes)):
            for position, index in enumerate(chain):
                last = len(chain) > 1 and position == len(chain) - 1
                result[index] = expand(template, nodes[index], position, numbering, sides, suffixes, letter, last)
        return result
    for position, index in enumerate(order_nodes(nodes, numbering.order)):
        result[index] = expand(template, nodes[index], position, numbering, sides, suffixes)
    return result


# ---------------------------------------------------------------------------- one-name operations

def name_parts(old: str, new: str) -> list:
    """The new name cut into (text, changed) pieces against the old one: what stays as it was, what
    is new or replaced ("lf_arm_jnt" -> "lf_leg_jnt": [("lf_", False), ("leg", True), ("_jnt", False)]).
    A name that changed nearly all through is one changed piece, and a single letter that happens to
    match inside a change counts as changed — chance matches only made it read speckled."""
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    if not new or matcher.ratio() < 0.5:
        return [(new, True)] if new else []
    parts = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if j2 <= j1:
            continue
        changed = tag != "equal" or (j2 - j1 < 2 and 0 < j1 and j2 < len(new))
        if parts and parts[-1][1] == changed:
            parts[-1] = (parts[-1][0] + new[j1:j2], changed)
        else:
            parts.append((new[j1:j2], changed))
    return parts


def capitalize(name: str) -> str:
    """"arm" -> "Arm", "armIK" -> "ArmIK" (the rest stays), "ARM" -> "Arm" (an all-caps name isn't
    kept shouting)."""
    if not name:
        return name
    rest = name[1:].lower() if name.isupper() else name[1:]
    return name[0].upper() + rest


def camel_to_snake(name: str) -> str:
    """"leftArmIK" -> "left_arm_ik"."""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return tidy(text.lower())


def snake_to_camel(name: str) -> str:
    """"left_arm_ik" -> "leftArmIk"."""
    parts = [part for part in name.split("_") if part]
    if not parts:
        return name
    return parts[0][:1].lower() + parts[0][1:] + "".join(capitalize(part.lower()) for part in parts[1:])


def remove_prefix(name: str) -> str:
    """Drops the first "_" part: "lf_arm_jnt" -> "arm_jnt" (a name of one part stays)."""
    head, sep, rest = name.partition("_")
    return rest if sep and rest.strip("_") else name


def remove_suffix(name: str) -> str:
    """Drops the last "_" part: "arm_jnt" -> "arm"."""
    rest, sep, _tail = name.rpartition("_")
    return rest if sep and rest.strip("_") else name


def remove_end_number(name: str) -> str:
    """"arm_01" / "arm01" -> "arm"."""
    text = re.sub(r"_?\d+$", "", name)
    return text if text.strip("_") else name


def remove_digits(name: str) -> str:
    """Every digit out: "arm_01_jnt2" -> "arm_jnt"."""
    text = tidy(re.sub(r"\d", "", name))
    return text if text.strip("_") else name


def remove_first(name: str, count: int = 1) -> str:
    return name[count:] if len(name) > count else name


def remove_last(name: str, count: int = 1) -> str:
    return name[:-count] if len(name) > count else name


def add_prefix(name: str, prefix: str) -> str:
    return name if not prefix or name.startswith(prefix) else prefix + name


def add_suffix(name: str, suffix: str) -> str:
    return name if not suffix or name.endswith(suffix) else name + suffix


def add_word(name: str, word: str, separator: bool = True) -> str:
    """A library word at the end: "arm" + "jnt" -> "arm_jnt" (`separator` False: "armjnt").
    Not twice."""
    if not word:
        return name
    piece = ("_" + word.lstrip("_")) if separator and not word.startswith("_") and name else word
    return name if name.endswith(piece) else tidy(name + piece) if separator else name + piece


def side_prefix(name: str, position, sides: Sides) -> str:
    """lf_ / rt_ / mid_ from where it stands — an old side prefix is taken off first."""
    known = {text.lower() for text in KNOWN_SIDES} | {text.lower() for text in sides.prefixes.values() if text}
    head, sep, rest = name.partition("_")
    if sep and head.lower() in known and rest:
        name = rest
    side = sides.text(position)
    return f"{side}{sides.separator}{name}" if side else name


def type_suffix(name: str, kind: str, suffixes: dict) -> str:
    """The suffix of its kind at the end; a suffix of ANOTHER kind there is replaced
    ("arm_grp" of a mesh -> "arm_geo")."""
    suffix = suffixes.get(kind, "")
    if not suffix:
        return name
    rest, sep, tail = name.rpartition("_")
    if sep and rest and tail != suffix and tail in set(suffixes.values()):
        name = rest
    return name if name.endswith("_" + suffix) or name == suffix else f"{name}_{suffix}"


SIDE_PAIRS = (("lf", "rt"), ("l", "r"), ("left", "right"), ("lft", "rgt"))


def _same_case(word: str, model: str) -> str:
    if model.isupper():
        return word.upper()
    if model[:1].isupper():
        return word[:1].upper() + word[1:].lower()
    return word.lower()


def mirror(name: str, sides: "Sides | None" = None) -> str:
    """The name of the same thing on the other side: lf_arm -> rt_arm, arm_L -> arm_R,
    leftArm -> rightArm (case kept). Whole "_" parts are swapped; a name without such a part gets
    a camelCase Left / Right swapped. A name with no side stays as it is."""
    pairs = list(SIDE_PAIRS)
    if sides is not None:
        left, right = sides.prefixes.get(LEFT, ""), sides.prefixes.get(RIGHT, "")
        if left and right:
            pairs.insert(0, (left.lower(), right.lower()))
    swap = {}
    for one, other in pairs:
        swap.setdefault(one, other)
        swap.setdefault(other, one)
    parts = name.split("_")
    changed = False
    for index, part in enumerate(parts):
        other = swap.get(part.lower())
        if other is not None:
            parts[index] = _same_case(other, part)
            changed = True
    if changed:
        return "_".join(parts)
    # camelCase: "leftArm", "armLeft", "LeftArm"
    pattern = r"(?:^(left|right|Left|Right)(?=[A-Z0-9]|$))|(?:(?<=[a-z0-9])(Left|Right)(?=[A-Z0-9]|$))"
    return re.sub(pattern, lambda match: _same_case(swap[(match.group(1) or match.group(2)).lower()],
                                                    match.group(1) or match.group(2)), name)


def shape_name(transform: str, index: int = 0) -> str:
    """What a transform's shape should be called: armShape, the second one armShape1 (Maya's way)."""
    return f"{transform}Shape" + (str(index) if index else "")


def replace(name: str, find: str, new: str, case: bool = True, regex: bool = False) -> str:
    """Every occurrence of `find` -> `new` (an empty `new` takes it out). `regex`: a Python regular
    expression (groups as \\1). Raises ValueError on a broken expression."""
    if not find:
        return name
    flags = 0 if case else re.IGNORECASE
    try:
        pattern = re.compile(find if regex else re.escape(find), flags)
    except re.error as error:
        raise ValueError(f"The expression doesn't read: {error}") from None
    return pattern.sub(new if regex else new.replace("\\", "\\\\"), name)


def matches(name: str, find: str, case: bool = True, regex: bool = False) -> bool:
    if not find:
        return False
    try:
        return re.search(find if regex else re.escape(find), name, 0 if case else re.IGNORECASE) is not None
    except re.error:
        return False


# ---------------------------------------------------------------------------- checks

_CYRILLIC = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
             "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
             "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
             "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}


def transliterate(text: str) -> str:
    out = []
    for char in text:
        latin = _CYRILLIC.get(char.lower())
        if latin is None:
            out.append(char)
        else:
            out.append(latin.capitalize() if char.isupper() and latin else latin)
    return "".join(out)


def sanitize(name: str) -> str:
    """A name Maya takes: Cyrillic spelled in Latin, anything else that isn't a letter, digit or
    "_" -> "_", no "__", not starting with a digit."""
    text = transliterate(name)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = tidy(text) if text.strip("_") else "_"
    if text[:1].isdigit():
        text = "_" + text
    return text


def problem(name: str) -> str:
    """Why Maya would refuse or change `name` ("" = fine)."""
    if not name:
        return "empty name"
    if re.search(r"[А-Яа-яЁё]", name):
        return "Cyrillic letters"
    if " " in name:
        return "a space"
    if name[0].isdigit():
        return "starts with a digit"
    if not _VALID.match(name):
        bad = sorted({char for char in name if not (char.isalnum() or char == "_")})
        return "not allowed: " + " ".join(bad)
    return ""


def notice(name: str) -> str:
    """Not wrong, but worth a look ("" = nothing)."""
    if "__" in name:
        return "double underscore"
    if name.endswith("_") or name.startswith("_"):
        return "underscore at an end"
    return ""


def duplicates(names: list[str]) -> set[str]:
    """Short names that occur more than once (case as Maya: exact)."""
    seen, twice = set(), set()
    for name in names:
        (twice if name in seen else seen).add(name)
    return twice


@dataclass
class Change:
    """One line of "before -> after"."""
    node: Node
    new: str
    state: str = ""     # "" fine / "same" unchanged / "locked" / "error" / "clash" / "warning"
    note: str = ""

    @property
    def changes(self) -> bool:
        return self.state not in ("same", "locked", "error", "idle", "nonconform", "skipped")


def plan(nodes: list[Node], new_names: list[str], drop_namespace: bool = False) -> list[Change]:
    """`new_names` checked: what can't be renamed, what Maya would refuse, two objects that would
    get one name under one parent (Maya would number the second — "clash"), what stays as it is."""
    changes = []
    for node, new in zip(nodes, new_names):
        new = new.strip()
        if node.locked:
            changes.append(Change(node, node.name, "locked", node.locked))
            continue
        if new == node.name and not (drop_namespace and node.namespace):
            changes.append(Change(node, new, "same"))
            continue
        reason = problem(new)
        if reason:
            changes.append(Change(node, new, "error", reason))
            continue
        changes.append(Change(node, new, "warning" if notice(new) else "", notice(new)))
    # one name twice under ONE parent: Maya numbers the later one; under different parents it's legal
    by_parent: dict = {}
    for change in changes:
        if change.changes:
            parent = change.node.path.rpartition("|")[0]
            by_parent.setdefault((parent, change.node.namespace if not drop_namespace else "", change.new), []).append(change)
    for group in by_parent.values():
        if len(group) > 1:
            for change in group[1:]:
                change.state, change.note = "clash", "same name under the same parent — Maya adds a number"
    # a name an object that STAYS already has under that parent
    leaving = {(change.node.path.rpartition("|")[0], change.node.name) for change in changes if change.changes}
    for change in changes:
        if change.state in ("", "warning") and change.new in change.node.siblings:
            parent = change.node.path.rpartition("|")[0]
            if (parent, change.new) not in leaving:
                change.state, change.note = "clash", f"“{change.new}” is taken under the same parent — Maya adds a number"
    return changes


# ---------------------------------------------------------------------------- a naming convention

def _convention_regex(pattern: str, sides: Sides, suffixes: dict):
    side_words = sorted({text for text in sides.prefixes.values() if text}, key=len, reverse=True)
    type_words = sorted({text for text in suffixes.values() if text}, key=len, reverse=True)
    pieces, used = [], set()
    position = 0
    for match in _TOKEN.finditer(pattern):
        pieces.append(re.escape(pattern[position:match.start()]))
        token = match.group(0)
        if token in ("{side}", "{type}"):
            key = token.strip("{}")
            words = side_words if key == "side" else type_words
            body = "|".join(map(re.escape, words)) or "(?!)"
            pieces.append(f"(?P<{key}>{body})" if key not in used else f"(?:{body})")
            used.add(key)
        elif token == "{#}":
            pieces.append(r"(?:\d+|end)")
        elif token == "{A}":
            pieces.append("[A-Z]+")
        elif token == "{a}":
            pieces.append("[a-z]+")
        elif token == "{name}":
            pieces.append(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?")
        else:
            pieces.append(re.escape(token))
        position = match.end()
    pieces.append(re.escape(pattern[position:]))
    return re.compile("".join(pieces))


_WHERE = {LEFT: "on the left", RIGHT: "on the right", CENTER: "in the middle"}


def convention_problem(node: Node, pattern: str, sides: Sides, suffixes: dict) -> str:
    """Why `node`'s name doesn't follow the convention `pattern` (a template: "{side}_{name}_{type}")
    — "" = it does. Beyond the shape of the name: a side that isn't where the object stands, a
    suffix that isn't its kind's."""
    if not pattern.strip():
        return ""
    match = _convention_regex(pattern.strip(), sides, suffixes).fullmatch(node.name)
    if match is None:
        return f"isn't {pattern.strip()}"
    groups = match.groupdict()
    if groups.get("side"):
        expected = sides.text(node.position)
        if expected and groups["side"] != expected:
            return f"says {groups['side']}, stands {_WHERE[sides.of(node.position)]}"
    if groups.get("type"):
        expected = suffixes.get(node.kind, "")
        if expected and groups["type"] != expected:
            return f"ends with {groups['type']}, a {node.kind} gets {expected}"
    return ""
