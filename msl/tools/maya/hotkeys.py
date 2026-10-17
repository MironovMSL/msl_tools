# tools/maya/hotkeys.py
"""Actions of msl_tools as Maya "runtime commands": named commands that show up in the Hotkey
Editor, so a key is given to them the usual way — no code pasted. Two categories:
Custom Scripts > MSL Tools (COMMANDS: the tools' windows and what needs one) and Custom Scripts >
MSL Scripts (tools/maya/scripts SCRIPTS: one key = one thing done, no window). No key is given to
any of them here: the user gives them in the Hotkey Editor, or for every Maya of an environment in Maya
Gate's Hotkeys tab (tools/maya/hotkey_set.py puts those in the hotkey set "MSL").

The actions themselves are functions of the package; a command only names one. Maya keeps
runtime commands in the user's preferences, so `register()` is safe to call on every start: a
command that exists is brought up to date, never duplicated.
"""
from maya import cmds

from msl_tools.msl.tools.maya import hotkey_catalog

CATEGORY = hotkey_catalog.TOOLS_CATEGORY
SCRIPTS_CATEGORY = hotkey_catalog.SCRIPTS_CATEGORY
# name -> (what the Hotkey Editor says about it, the Python it runs) - the tools' (hotkey_catalog.py: one list
# for Maya and the hub, whose Hotkeys tab gives them keys)
COMMANDS = {command.name: (command.annotation, command.python) for command in hotkey_catalog.TOOL_COMMANDS}


def all_commands() -> dict:
    """name -> (annotation, Python, category) of every command: the tools' and the scripts'."""
    return {command.name: (command.annotation, command.python, command.category)
            for command in hotkey_catalog.commands()}


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
