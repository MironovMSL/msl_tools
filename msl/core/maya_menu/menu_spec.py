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
        icon: Absolute path to a raster icon (png), or None for no icon. Maya's classic
            menu image is drawn from a file path, not a QIcon - resolve it with a plain
            pathlib lookup (see menu_definition.py's `_icon()`), never through the Qt
            IconManager. Pulling that in here would mean importing PySide6 just to build
            the main menu, which is exactly the slow-startup cost this module avoids.
    """
    label:   str
    target:  str
    tooltip: str        = ""
    enabled: bool       = True
    icon:    str | None = None


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
        icon: Absolute path to a raster icon (png), or None for no icon. See MenuAction.icon.
        tear_off: Lets the user drag this submenu off into its own floating window, same as
            the root menu already does. True by default - there's no real downside to it for
            a submenu, and it's the more discoverable default for anyone new to the menu.
    """
    label:    str
    items:    tuple["MenuEntry", ...] = ()
    icon:     str | None              = None
    tear_off: bool                    = True


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
    label:   str
    items:   tuple[MenuEntry, ...] = ()