"""
Declarative description of a Maya main-window menu.

Pure data: no maya.cmds, no Qt, no I/O. Because of that it can be unit-tested
outside Maya and reused by MSL_MayaLauncher.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuAction:
    """A clickable menu item.

    Attributes:
        label: Text shown in the menu.
        target: Dotted path to a zero-argument callable executed on click, e.g.
            "pkg.tools.maya.installer.launcher_entry_point". It is resolved lazily
            at click time, so building the menu never imports the tool itself.
        tooltip: Annotation shown in Maya's help line on hover.
        enabled: When False the item is rendered greyed out.
    """
    label: str
    target: str
    tooltip: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class MenuDivider:
    """A separator line, optionally with a caption.

    Attributes:
        label: Optional caption rendered on the divider.
    """
    label: str = ""


@dataclass(frozen=True)
class SubMenu:
    """A nested menu. Children are owned by the node (a tree), never referenced by label.

    Attributes:
        label: Text shown in the parent menu.
        items: Child entries. Use a tuple to keep the spec truly immutable.
    """
    label: str
    items: tuple["MenuEntry", ...] = ()


MenuEntry = MenuAction | MenuDivider | SubMenu


@dataclass(frozen=True)
class MenuSpec:
    """Root of a menu tree.

    Attributes:
        menu_id: Maya UI object name of the top-level menu. Must be a valid
            identifier (letters, digits, underscore; no spaces).
        label: Text shown in Maya's menu bar.
        items: Top-level entries. Use a tuple to keep the spec truly immutable.
    """
    menu_id: str
    label: str
    items: tuple[MenuEntry, ...] = ()