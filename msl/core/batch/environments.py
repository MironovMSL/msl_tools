# core/batch/environments.py
"""Maya Gate's environments for a render: the variables an environment sets (its Maya and its custom
ones, as Maya Gate keeps them in configs/desktop/maya_gate/config.json), plus the paths msl_tools
itself puts in front (the package's folder on PYTHONPATH, its Maya module on MAYA_MODULE_PATH).

What a render does NOT take from the environment: its userSetup script (that is the artist's
startup — menus, tools —, not the render's), boost (a render loads what the scene needs), the hub
link and the console. Read-only: the file is never written here.
"""
from __future__ import annotations

import os
from pathlib import Path

from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object

DEFAULT_NAMES = ["<default>", "Stable", "Dev"]
PREPENDED = ("PYTHONPATH", "MAYA_MODULE_PATH")


def _config(config_file) -> dict:
    try:
        return read_json_object(Path(config_file))
    except (JsonUnavailable, OSError):
        return {}


def names(config_file) -> list[str]:
    """The environments Maya Gate knows (its defaults first, then any other it has settings for)."""
    data = _config(config_file)
    found = list(DEFAULT_NAMES)
    for branch in ("maya", "custom"):
        for name in (data.get(branch) or {}):
            if isinstance(name, str) and name not in found:
                found.append(name)
    return found


def variables(config_file, name: str, package_parent=None, module_folder=None, base=None) -> dict:
    """The environment `name` as a dict of variables to lay over `base` (the process's own): every
    non-empty variable the environment sets, with msl_tools' own paths in front of PYTHONPATH and
    MAYA_MODULE_PATH. An unknown / empty name gives just msl_tools' paths."""
    data = _config(config_file)
    result: dict = {}
    for branch in ("maya", "custom"):
        section = (data.get(branch) or {}).get(name) or {}
        if isinstance(section, dict):
            result.update({str(key): str(value) for key, value in section.items() if str(value).strip()})
    base = dict(os.environ if base is None else base)
    front = {"PYTHONPATH": str(package_parent) if package_parent else "",
             "MAYA_MODULE_PATH": str(module_folder) if module_folder else ""}
    for key in PREPENDED:
        parts = [front[key]] if front[key] else []
        own = result.get(key)
        if own:
            parts.append(own)
        elif key != "PYTHONPATH" and base.get(key):  # the hub's own PYTHONPATH never goes to Maya
            parts.append(base[key])
        if parts:
            result[key] = os.pathsep.join(parts)
    return result
