# tools/maya/hotkeys.py
"""Actions of msl_tools as Maya "runtime commands": named commands that show up in the Hotkey
Editor (Custom Scripts > MSL Tools), so a key is given to them the usual way — no code pasted.

The actions themselves are functions of the package; a command only names one. Maya keeps
runtime commands in the user's preferences, so `register()` is safe to call on every start: a
command that exists is brought up to date, never duplicated.
"""
from maya import cmds

CATEGORY = "Custom Scripts.MSL Tools"
# name -> (what the Hotkey Editor says about it, the Python it runs)
COMMANDS = {
    "MSLPlayblast": ("Open the MSL Playblast window",
                     "from msl_tools.msl.tools.maya.playblast import launcher_entry_point; launcher_entry_point()"),
    "MSLPlayblastRepeat": ("Playblast again with the settings used last (opens the window if it is closed)",
                           "from msl_tools.msl.tools.maya.playblast import repeat_last; repeat_last()"),
    "MSLShotMaskToggle": ("Show or hide the MSL shot mask in the viewport",
                          "from msl_tools.msl.tools.maya.playblast import toggle_mask; toggle_mask()"),
    "MSLRename": ("Open the MSL Rename window",
                  "from msl_tools.msl.tools.maya.rename import launcher_entry_point; launcher_entry_point()"),
    "MSLControls": ("Controls: the window of control shapes and tools",
                    "from msl_tools.msl.tools.maya.controls import launcher_entry_point; launcher_entry_point()"),
    "MSLRenameQuick": ("Rename at the mouse pointer: a small field, Enter renames the selection",
                       "from msl_tools.msl.tools.maya.rename import quick; quick()"),
    "MSLRenameRepeat": ("Rename again: the last rename on what is selected now (opens the window if it is closed)",
                        "from msl_tools.msl.tools.maya.rename import repeat_last; repeat_last()"),
}


def register() -> list[str]:
    """Creates (or updates) the runtime commands. Returns their names."""
    for name, (annotation, command) in COMMANDS.items():
        if cmds.runTimeCommand(name, query=True, exists=True):
            cmds.runTimeCommand(name, edit=True, annotation=annotation, command=command, commandLanguage="python",
                                category=CATEGORY)
        else:
            cmds.runTimeCommand(name, annotation=annotation, command=command, commandLanguage="python",
                                category=CATEGORY)
    return list(COMMANDS)
