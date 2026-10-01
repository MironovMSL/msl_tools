# tools/desktop/maya_gate/maya_variables.py
"""What Maya Gate knows about Maya's environment variables — Qt-free.

The single source for the known-variables dropdown (EnvVariableAdder) and
for how each variable's value is edited in its row:

- PATH_LIST: several folders joined by os.pathsep (";" on Windows) — Maya
  searches all of them. Browsing ADDS a folder; replacing would silently
  drop the ones already there.
- PATH: exactly one folder. Browsing replaces it.
- FILE: one file. Browsing picks a file.
- FLAG: on or off — an On / Off switch. ON stores `on_value` ("1"); OFF
  stores "" and the variable is then NOT passed to Maya at all: many of
  Maya's flags only check that the variable EXISTS, so "=0" would still
  switch them on. An off flag keeps its row, so it is one click to turn
  back on.
- CHOICE: one of `choices` — a drop-down ("" = not set).
- VALUE: free text that isn't a path (a number, a name). No browse button.

Variables Maya Gate doesn't know (the custom ones) are treated as PATH.

An empty value of ANY kind is not passed to Maya (launch_values()).
"""
from dataclasses import dataclass
from enum import Enum, auto
from typing import Mapping


class VariableKind(Enum):
    PATH_LIST = auto()
    PATH = auto()
    FILE = auto()
    FLAG = auto()
    CHOICE = auto()
    VALUE = auto()


@dataclass(frozen=True)
class VariableSpec:
    """One known variable.

    Attributes:
        name: The variable's name.
        kind: What its value is (see the module docstring).
        description: One line on what it does ("" = none yet).
        choices: CHOICE only — the values to pick from.
        on_value: FLAG only — the value that switches it on.
    """

    name: str
    kind: VariableKind = VariableKind.PATH
    description: str = ""
    choices: tuple[str, ...] = ()
    on_value: str = "1"

    @property
    def default_value(self) -> str:
        """Value a freshly added variable starts with: a flag is added to be
        switched ON; everything else starts empty."""
        return self.on_value if self.kind is VariableKind.FLAG else ""


def _spec(name: str, kind: VariableKind, **details) -> VariableSpec:
    return VariableSpec(name=name, kind=kind, **details)


# Dropdown order = this order.
_SPECS: tuple[VariableSpec, ...] = (
    _spec("MAYA_PLUG_IN_PATH", VariableKind.PATH_LIST),
    _spec("MAYA_MODULE_PATH", VariableKind.PATH_LIST),
    _spec("MAYA_SCRIPT_PATH", VariableKind.PATH_LIST),
    _spec("MAYA_SHELF_PATH", VariableKind.PATH_LIST),
    _spec("XBMLANGPATH", VariableKind.PATH_LIST),
    _spec("MAYA_APP_DIR", VariableKind.PATH),
    _spec("MAYA_ENV_DIR", VariableKind.PATH),
    _spec("MAYA_LOCATION", VariableKind.PATH),
    _spec("PYTHONPATH", VariableKind.PATH_LIST),
    _spec("TEMP", VariableKind.PATH),
    _spec("MAYA_PROJECT", VariableKind.PATH),
    _spec("MAYA_SHADER_PATH", VariableKind.PATH_LIST),
    _spec("MAYA_ICON_PATH", VariableKind.PATH_LIST),
    # Flags — Autodesk's customer-involvement / error-report / licensing popups.
    _spec("MAYA_DISABLE_CIP", VariableKind.FLAG),
    _spec("MAYA_DISABLE_CER", VariableKind.FLAG),
    _spec("MAYA_DISABLE_CLIC_IPM", VariableKind.FLAG),
)

_KNOWN: dict[str, VariableSpec] = {spec.name: spec for spec in _SPECS}

KNOWN_VARIABLES: list[str] = list(_KNOWN)


def spec_of(name: str) -> VariableSpec:
    """What is known about variable `name`; an unknown (custom) variable
    comes back as a PATH with no description."""
    return _KNOWN.get(name) or VariableSpec(name=name)


def kind_of(name: str) -> VariableKind:
    """Kind of variable `name`; unknown (custom) variables count as PATH."""
    return spec_of(name).kind


def launch_values(variables: Mapping[str, str]) -> dict[str, str]:
    """The variables to actually pass to Maya: those with a value. An empty
    one — a flag switched off, a choice not made, a field left blank — is
    left out, so Maya sees it as not set."""
    return {name: value for name, value in variables.items() if str(value).strip()}
