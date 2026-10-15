# tools/maya/hotkeys.py
"""Actions of msl_tools as Maya "runtime commands": named commands that show up in the Hotkey
Editor, so a key is given to them the usual way — no code pasted. Two categories:
Custom Scripts > MSL Tools (COMMANDS: the tools' windows and what needs one) and Custom Scripts >
MSL Scripts (tools/maya/scripts SCRIPTS: one key = one thing done, no window). No key is given to
any of them: the user does that in the Hotkey Editor.

The actions themselves are functions of the package; a command only names one. Maya keeps
runtime commands in the user's preferences, so `register()` is safe to call on every start: a
command that exists is brought up to date, never duplicated.
"""
from maya import cmds

CATEGORY = "Custom Scripts.MSL Tools"
SCRIPTS_CATEGORY = "Custom Scripts.MSL Scripts"
# name -> (what the Hotkey Editor says about it, the Python it runs)
COMMANDS = {
    "MSLPlayblast": ("Open the MSL Playblast window",
                     "from msl_tools.msl.tools.maya.playblast import launcher_entry_point; launcher_entry_point()"),
    "MSLPlayblastRepeat": ("Playblast again with the settings used last (opens the window if it is closed)",
                           "from msl_tools.msl.tools.maya.playblast import repeat_last; repeat_last()"),
    "MSLLabels": ("Open the MSL Labels window (attribute values in the viewport)",
                  "from msl_tools.msl.tools.maya.labels import launcher_entry_point; launcher_entry_point()"),
    "MSLRename": ("Open the MSL Rename window",
                  "from msl_tools.msl.tools.maya.rename import launcher_entry_point; launcher_entry_point()"),
    "MSLControls": ("Controls: the window of control shapes and tools",
                    "from msl_tools.msl.tools.maya.controls import launcher_entry_point; launcher_entry_point()"),
    "MSLRenameQuick": ("Rename at the mouse pointer: a small field, Enter renames the selection",
                       "from msl_tools.msl.tools.maya.rename import quick; quick()"),
    "MSLRenameRepeat": ("Rename again: the last rename on what is selected now (opens the window if it is closed)",
                        "from msl_tools.msl.tools.maya.rename import repeat_last; repeat_last()"),
    "MSLPathsToVariables": ("Paths to variables: the open scene's absolute paths become $WG_ANIM/... (asks first)",
                            "from msl_tools.msl.tools.maya.scene_paths_tool import paths_to_variables; paths_to_variables()"),
}


def all_commands() -> dict:
    """name -> (annotation, Python, category) of every command: the tools' and the scripts'."""
    from msl_tools.msl.tools.maya.scripts import SCRIPTS
    commands = {name: (annotation, command, CATEGORY) for name, (annotation, command) in COMMANDS.items()}
    for script in SCRIPTS:
        commands[script.command] = (script.annotation, script.python(), SCRIPTS_CATEGORY)
    return commands


def register() -> list[str]:
    """Creates (or updates) the runtime commands. Returns their names. A command that moved to
    another category (a tool's quick action into MSL Scripts) is moved there; its key stays."""
    commands = all_commands()
    for name, (annotation, command, category) in commands.items():
        if cmds.runTimeCommand(name, query=True, exists=True):
            cmds.runTimeCommand(name, edit=True, annotation=annotation, command=command, commandLanguage="python",
                                category=category)
        else:
            cmds.runTimeCommand(name, annotation=annotation, command=command, commandLanguage="python",
                                category=category)
    return list(commands)
