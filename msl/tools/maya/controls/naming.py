# tools/maya/controls/naming.py
"""A control's name from what it is made for — no Qt, no Maya. Uses the Rename tool's sides and
kind suffixes, so the two tools name alike: "{side}_{name}_ctrl" for "lf_arm_jnt" standing on the
left is "lf_arm_ctrl"."""
import re

from msl_tools.msl.tools.maya.rename import rules

DEFAULT_TEMPLATE = "{side}_{name}_ctrl"
TOKENS = ("{name}", "{side}", "{#}")
# what a target's name may end with that a control's name shouldn't carry on
EXTRA_ENDS = ("ctrl", "con", "drv", "bind", "joint", "jnt", "JNT", "skin", "zero", "offset")


def base_name(name: str, suffixes: "dict | None" = None) -> str:
    """The name without its namespace, an old side word in front and a kind suffix at the end."""
    name = name.rpartition("|")[2].rpartition(":")[2]
    head, sep, rest = name.partition("_")
    if sep and rest and head.lower() in {side.lower() for side in rules.KNOWN_SIDES}:
        name = rest
    ends = set((suffixes or rules.DEFAULT_TYPE_SUFFIXES).values()) | set(EXTRA_ENDS)
    rest, sep, tail = name.rpartition("_")
    if sep and rest and tail in ends:
        name = rest
    return name or "control"


def control_name(template: str, target: str, position, sides: rules.Sides, index: int = 1,
                 suffixes: "dict | None" = None) -> str:
    """The template filled in: {name} = the target's base name ("control" when there is none),
    {side} = lf / rt / mid from where it stands, {#} = 01, 02… An empty side leaves no "__"."""
    text = (template or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE
    text = text.replace("{name}", base_name(target, suffixes) if target else "control")
    text = text.replace("{side}", sides.text(position) if position is not None else "")
    text = text.replace("{#}", f"{index:02d}")
    text = re.sub(r"_+", "_", text).strip("_")
    return rules.sanitize(text) or "control"
