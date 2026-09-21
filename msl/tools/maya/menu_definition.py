"""
Content of the MSL main menu: which entries exist and what they run.

Pure data (a MenuSpec). Nothing here imports the tools themselves - entries only reference
them by dotted path, so building the menu stays fast and never breaks on a broken tool.
"""

from msl_tools.msl.core.maya_menu import MenuAction, MenuDivider, MenuSpec, SubMenu


class MslMenuDefinition:
    """Builds the MenuSpec of the MSL main menu."""

    MENU_ID = "MSLToolsMenu"
    MENU_LABEL = "MSL"

    # Dotted paths are derived from this module's own package, so they follow the package
    # layout automatically ("<root>.tools.maya" -> "<root>").
    _TOOLS_PACKAGE = __package__
    _ROOT_PACKAGE = __package__.rsplit(".", 2)[0]

    @classmethod
    def build(cls) -> MenuSpec:
        """Returns the current menu description."""
        return MenuSpec(
            menu_id=cls.MENU_ID,
            label=cls.MENU_LABEL,
            items=(
                # Temporary entry: the installer stays reachable from the menu for now.
                MenuAction("Installer", cls._tool("installer"), tooltip="Open the MSL installer."),
                MenuDivider(),
                SubMenu("Dev", items=(
                    MenuAction("Print Hello", cls._dev_action("print_hello"),
                               tooltip="Prints a test message."),
                    MenuAction("Print Environment", cls._dev_action("print_environment"),
                               tooltip="Prints Maya version, state and package location."),
                    MenuDivider(),
                    MenuAction("Rebuild Menu", f"{cls._ROOT_PACKAGE}.startup.rebuild_menu",
                               tooltip="Re-creates this menu."),
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