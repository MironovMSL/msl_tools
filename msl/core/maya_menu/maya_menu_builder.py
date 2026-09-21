"""
Renders a MenuSpec into a real menu in the Maya main window.
"""

import logging

from msl_tools.msl.core.reflection.reflection import Reflection
from msl_tools.msl.core.maya_menu.menu_spec import MenuAction, MenuDivider, MenuSpec, SubMenu


class MayaMenuBuilder:
    """Creates and removes a menu in the Maya main window from a MenuSpec.

    Holds no state except the injected logger. `maya.cmds` / `maya.mel` are imported
    lazily inside methods, so this module is importable outside Maya. Every public
    method returns None/False and logs a warning on failure instead of raising.
    """

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)

    def build(self, spec: MenuSpec) -> str | None:
        """Creates the menu described by `spec`, replacing an existing one with the same id.

        Idempotent: calling it again rebuilds the menu instead of duplicating it. A half-built
        menu is never left behind - on failure everything created so far is removed.

        Args:
            spec: Menu description.

        Returns:
            Maya UI path of the created menu, or None on failure.
        """
        if not spec.menu_id.isidentifier():
            self._logger.warning(f'Unable to build menu. Invalid menu_id: "{spec.menu_id}".')
            return None

        try:
            import maya.cmds as cmds
            import maya.mel as mel
        except ImportError as e:
            self._logger.warning(f'Unable to build menu. Maya is not available. Issue: "{e}".')
            return None

        main_window = mel.eval("$msl_main_window = $gMainWindow;")
        if not main_window:
            self._logger.warning("Unable to build menu. Maya main window was not found.")
            return None

        self.remove(spec.menu_id)
        try:
            menu = cmds.menu(spec.menu_id, label=spec.label, parent=main_window, tearOff=True)
            self._add_entries(menu, spec.items)
        except Exception as e:
            self._logger.warning(f'Unable to build menu "{spec.menu_id}". Issue: "{e}".')
            self.remove(spec.menu_id)
            return None
        return menu

    def remove(self, menu_id: str) -> bool:
        """Deletes the menu with `menu_id` from the Maya main window, if it exists.

        Args:
            menu_id: Maya UI object name of the menu.

        Returns:
            True if the menu is absent after the call (including "was never there"), False on failure.
        """
        try:
            import maya.cmds as cmds
            if cmds.menu(menu_id, exists=True):
                cmds.deleteUI(menu_id, menu=True)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to remove menu "{menu_id}". Issue: "{e}".')
            return False

    def _add_entries(self, parent: str, entries) -> None:
        """Recursively creates Maya UI items for `entries` under `parent`."""
        import maya.cmds as cmds

        for entry in entries:
            if isinstance(entry, SubMenu):
                sub_menu = cmds.menuItem(label=entry.label, subMenu=True, parent=parent)
                self._add_entries(sub_menu, entry.items)
            elif isinstance(entry, MenuDivider):
                cmds.menuItem(divider=True, dividerLabel=entry.label, parent=parent)
            elif isinstance(entry, MenuAction):
                cmds.menuItem(label=entry.label, annotation=entry.tooltip, enable=entry.enabled,
                              command=self._make_command(entry), parent=parent)
            else:
                self._logger.warning(f'Unknown menu entry skipped: {entry!r}')

    def _make_command(self, action: MenuAction):
        """Returns the callable Maya invokes on click. It only carries the action, not the tool."""
        def _command(*_args):
            self._run_action(action)
        return _command

    def _run_action(self, action: MenuAction) -> None:
        """Resolves `action.target` at click time and calls it.

        Late binding on purpose: the tool is imported only when clicked (fast Maya startup)
        and always comes from the current sys.modules (safe after a package reload).
        """
        import maya.cmds as cmds

        try:
            func = Reflection.import_from_path(action.target)
            if not callable(func):
                self._logger.warning(f'Menu action "{action.label}": target is missing or not callable: "{action.target}".')
                cmds.warning(f'MSL: unable to run "{action.label}". See Script Editor.')
                return
            func()
        except Exception:
            self._logger.exception(f'Menu action "{action.label}" failed. Target: "{action.target}".')
            cmds.warning(f'MSL: "{action.label}" failed. See Script Editor.')