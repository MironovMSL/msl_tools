"""
"Print Launch Report" of the MSL menu's Dev sub-menu: everything worth knowing about HOW this
Maya session was started — to see at a glance whether Maya Gate's environment, userSetup and
boost start did what they were set up to do.

Runs inside Maya. Read-only: it prints, it changes nothing.

Also asked for by the hub over the link (tools/maya/hub_link.py), so it must
run in every Maya the link runs in — Maya 2023 is Python 3.9: no newer
syntax at runtime, and no imports of msl modules that use it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Set by Maya Gate on every launch / on a boosted one (tools/desktop/maya_gate: page.py, boost.py).
GATE_ENVIRONMENT = "MSL_GATE_ENVIRONMENT"
GATE_VARIABLES = "MSL_GATE_VARIABLES"      # os.pathsep-joined names of the variables Maya Gate set
BOOST_SKIP = "MSL_GATE_BOOST_SKIP"
BOOST_REPORT = "MSL_GATE_BOOST_REPORT"
LAUNCH_FILE = "MSL_GATE_LAUNCH_FILE"       # this launch's record; the loader adds the startup time to it

# Variables shown besides every MAYA_* / MSL_* one.
_EXTRA_VARIABLES = ("PYTHONPATH", "XBMLANGPATH", "OCIO", "TEMP", "TMP", "PYTHONDONTWRITEBYTECODE")
_PATH_LIST_HINTS = ("PATH",)  # a name containing this and a value with os.pathsep = one entry per line
_WIDTH = 78


def _title(text: str) -> str:
    return f"\n--- {text} " + "-" * max(_WIDTH - len(text) - 5, 3)


def _mark(path: str) -> str:
    """"ok" / "MISSING" for a filesystem path."""
    return "ok     " if os.path.exists(path) else "MISSING"


def _variable_lines(name: str, value: str, full: bool) -> list[str]:
    """One variable. A folder list is laid out one entry per line with an
    ok / MISSING mark when `full`, else summed up as a count — Maya extends
    its own lists (MAYA_SCRIPT_PATH, XBMLANGPATH, ...) with dozens of
    module folders that would bury everything else."""
    entries = [entry for entry in value.split(os.pathsep) if entry.strip()]
    is_list = any(hint in name for hint in _PATH_LIST_HINTS) and (len(entries) > 1 or os.path.isabs(value))
    if not is_list:
        return [f"  {name} = {value}"]
    if not full:
        missing = sum(1 for entry in entries if not os.path.exists(entry))
        return [f"  {name} = {len(entries)} folder(s)" + (f", {missing} missing" if missing else "")]
    return [f"  {name} ="] + [f"      {_mark(entry)}  {entry}" for entry in entries]


def _autoload_names(prefs_file: Path) -> list[str]:
    """Plug-in names in Maya's pluginPrefs.mel (same parsing as Maya Gate's boost)."""
    quote = chr(92) + '"'
    names: list[str] = []
    try:
        for line in prefs_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if "autoLoadPlugin(" in line:
                parts = line.split(quote)
                if len(parts) >= 6 and parts[3] not in names:
                    names.append(parts[3])
    except OSError:
        pass
    return names


def build_launch_report() -> str:
    """The report as text (print_launch_report() prints it)."""
    import maya.cmds as cmds

    from msl_tools.msl import __version__

    environ = os.environ
    lines = ["", "=" * _WIDTH, " MSL launch report", "=" * _WIDTH]

    # --- the session -----------------------------------------------------------------
    lines.append(_title("Maya"))
    lines.append(f"  version      : {cmds.about(version=True)}  ({cmds.about(installedVersion=True)})")
    lines.append(f"  state        : {'batch' if cmds.about(batch=True) else 'interactive'}")
    lines.append(f"  executable   : {sys.executable}")
    lines.append(f"  Python       : {sys.version.split()[0]}")
    lines.append(f"  msl_tools    : {__version__}  at {Path(__file__).resolve().parents[3]}")

    # --- Maya Gate -------------------------------------------------------------------
    lines.append(_title("Maya Gate"))
    environment = environ.get(GATE_ENVIRONMENT)
    if environment is None:
        lines.append("  not started from Maya Gate (or from a version older than this report)")
    else:
        lines.append(f"  environment  : {environment}")
    boosted = BOOST_SKIP in environ
    lines.append(f"  boost start  : {'ON' if boosted else 'off'}")
    try:
        launch = json.loads(Path(environ.get(LAUNCH_FILE, "")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        launch = {}
    if "ready_seconds" in launch:
        plugins = f"  (plug-ins {launch['plugin_seconds']} s)" if "plugin_seconds" in launch else ""
        lines.append(f"  startup time : {launch['ready_seconds']} s from the click in Maya Gate until Maya was idle{plugins}")
    elif LAUNCH_FILE in environ:
        lines.append("  startup time : not measured (Maya's side did not report it)")

    # --- preferences -----------------------------------------------------------------
    lines.append(_title("Preferences"))
    app_dir = environ.get("MAYA_APP_DIR")
    lines.append(f"  MAYA_APP_DIR : {app_dir if app_dir else '(not set - Maya default)'}")
    lines.append(f"  user folder  : {cmds.internalVar(userAppDir=True)}")
    prefs_dir = Path(cmds.internalVar(userPrefDir=True))
    lines.append(f"  prefs        : {prefs_dir}")
    lines.append(f"  scripts      : {cmds.internalVar(userScriptDir=True)}")

    # --- variables -------------------------------------------------------------------
    by_gate = [name for name in environ.get(GATE_VARIABLES, "").split(os.pathsep) if name]
    lines.append(_title("Variables set by Maya Gate"))
    for name in by_gate:
        if name in environ:
            lines += _variable_lines(name, environ[name], full=True)
        else:
            lines.append(f"  {name}  (set by Maya Gate, but not in this session's environment)")
    if not by_gate:
        lines.append("  none" if environment is not None else "  unknown (not started from Maya Gate)")

    lines.append(_title("Other MAYA_* / MSL_* variables (folder lists summed up)"))
    names = sorted(name for name in environ
                   if (name.startswith(("MAYA_", "MSL_")) or name in _EXTRA_VARIABLES) and name not in by_gate)
    for name in names:
        lines += _variable_lines(name, environ[name], full=False)

    # --- userSetup -------------------------------------------------------------------
    lines.append(_title("userSetup files Maya ran (in sys.path order)"))
    found = []
    for folder in sys.path:
        for file_name in ("userSetup.py", "userSetup.mel"):
            path = os.path.join(folder, file_name)
            if os.path.isfile(path) and path not in found:
                found.append(path)
    lines += [f"  {path}" for path in found] or ["  none"]
    if "MAYA_SKIP_USERSETUP_PY" in environ:
        lines.append("  NOTE: MAYA_SKIP_USERSETUP_PY is set - Maya skipped every userSetup.py above")

    # --- plug-ins --------------------------------------------------------------------
    lines.append(_title("Plug-ins"))
    loaded = sorted(cmds.pluginInfo(query=True, listPlugins=True) or [], key=str.lower)
    autoload = _autoload_names(prefs_dir / "pluginPrefs.mel")
    lines.append(f"  loaded now            : {len(loaded)}")
    lines.append(f"  Maya's auto-load list : {len(autoload)}  ({prefs_dir / 'pluginPrefs.mel'})")
    if boosted:
        skip = [name for name in environ.get(BOOST_SKIP, "").split(os.pathsep) if name]
        loaded_keys = {name.lower() for name in loaded}
        came_anyway = [name for name in skip if os.path.splitext(name)[0].lower() in loaded_keys]
        lines.append(f"  skipped by boost      : {len(skip)}  {', '.join(skip)}")
        if came_anyway:
            lines.append(f"  skipped, yet loaded   : {', '.join(came_anyway)}  (a dependency or the scene needed them)")
        report_file = environ.get(BOOST_REPORT, "")
        try:
            report = json.loads(Path(report_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            report = None
        if report is None:
            lines.append(f"  boost report          : none yet  ({report_file})")
        else:
            entries = report.get("plugins", {})
            by_status: dict[str, list[str]] = {}
            for name, entry in entries.items():
                by_status.setdefault(entry.get("status", "?"), []).append(name)
            counts = ", ".join(f"{len(group)} {status}" for status, group in sorted(by_status.items()))
            lines.append(f"  boost loaded          : {counts}  in {report.get('seconds', '?')} s  ({report.get('time', '')})")
            for name in by_status.get("failed", []):
                lines.append(f"      FAILED  {name}: {entries[name].get('error', '')}")
            for note in report.get("notes", []):
                lines.append(f"      note    {note}")
            slowest = sorted(entries.items(), key=lambda item: -float(item[1].get("seconds", 0)))[:8]
            lines.append("  slowest to load:")
            lines += [f"      {float(entry.get('seconds', 0)):6.2f} s  {name}" for name, entry in slowest
                      if float(entry.get("seconds", 0)) > 0]
    lines.append("  loaded plug-ins:")
    for start in range(0, len(loaded), 6):
        lines.append("      " + ", ".join(loaded[start:start + 6]))

    lines.append(_title("Modules"))
    modules = cmds.moduleInfo(listModules=True) or []
    for module in modules:
        lines.append(f"  {module:<28} {cmds.moduleInfo(moduleName=module, path=True)}")
    if not modules:
        lines.append("  none")

    lines.append("=" * _WIDTH)
    return "\n".join(lines)


def print_launch_report() -> None:
    """Prints the launch report to the Script Editor."""
    print(build_launch_report())
