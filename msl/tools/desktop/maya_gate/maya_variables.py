# tools/desktop/maya_gate/maya_variables.py
"""What Maya Gate knows about Maya's environment variables — Qt-free.

The single source for the known-variables dropdown (EnvVariableAdder: the
groups, their order, the descriptions shown as tooltips) and for how each
variable's value is edited in its row:

- PATH_LIST: several folders joined by os.pathsep (";" on Windows) — Maya
  searches all of them. Browsing ADDS a folder; replacing would silently
  drop the ones already there.
- PATH: exactly one folder. Browsing replaces it.
- FILE: one file. Browsing picks a file (`file_filter`).
- FLAG: on or off — an On / Off switch. ON stores `on_value` (usually "1");
  OFF stores "" and the variable is then NOT passed to Maya at all: many of
  Maya's flags only check that the variable EXISTS (MAYA_SKIP_USERSETUP_PY:
  `if 'MAYA_SKIP_USERSETUP_PY' not in os.environ`), so "=0" would still
  switch them on. An off flag keeps its row, so it is one click to turn
  back on.
- CHOICE: one of `choices` — a drop-down ("" = not set).
- VALUE: free text that isn't a path (a number, a name). No browse button.

Variables Maya Gate doesn't know (the custom ones) are treated as PATH.
An empty value of ANY kind is not passed to Maya (launch_values()).

The catalog is a CURATED part of Maya's variables (Windows, the ones worth
setting per environment), not all of them. Every name was checked to exist
in a Maya 2025 install (binaries / startup scripts); kinds, values and
descriptions follow Autodesk's "Environment variables" help (Maya 2025:
General, File path, Rendering variables) — the descriptions are our own
one-liners. Before adding a variable, check both; a wrong kind here
silently writes a wrong value into every launch.
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
        description: One line on what it does ("" = unknown variable).
        group: Title of the dropdown group it is listed under.
        choices: CHOICE only — the values to pick from.
        on_value: FLAG only — the value that switches it on.
        file_filter: FILE only — the file dialog's filter.
    """

    name: str
    kind: VariableKind = VariableKind.PATH
    description: str = ""
    group: str = ""
    choices: tuple[str, ...] = ()
    on_value: str = "1"
    file_filter: str = "All Files (*)"

    @property
    def default_value(self) -> str:
        """Value a freshly added variable starts with: a flag is added to be
        switched ON; everything else starts empty."""
        return self.on_value if self.kind is VariableKind.FLAG else ""


_LIST, _DIR, _FILE = VariableKind.PATH_LIST, VariableKind.PATH, VariableKind.FILE
_FLAG, _CHOICE, _VALUE = VariableKind.FLAG, VariableKind.CHOICE, VariableKind.VALUE


def _v(name: str, kind: VariableKind, description: str, **details) -> VariableSpec:
    return VariableSpec(name=name, kind=kind, description=description, **details)


# (group title, its variables) — dropdown order = this order.
_CATALOG: tuple[tuple[str, tuple[VariableSpec, ...]], ...] = (
    ("Search paths", (
        _v("MAYA_MODULE_PATH", _LIST, "Folders searched for module (.mod) files — the usual way to add "
                                      "a tool with its plug-ins, scripts and icons."),
        _v("MAYA_PLUG_IN_PATH", _LIST, "Folders searched for plug-ins; they also show in the Plug-in Manager."),
        _v("MAYA_SCRIPT_PATH", _LIST, "Folders searched for MEL scripts."),
        _v("PYTHONPATH", _LIST, "Folders searched for Python modules. Maya Gate adds msl_tools to it "
                                "at every launch."),
        _v("MAYA_SHELF_PATH", _LIST, "Folders shelves are loaded from."),
        _v("XBMLANGPATH", _LIST, "Folders searched for icons, shelf button icons included."),
        _v("MAYA_PRESET_PATH", _LIST, "Folders with presets — each is the folder above an attrPresets folder."),
        _v("MAYA_CUSTOM_TEMPLATE_PATH", _LIST, "Folders with custom Attribute Editor / Node Editor templates."),
        _v("MAYA_CONTENT_PATH", _LIST, "Content folders listed on the Content Browser’s Examples tab."),
        _v("MAYA_TOOLCLIPS_PATH", _LIST, "Folders searched for ToolClip content."),
    )),
    ("Folders", (
        _v("MAYA_APP_DIR", _DIR, "Your Maya user folder (preferences, scripts, projects) instead of "
                                 "Documents\\maya."),
        _v("MAYA_ENV_DIR", _DIR, "Folder Maya.env is read from, instead of the default one."),
        _v("MAYA_PROJECT", _DIR, "Project folder opened at startup."),
        _v("MAYA_PROJECTS_DIR", _DIR, "Default folder for projects."),
        _v("MAYA_LOCATION", _DIR, "Maya’s install folder. Maya sets it itself — change it only if "
                                  "you know why."),
        _v("TEMP", _DIR, "Folder for temporary files (Windows’ own variable; Maya uses it too)."),
        _v("MAYA_WINDOWS_CRASH_LOG_DIR", _DIR, "Folder Maya writes crash files to, instead of the temp folder."),
    )),
    ("Startup & interface", (
        _v("MAYA_NO_HOME", _FLAG, "Skips the Home screen: Maya opens straight into its interface."),
        _v("MAYA_NO_HOME_ICON", _FLAG, "Hides the Home icon; the menus go back to their usual place."),
        _v("MAYA_UI_LANGUAGE", _CHOICE, "Interface language, whatever the system language is.",
           choices=("en_US", "ja_JP", "zh_CN")),
        _v("MAYA_OVERRIDE_UI", _VALUE, "MEL file Maya loads for its layout instead of initialLayout.mel."),
        _v("MAYA_DISABLE_BACKSPACE_DELETE", _FLAG, "The Backspace key no longer deletes."),
        _v("MAYA_FORCE_PANEL_FOCUS", _FLAG, "On stores 0: a viewport no longer takes keyboard focus when "
                                            "Shift is pressed.", on_value="0"),
        _v("MAYA_DISABLE_PLUGIN_SCENE_MODIFIED_WARNING", _FLAG, "No warning when loading a plug-in changes "
                                                                "the scene."),
        _v("MAYA_DISABLE_CIP", _FLAG, "No Customer Involvement Program at startup (can make Maya start faster)."),
        _v("MAYA_DISABLE_CER", _FLAG, "No Customer Error Reporting window after a crash."),
        _v("MAYA_DISABLE_CLIC_IPM", _FLAG, "No in-product licensing messages (can make Maya start faster)."),
        _v("MAYA_DISABLE_ADP", _FLAG, "Opts out of analytics when Maya runs in batch mode."),
    )),
    ("Python & scripts", (
        _v("MAYA_SKIP_USERSETUP_PY", _FLAG, "Maya runs NO userSetup.py at all — the script on Maya Gate’s "
                                            "userSetup tab included."),
        _v("MAYA_PYTHON_USER_PACKAGES_PRIORITY", _FLAG, "Python packages in your user site folder load before "
                                                        "Maya’s own."),
        _v("PYTHONDONTWRITEBYTECODE", _FLAG, "Python writes no .pyc files (no __pycache__ folders)."),
        _v("MAYA_SCRIPT_EDITOR_STDOUT", _FLAG, "Script Editor output is also written to the Output Window."),
        _v("MAYA_CMD_FILE_OUTPUT", _FILE, "File the Script Editor’s output is written to, from startup on.",
           file_filter="Log files (*.log *.txt);;All Files (*)"),
    )),
    ("Viewport", (
        _v("MAYA_VP2_DEVICE_OVERRIDE", _CHOICE, "Rendering engine of Viewport 2.0 (DirectX 11 / OpenGL).",
           choices=("VirtualDeviceDx11", "VirtualDeviceGL", "VirtualDeviceGLCore", "VirtualDeviceGLCoreCompat")),
        _v("MAYA_OGS_GPU_MEMORY_LIMIT", _VALUE, "Viewport 2.0 GPU memory limit, in MB."),
        _v("MAYA_VP2_PAUSE_ON_STARTUP", _FLAG, "Viewport 2.0 starts paused."),
        _v("MAYA_ALLOW_OPENGL_REMOTE_SESSION", _FLAG, "Allows the OpenGL Core Profile over Remote Desktop "
                                                      "(NVIDIA cards)."),
        _v("MAYA_ENABLE_MULTI_DRAW_CONSOLIDATION", _CHOICE, "Viewport 2.0 MultiDraw consolidation mode "
                                                            "(see Maya’s help for 0 / 1 / 2).",
           choices=("0", "1", "2")),
    )),
    ("Color management", (
        _v("OCIO", _FILE, "OpenColorIO configuration file to use.",
           file_filter="OCIO config (*.ocio);;All Files (*)"),
        _v("MAYA_COLOR_MANAGEMENT_POLICY_FILE", _FILE, "Color management preferences file loaded at startup.",
           file_filter="Policy files (*.xml);;All Files (*)"),
        _v("MAYA_COLOR_MANAGEMENT_POLICY_LOCK", _FLAG, "Locks the color management preferences set by the "
                                                       "policy file."),
        _v("MAYA_COLOR_MGT_NO_LOGGING", _FLAG, "No OpenColorIO messages in the output."),
    )),
    ("Scenes & rendering", (
        _v("MAYA_FORCE_REF_READ", _FLAG, "References are always read from disk, never from cached copies."),
        _v("MAYA_MULTI_SKIN_CLUSTER", _FLAG, "Several skinClusters on one mesh are allowed by default."),
        _v("MAYA_ALLOW_REFERENCED_CAMERA_SEQUENCER", _FLAG, "Shots connect to Camera Sequencer nodes of "
                                                            "referenced files (the older behavior)."),
        _v("MAYA_RENDER_SETUP_GLOBAL_TEMPLATE_PATH", _DIR, "Shared folder of Render Setup templates."),
        _v("MAYA_RENDER_SETUP_GLOBAL_PRESETS_PATH", _DIR, "Shared folder of Render Settings presets."),
        _v("MAYA_RENDER_SETUP_INCLUDE_ALL_LIGHTS", _CHOICE, "Whether render layers include all lights "
                                                            "automatically (1) or not (0).", choices=("0", "1")),
        _v("MAYA_CER_INCLUDE_SCENE_NAME", _CHOICE, "Whether crash reports sent to Autodesk carry the scene "
                                                   "file’s name (see Maya’s help for 0 / 1 / 2).",
           choices=("0", "1", "2")),
    )),
)

# Offered by earlier versions, but not found in Maya itself: no longer in the
# dropdown; a config that still has them keeps their folder-list editor.
_LEGACY: tuple[VariableSpec, ...] = (
    VariableSpec("MAYA_SHADER_PATH", _LIST),
    VariableSpec("MAYA_ICON_PATH", _LIST),
)

GROUPS: tuple[tuple[str, tuple[VariableSpec, ...]], ...] = tuple(
    (title, tuple(VariableSpec(**{**spec.__dict__, "group": title}) for spec in specs))
    for title, specs in _CATALOG)

_KNOWN: dict[str, VariableSpec] = {spec.name: spec for _title, specs in GROUPS for spec in specs}
_BY_NAME: dict[str, VariableSpec] = {**{spec.name: spec for spec in _LEGACY}, **_KNOWN}

KNOWN_VARIABLES: list[str] = list(_KNOWN)


def spec_of(name: str) -> VariableSpec:
    """What is known about variable `name`; an unknown (custom) variable
    comes back as a PATH with no description."""
    return _BY_NAME.get(name) or VariableSpec(name=name)


def kind_of(name: str) -> VariableKind:
    """Kind of variable `name`; unknown (custom) variables count as PATH."""
    return spec_of(name).kind


def launch_values(variables: Mapping[str, str]) -> dict[str, str]:
    """The variables to actually pass to Maya: those with a value. An empty
    one — a flag switched off, a choice not made, a field left blank — is
    left out, so Maya sees it as not set."""
    return {name: value for name, value in variables.items() if str(value).strip()}
