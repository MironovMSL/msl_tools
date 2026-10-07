"""
Content of the MSL main menu: which entries exist and what they run.

Pure data (a MenuSpec). Nothing here imports the tools themselves - entries only reference
them by dotted path, so building the menu stays fast and never breaks on a broken tool.
"""

from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.maya_menu import MenuAction, MenuDivider, MenuSpec, SubMenu


class MslMenuDefinition:
    """Builds the MenuSpec of the MSL main menu."""

    MENU_ID    = "MSLToolsMenu"
    MENU_LABEL = "MSL"

    _TOOLS_PACKAGE = __package__
    _ROOT_PACKAGE  = FileSystemManager.PACKAGE_ROOT
    _ICON_DIR      = FileSystemManager.icons / "menu"

    @classmethod
    def build(cls) -> MenuSpec:
        """Returns the current menu description."""
        return MenuSpec(
            menu_id=cls.MENU_ID,
            label=cls.MENU_LABEL,
            items=(
                MenuAction("Playblast", cls._tool("playblast"), icon=cls._icon("playblast"), tooltip="What the viewport shows as a video or frames: camera, size, frame range, name. Maya 2025 and newer."),
                MenuAction("Rename", cls._tool("rename"), icon=cls._icon("rename"), tooltip="Quick naming of the selected objects: a name with numbers, sides and kinds, prefix / suffix, find & replace, a library of words — see before / after first. Maya 2025 and newer."),
                MenuDivider(),
                SubMenu("Dev", icon=cls._icon("dev"), items=(
                    MenuAction("Print Hello", cls._dev_action("print_hello"), icon=cls._icon("print_hello"), tooltip="Prints a test message."),
                    MenuAction("Print Environment", cls._dev_action("print_environment"), icon=cls._icon("print_environment"), tooltip="Prints Maya version, state and package location."),
                    MenuAction("Print Launch Report", f"{cls._TOOLS_PACKAGE}.launch_report.print_launch_report", icon=cls._icon("launch_report"), tooltip="Prints how this Maya was started: Maya Gate environment, preferences folder, variables, userSetup files, boost start and plug-ins."),
                    MenuDivider(),
                    MenuAction("Reload Code", cls._dev_action("reload_package"), icon=cls._icon("reload_code"), tooltip="Re-imports msl_tools from disk and rebuilds this menu. Already-open windows keep their old code until reopened."),
                    MenuAction("Rebuild Menu", f"{cls._ROOT_PACKAGE}.startup.rebuild_menu", icon=cls._icon("rebuild_menu"), tooltip="Re-creates this menu without reloading any code."),
                )),
            ),
        )

    @classmethod
    def _tool(cls, tool_name: str) -> str:
        """Dotted path to a tool's entry point (convention: `<tool package>.launcher_entry_point`)."""
        return f"{cls._TOOLS_PACKAGE}.{tool_name}.launcher_entry_point"

    @classmethod
    def _dev_action(cls, function_name: str) -> str:
        """Dotted path to a function in `dev_actions`."""
        return f"{cls._TOOLS_PACKAGE}.dev_actions.{function_name}"

    @classmethod
    def _icon(cls, name: str) -> str | None:
        """Absolute path to `assets/icons/menu/<name>.png`, or None if that file doesn't exist.
        The PNGs are rendered from our SVGs by ui/maya_menu_icons.py (MENU_ICONS names them).

        A bare filesystem lookup, not the Qt IconManager (see MenuAction.icon docstring) - so
        building the menu never needs PySide6 importable. Missing icons are silently skipped
        rather than warned about: an icon is cosmetic, and until PNGs are actually dropped into
        that folder every single item would otherwise warn on every menu build.
        """
        path = cls._ICON_DIR / f"{name}.png"
        return str(path) if path.is_file() else None