# core/scene_paths/coverage.py
"""Where a variable a scene's paths depend on is SET — so a scene written as "$WG_ANIM/..." isn't
opened somewhere it means nothing (Maya then finds none of its files, and says little about why).

Looked at, on this machine:
- Maya Gate's environments (each sets its own variables: a Maya started from Dev has WG_ANIM, one
  started from Stable may not);
- Windows' own variables, the user's and the system's (the registry — not this process's
  environment, which a hub started from an IDE or before a change doesn't show);
- Maya.env of every installed Maya version: <prefs>/<year>/Maya.env, where <prefs> is Documents/maya
  — and the MAYA_APP_DIR an environment sets, for a Maya started from it. Measured with mayapy 2024:
  Maya reads ONLY the versioned file (<prefs>/Maya.env without a year is not read), values are trimmed,
  and a variable already set in the process (by Maya Gate, by Windows) wins over Maya.env.

What a scene opened elsewhere sees (a render farm, a colleague's machine) can't be known from here:
the warning says so instead of guessing. Qt-free; reads files and the registry.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from msl_tools.msl.core.batch import environments


@dataclass
class Coverage:
    """Where one variable is set: {place: value} for each kind of place ("" = not set there)."""

    name: str
    gate: dict = field(default_factory=dict)        # Maya Gate environment -> value
    windows: dict = field(default_factory=dict)     # "user" / "system" -> value
    maya_env: dict = field(default_factory=dict)    # "Maya 2024" / "Maya 2024 · Dev" -> value
    problems: list = field(default_factory=list)    # lines that look meant for it but don't set it

    @property
    def in_windows(self) -> str:
        """Its value for every program on this machine ("" = Windows doesn't set it)."""
        return self.windows.get("user") or self.windows.get("system") or ""

    @property
    def gate_without(self) -> list:
        return [name for name, value in self.gate.items() if not value]

    @property
    def gate_with(self) -> list:
        return [name for name, value in self.gate.items() if value]

    @property
    def maya_env_with(self) -> list:
        return [place for place, value in self.maya_env.items() if value]

    def gaps(self) -> list[str]:
        """Plain words for each way a Maya on this machine would start WITHOUT the variable."""
        if self.in_windows:
            return []   # every program gets it, a Maya from the Start menu too
        gaps = []
        plain = [place for place in self.maya_env if "·" not in place]   # Documents/maya, no MAYA_APP_DIR
        if not any(self.maya_env.get(place) for place in plain):
            gaps.append("a Maya not started from Maya Gate (the Start menu, a double click on a scene)")
        for name in self.gate_without:
            own = [place for place in self.maya_env if place.endswith(f"· {name}")]
            if own and any(self.maya_env.get(place) for place in own):
                continue   # its MAYA_APP_DIR's Maya.env sets it
            if not own and any(self.maya_env.get(place) for place in plain):
                continue   # the Documents Maya.env sets it, and this environment reads that one
            gaps.append(f"Maya Gate · {name}")
        return gaps

    def describe(self) -> str:
        """Every place, one per line — for a tooltip / a dialog's details."""
        lines = [f"${self.name}"]
        for name, value in self.gate.items():
            lines.append(f"  Maya Gate · {name}: {value or '— not set'}")
        for place in ("user", "system"):
            lines.append(f"  Windows ({place}): {self.windows.get(place) or '— not set'}")
        for place, value in self.maya_env.items():
            lines.append(f"  Maya.env · {place}: {value or '— not set'}")
        lines += [f"  ✗ {problem}" for problem in self.problems]
        return "\n".join(lines)


def read_maya_env(file) -> dict:
    """NAME = value lines of a Maya.env (values trimmed, as Maya reads them); {} when there is none."""
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found = {}
    for line in text.splitlines():
        name, equals, value = line.partition("=")
        if equals and name.strip():
            found[name.strip()] = value.strip()
    return found


def windows_variables() -> dict:
    """{"user": {name: value}, "system": {...}} from the registry ({} off Windows / unreadable)."""
    found = {"user": {}, "system": {}}
    if sys.platform != "win32":
        return found
    import winreg
    places = {"user": (winreg.HKEY_CURRENT_USER, r"Environment"),
              "system": (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")}
    for place, (hive, key_path) in places.items():
        try:
            with winreg.OpenKey(hive, key_path) as key:
                index = 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    found[place][str(name).upper()] = str(value)
                    index += 1
        except OSError:
            continue
    return found


def coverage(names, gate_config, years, documents_prefs, windows: dict | None = None) -> dict[str, Coverage]:
    """{name: Coverage} for each variable of `names`.

    gate_config: Maya Gate's config.json; years: the installed Maya versions ("2024", ...);
    documents_prefs: Documents/maya (MayaPaths.get_preferences_root()); windows: windows_variables()
    (read here when None — a test gives its own)."""
    windows = windows_variables() if windows is None else windows
    gate_names = environments.names(gate_config)
    gate_values = {env: environments.variables(gate_config, env, base={}) for env in gate_names}
    env_files: dict[str, dict] = {}
    env_paths: dict[str, Path] = {}
    for year in sorted(years):
        places = [(f"Maya {year}", documents_prefs)] if documents_prefs else []
        places += [(f"Maya {year} · {env}", _get(variables, "MAYA_APP_DIR"))
                   for env, variables in gate_values.items() if _get(variables, "MAYA_APP_DIR")]
        for place, prefs in places:
            env_paths[place] = Path(prefs) / year / "Maya.env"
            env_files[place] = read_maya_env(env_paths[place])
    result = {}
    for name in names:   # names compare as Windows does: in any case
        upper = name.upper()
        found = Coverage(
            name,
            gate={env: _get(variables, name) for env, variables in gate_values.items()},
            windows={place: _get(windows.get(place) or {}, upper) for place in ("user", "system")})
        for place, values in env_files.items():
            found.maya_env[place] = ""
            for written, value in values.items():
                if written.lstrip("$").upper() != upper:
                    continue
                file = env_paths[place]
                reasons = []
                if written.startswith("$"):
                    reasons.append(f"no “$” before the name: Maya sets a variable called “{written}”, not {name}")
                if value.endswith(";"):
                    reasons.append(f"the “;” at its end makes it a list: ${name}/tex.png would read "
                                   f"“{value}/tex.png”")
                if reasons:
                    found.problems.append(f"{file}: “{written} = {value}” — " + "; and ".join(reasons))
                else:
                    found.maya_env[place] = value
        result[name] = found
    return result


def _get(values: dict, name: str) -> str:
    """values[name] in any case, trimmed ("" = not there or empty)."""
    upper = name.upper()
    for key, value in values.items():
        if str(key).upper() == upper:
            return str(value).strip()
    return ""
