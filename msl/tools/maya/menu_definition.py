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
                # Temporary entry: the installer stays reachable from the menu for now.
                MenuAction("Installer", cls._tool("installer"), tooltip="Open the MSL installer.", icon=cls._icon("installer")),
                MenuDivider(),
                SubMenu("Dev", icon=cls._icon("dev"), items=(
                    MenuAction("Print Hello", cls._dev_action("print_hello"), tooltip="Prints a test message."),
                    MenuAction("Print Environment", cls._dev_action("print_environment"), tooltip="Prints Maya version, state and package location."),
                    MenuDivider(),
                    MenuAction("Reload Code", cls._dev_action("reload_package"), tooltip="Re-imports msl_tools from disk and rebuilds this menu. Already-open windows keep their old code until reopened."),
                    MenuAction("Rebuild Menu", f"{cls._ROOT_PACKAGE}.startup.rebuild_menu", tooltip="Re-creates this menu without reloading any code."),
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

        A bare filesystem lookup, not the Qt IconManager (see MenuAction.icon docstring) - so
        building the menu never needs PySide6 importable. Missing icons are silently skipped
        rather than warned about: an icon is cosmetic, and until PNGs are actually dropped into
        that folder every single item would otherwise warn on every menu build.
        """
        path = cls._ICON_DIR / f"{name}.png"
        return str(path) if path.is_file() else None