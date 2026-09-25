# msl_tools — project context for Claude Code

Read this before touching anything. It captures architecture, conventions,
and current state accumulated over a planning/build session in claude.ai
that this file hands off from. Docstrings and this file are English
regardless of chat language, per project convention.

## What this is

`msl_tools` — a PySide6 + Maya pipeline toolkit with a custom "atomic
design" UI framework (atoms → compositions → windows), built by
msl.Mironov (lead animator / animation-team lead). Repo:
https://github.com/MironovMSL/msl_tools

## Repo layout

```
msl_tools/                 (repo root)
    CLAUDE.md                this file
    setup_drag_drop_maya.py  drag-and-drop into Maya's viewport → runs the package installer
    configs/                runtime config output (JsonConfig files land here),
                            split into core/ and maya/<tool_name>/
    logs/
    msl/
        run_hub.py            standalone entry point for the desktop hub
        assets/               icons/, themes/ — SVG assets, sparse right now
        core/                 Qt-FREE layer: config, fs, logger, process_launcher,
                              environment, theme, version, installer, network,
                              resources.py (core.Resources singleton)
        ui/                   Qt-DEPENDENT layer: qt_bindings shim, icon_manager,
                              ui_resources.py (UiResources singleton), theme/,
                              widgets/ (atoms/, compositions/, windows/, app/)
        tools/                DCC-specific instruments
            desktop/            NEW: tools that run as part of the desktop hub
                maya_gate/        fully ported Maya Gate tool (see below)
                stub_a/, stub_b/  placeholder tools used to test hub navigation
            maya/               existing Maya-side tools (installer, etc.)
```

## Hard conventions (violate these and it won't match the rest of the codebase)

- **All Qt imports go through the shim**: `import msl_tools.msl.ui.qt_bindings as qt`,
  then `qt.QtWidgets.X` / `qt.QtCore.X` / `qt.QtGui.X`. Never `from PySide6 import ...` directly.
- **Docstrings in English**, always, regardless of chat/commit language.
- **Three-layer split**: `core/` never imports Qt. `ui/` is Qt-dependent, generic,
  reusable presentation (no DCC-specific logic). `tools/` is where DCC-specific
  instruments live, built out of `ui/` atoms/compositions.
- **Atomic design under `ui/widgets/`**: `atoms/` = smallest reusable pieces
  (one class, no dependency on other custom widgets), grouped in subfolders by
  kind (`checkboxes/`, `toggles/`, `header/`, `paths/`, `buttons/`, `comboboxes/`,
  `progress/`, `status/`, `surfaces/`). `compositions/` = things built out of
  atoms, still generic/reusable, not tied to one tool. `windows/` = top-level
  window types (`FramelessWindowMixin`, `FramelessDialog`, `FramelessMainWindow`,
  and now `hub/`). A tool-specific composition (only that one tool would ever
  use it) goes under `tools/<...>/`, NOT `ui/widgets/compositions/`.
- **Naming**: no `Q`-prefix, no "Custom" in class names (both read as if they
  were part of Qt itself, or say nothing). `BaseX` for things meant to be
  reused/extended broadly (`BaseCheckbox`, `BaseToggle`, `BaseNavButton`,
  `BaseComboBox`). Plain descriptive names otherwise (`VersionStatusWidget`,
  `ApplicationButton`).
- **No hidden I/O in constructors.** Widgets that need data get it lazily or
  take it as a constructor argument from a caller that already fetched it.
- **Theming**: plain controls (QPushButton, QLineEdit, QComboBox) are styled
  for free by `StylesheetBuilder`'s global QSS baseline, applied per-window
  (never `QApplication`-wide — inside Maya, the QApplication is Maya's own).
  Only STATE-DRIVEN custom-painted atoms (BaseCheckbox, BaseToggle,
  BaseProgressBar, ApplicationButton's label) carry their own `set_theme()`
  and take `theme: Theme | None = None` defaulting to `ThemeRegistry.fallback()`
  (no file I/O).
- **Icons**: `UiResources().iconManager.get_icon(name, sub_folder=None, color=None)`.
  SVGs need a literal `#000000` placeholder for runtime color substitution.
  msl_tools' asset bundle currently only has window-chrome icons
  (close/maximize/minimize/restore) — add/delete/copy/drag icons do NOT
  exist yet. Several new widgets below use plain Unicode characters as a
  stand-in ("×", "⧉", "⋮⋮", "˄"/"˅") — swap for real IconManager-resolved
  icons once real SVG assets are added.
- **Config**: `Resources().configsCoreMng` / `Resources().configsMayaMng` are
  the two `ConfigManager` instances (`msl/core/resources.py`). Maya tools use
  `configsMayaMng.get_config("<tool_name>", defaults={...})`, which returns a
  `JsonConfig`/`ConfigNode` (MutableMapping, supports `move_key_left`/
  `move_key_right`/`reorder_keys`, detached-node pattern so reads don't
  create phantom keys).
- **Testing widgets**: use `ThemedWidgetPlaygroundDialog`
  (`ui/widgets/themed_widget_playground_dialog.py`) in a file's
  `if __name__ == "__main__":` block, NOT the older
  `WidgetPlaygroundDialog` — it's `FramelessDialog`-based with a live
  theme toggle in the header; any added widget exposing `set_theme()` gets
  re-themed on every toggle automatically.

## Current initiative: the desktop hub

Goal: replace the standalone `MSL_MayaGate`/`MSL_MayaLauncher` repo (a
separate, already-working PySide6 app) with one general, extensible
"hub" desktop app — a single desktop shortcut — that lists tools in a
sidebar (Maya Gate among them, more tools added over time). The hub
NEVER runs inside Maya; it's a pure standalone desktop app. Future
(unimplemented) plan: connect to a running Maya session over
`cmds.commandPort` from Maya's own `userSetup`, not by sharing a process.

### Hub architecture

- `msl/ui/widgets/windows/hub/` — `HubWindow(FramelessDialog)` + `ToolDescriptor`
  (a frozen dataclass: `id`, `title`, `widget_factory: Callable[[], QWidget]`).
  Built on `FramelessDialog`, not `FramelessMainWindow` — the hub only needs a
  title bar + one content area (`add_widget()`), which `FramelessDialog`
  already gives; `FramelessMainWindow` (menu bar/toolbar/status bar) is
  unused so far, and untested in practice.
  Sidebar uses plain `QPushButton`s for now — `BaseNavButton` is built for
  the header's icon-only fixed-width/expanding-height row and draws no
  text, so it isn't a fit for a labeled vertical list without a subclass.
- `msl/tools/desktop/registry.py` — `TOOLS: list[ToolDescriptor]`, one import
  + one line per tool. The hub iterates this and knows nothing about any
  individual tool.
- `msl/run_hub.py` — the only place a `QApplication` gets created
  for the hub, via `QtApplicationContext`.

### Maya Gate — fully ported from MSL_MayaGate

Location: `msl/tools/desktop/maya_gate/`. Entry: `TOOL_DESCRIPTOR` in
`maya_gate/__init__.py`, page assembled in `page.py` (`MayaGatePage`).

What changed vs. the original (all deliberate, not oversights):
- `MSL_MayaGate`'s own `core/` (Resources' Maya-path scan, Configurator/
  JsonConfig, ThemeManager, LauncherLogger) is NOT ported — msl_tools
  already has better equivalents: `ProcessLauncher.launch_maya(version=,
  environment=)`, `MayaPaths.get_available_installs()` /
  `get_executable_path()`, `Resources().configsMayaMng`, and the shared
  theme/logger systems. `MayaVersionRow` sorts `get_available_installs()`
  itself, since (unlike the original) it isn't pre-sorted.
- Theme combo box dropped entirely — the hub/window chrome already has a
  `SunMoonToggle` via `FramelessWindowMixin(show_theme_toggle=True)`.
- Several originally "generic" widgets directly wrote to a global
  `json_config` singleton or reached multiple `.parent()` calls up to poke
  a specific enclosing widget — both patterns removed. Generic pieces
  (`DraggableList`, `EnvVarRow` in
  `ui/widgets/compositions/`) only emit signals; the config-aware owner
  (`CollapsibleVariableGroup`, tool-specific) listens and persists.
- `MayaVersionRow.clicked` emits the selected YEAR (str), not an
  executable path — `ProcessLauncher.launch_maya(version=...)` resolves
  the path itself, so the row no longer needs to hand one out.
- `EnvVariableAdder`'s known-vs-custom routing is preserved exactly: a
  variable picked from the known-variables dropdown goes into the
  CURRENTLY SELECTED environment section; a freeform typed variable
  always goes into the fixed "Additional" section — this is real routing
  from the original, not just a label.
- Window-resize-on-content-change was intentionally NOT ported (the
  original chained `.update_size()` calls up to its own standalone
  top-level window). Maya Gate is now one page inside the hub's
  fixed-size dialog, not its own window — the advanced editor is wrapped
  in its own `QScrollArea` instead.
- `CollapsibleVariableGroup.set_advanced_visible(bool)` replaces the
  original's `environment_vis` attribute, which was read once at
  construction and then poked directly from outside on every toggle (a
  stale-on-toggle bug waiting to happen).

- One scroll area for the whole advanced editor (no per-group scroll, no row
  cap); groups fold via their header instead. Fold state is persisted under
  the `_ui` key of the `maya_gate` config — never merged into a launch
  environment (`_launch` reads named sections only).

Files:
```
maya_gate/
    __init__.py          TOOL_DESCRIPTOR
    page.py               MayaGatePage — assembles everything below
    toolbar.py             MayaGateToolbar (year + environment + advanced toggle)
    version_row.py         MayaVersionRow (animated row of installed versions)
    variable_group.py      CollapsibleVariableGroup (config-aware, owns persistence)
    variable_adder.py      EnvVariableAdder (known/custom variable input row)
```

New generic pieces added to `ui/widgets/` along the way:
```
atoms/buttons/application_button.py          ApplicationButton (was ApplicationButtonWdg)
atoms/comboboxes/base_combo_box.py        BaseComboBox (was QCustomComboBox)
atoms/surfaces/stable_scroll_area.py      StableScrollArea (scroll-bar column always reserved, bar hidden when not needed, so content never shifts)
compositions/draggable_list.py            DraggableList (generic drag-reorder list)
compositions/env_var_row.py               EnvVarRow (copy/up/down/delete controls inline, shown on row hover)
themed_widget_playground_dialog.py        ThemedWidgetPlaygroundDialog
```

Bug fixes made to EXISTING framework files along the way (not new code):
- `ui/widgets/windows/frameless_dialog.py`: `add_separator()` referenced
  `self.content_layout`, which doesn't exist on `FramelessDialog` (only on
  `BaseDialog`) — fixed to route through `self.add_widget()`.
- `ui/theme/stylesheet_builder.py`: added `_combo_box_style()` (QComboBox
  had no baseline QSS at all — wired into `build()`). First pass, to be
  tuned later; the dropdown arrow is a border-drawn triangle stand-in
  until a real SVG arrow asset exists.

Gotcha worth knowing before subclassing `FramelessDialog`/
`FramelessMainWindow` and overriding `_apply_theme()`: any state that
override reads must be set BEFORE calling `super().__init__()`, since the
base class's `__init__()` calls `self._apply_theme()` synchronously at the
end of its own construction — reaching the subclass's override before the
subclass's own `__init__` body finishes.

## Verified so far

Everything above was smoke-tested in an offscreen Qt session (no display,
no Maya installed) — imports, construction, and BEHAVIOR (drag-reorder,
value edits, section switching, add/remove, EnvVariableAdder's routing)
all confirmed working against a real `ConfigManager`-backed JsonConfig on
disk. NOT yet tested: against a real Maya installation (actual launch via
`ProcessLauncher.launch_maya`), or in the real GUI (only offscreen).

## Not done yet / open threads

- The hub / Maya Gate work is in the working tree (mostly staged) but
  not committed yet.
- Persisting the last-picked year/environment across restarts (currently
  always starts at the earliest installed year + "Dev").
- Real icon assets for add/delete/copy/drag (currently Unicode placeholders).
- The `cmds.commandPort`-based Maya connection (future work, unstarted).
- Hub sidebar styling (plain QPushButton placeholders, not a themed nav button).
