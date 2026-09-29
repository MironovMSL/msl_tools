# tools/desktop/maya_gate/maya_variables.py
"""What Maya Gate knows about Maya's environment variables — Qt-free.

The single source for the known-variables dropdown (EnvVariableAdder) and
for how each variable's value is edited (the row's browse button):

- PATH_LIST: several folders joined by os.pathsep (";" on Windows) — Maya
  searches all of them. Browsing ADDS a folder; replacing would silently
  drop the ones already there.
- PATH: exactly one folder. Browsing replaces it.
- VALUE: not a path (a flag like "1"). No browse button.

Variables Maya Gate doesn't know (custom ones typed into "Additional")
are treated as PATH.
"""
from enum import Enum, auto


class VariableKind(Enum):
    PATH_LIST = auto()
    PATH = auto()
    VALUE = auto()


# Dropdown order = insertion order.
_KNOWN: dict[str, VariableKind] = {
    "MAYA_PLUG_IN_PATH": VariableKind.PATH_LIST,
    "MAYA_MODULE_PATH": VariableKind.PATH_LIST,
    "MAYA_SCRIPT_PATH": VariableKind.PATH_LIST,
    "MAYA_SHELF_PATH": VariableKind.PATH_LIST,
    "XBMLANGPATH": VariableKind.PATH_LIST,
    "MAYA_APP_DIR": VariableKind.PATH,
    "MAYA_ENV_DIR": VariableKind.PATH,
    "MAYA_LOCATION": VariableKind.PATH,
    "PYTHONPATH": VariableKind.PATH_LIST,
    "TEMP": VariableKind.PATH,
    "MAYA_PROJECT": VariableKind.PATH,
    "MAYA_SHADER_PATH": VariableKind.PATH_LIST,
    "MAYA_ICON_PATH": VariableKind.PATH_LIST,
    # Flags ("1" to set) — Autodesk's customer-involvement / error-report / licensing popups.
    "MAYA_DISABLE_CIP": VariableKind.VALUE,
    "MAYA_DISABLE_CER": VariableKind.VALUE,
    "MAYA_DISABLE_CLIC_IPM": VariableKind.VALUE,
}

KNOWN_VARIABLES: list[str] = list(_KNOWN)


def kind_of(name: str) -> VariableKind:
    """Kind of variable `name`; unknown (custom) variables count as PATH."""
    return _KNOWN.get(name, VariableKind.PATH)
