# tools/desktop/maya_gate/launch_check.py
"""What is wrong with an environment BEFORE Maya is started with it — the things that otherwise
show up only inside Maya, as a missing menu or a plug-in that didn't load. Qt-free; it reads the
disk (folders that should exist), so call it off the window's thread.
"""
from __future__ import annotations

import os
import re
from typing import Mapping

from msl_tools.msl.tools.desktop.maya_gate.maya_variables import VariableKind, kind_of
from msl_tools.msl.tools.desktop.maya_gate.user_setup import UserSetupStore

_REFERENCE = re.compile(r"%[^%]+%|\$\{?\w+")  # %VAR%, $VAR, ${VAR}: filled in by Maya, can't be checked here


def _looks_like_path(text: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:[\\/]|\\\\|/)", text))


def missing_paths(variables: Mapping[str, str]) -> list[str]:
    """One line per folder or file a variable names that isn't there."""
    problems = []
    for name, value in variables.items():
        kind = kind_of(name)
        if kind is VariableKind.PATH_LIST:
            entries = [entry.strip() for entry in str(value).split(os.pathsep)]
        elif kind in (VariableKind.PATH, VariableKind.FILE):
            entries = [str(value).strip()]
        else:
            entries = [str(value).strip()] if _looks_like_path(str(value).strip()) else []
        for entry in entries:
            if entry and not _REFERENCE.search(entry) and _looks_like_path(entry) and not os.path.exists(entry):
                problems.append(f"{name}: {entry} isn’t there")
    return problems


def check(variables: Mapping[str, str], script: str = "", boost_enabled: bool = False,
          boost_blocked: str = "") -> list[str]:
    """Everything worth a look before a launch, one line each ([] = nothing).

    Args:
        variables: The environment's variables as a launch passes them.
        script: The environment's userSetup script.
        boost_enabled: Boost start is switched on for it.
        boost_blocked: Why a boosted launch can't be made ("" = it can).
    """
    problems = missing_paths(variables)
    if script.strip():
        error = UserSetupStore.syntax_error(script)
        if error is not None:
            problems.append(f"userSetup, line {error[0]}: {error[1]}")
    if boost_enabled and boost_blocked:
        problems.append(f"Boost start is on but won’t be applied: {boost_blocked}")
    return problems
