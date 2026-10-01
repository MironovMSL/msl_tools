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
    setup_express_launcher.bat  double-click setup: finds Python, prepares the runtime, opens the setup window
    requirements.txt         what the hub's Python environment gets (PySide6-Essentials)
    configs/                runtime config output (JsonConfig files land here),
                            split into core/, maya/<tool_name>/ (Maya-side tools)
                            and desktop/<tool_name>/ (the hub: hub/, maya_gate/)
    logs/                   same split: logs/maya/, logs/desktop/<tool_name>/
                            configs/ and logs/ are per-user and NOT in git
                            (.gitignore): both are created on first run, so
                            every default must come from code (get_config
                            defaults, UserSetupStore.DEFAULT_SCRIPT), never
                            from a committed config file.
    msl/
        run_hub.py            standalone entry point for the desktop hub
        run_installer.py      standalone entry point of the setup window (run by path, see "Install")
        assets/               icons/, themes/ — SVG assets, sparse right now
        core/                 Qt-FREE layer: config, fs, logger,
                              environment, theme, version, installer, network,
                              resources.py (core.Resources singleton)
                              (known Qt leftovers: config/ini_config.py uses QSettings,
                              fs/qt_paths.py imports Qt lazily)
        ui/                   Qt-DEPENDENT layer: qt_bindings shim, icon_manager,
                              ui_resources.py (UiResources singleton), theme/,
                              process_launcher/ (ProcessLauncher — QProcess-based, so ui/, not core/),
                              widgets/ (atoms/, compositions/, windows/, app/)
        tools/                DCC-specific instruments
            desktop/            NEW: tools that run as part of the desktop hub
                maya_gate/        fully ported Maya Gate tool (see below)
                installer/        InstallerView — the setup window (not a hub tool, not in the registry)
                stub_a/, stub_b/  placeholder tools used to test hub navigation
            maya/               existing Maya-side tools (the MSL menu, etc.)
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
- **Theming**:
  - Colors live ONLY in palette files `msl/assets/themes/<name>.css`
    (`:root { --accent: #2f7dd1; }` — CSS so editors show swatches/picker;
    theme name = file name; parsed by `core/theme/palette.py`). A palette may
    omit tokens — they come from `light.css`. No colors in Python code.
  - Surfaces are layered by role (documented at the top of `light.css`):
    `chrome-background` (frame/sidebar) · `surface` (page card, dialogs) ·
    `surface-raised` (panels on the page — variable groups —, menus, combo
    popups) · `field` (line edits, combos, check boxes) ·
    `editor-background` (CodeEditor's writing area) · `button-top/-bottom`
    (+ `-hover`: push buttons' top-lit gradient) · `primary-top/-bottom`
    (accent gradient of a primary button) · `on-accent` (text/marks on an accent
    fill — never `surface` for that). New widgets pick the token by role,
    so both themes keep their contrast without per-widget colors.
  - `Theme` fields = tokens Python widgets read (`--text-primary` ->
    `theme.text_primary`); `theme.tokens` = every palette declaration. A
    color used only in QSS needs just a palette line, no `Theme` change.
  - Push buttons (base.qss): raised top-lit gradient; hover = brighter +
    accent border; pressed = gradient flipped (pushed in). Variants:
    `setProperty("primary", True)` = accent gradient for a dialog's one main
    action (ConfirmDialog's first choice); `setFlat(True)` = borderless,
    transparent until hovered, no padding (use sparingly: a borderless "+"
    didn't read as clickable — the adder's "+" are framed IconPushButtons
    with `actions/add`, 24x22 like their fields).
  - Line edits (base.qss): sunken — a faint top shade (`--field-top`)
    fading into `--field`; hover = border half-way to the accent, focus =
    accent (and flat); placeholder = `placeholder-text-color` (QSS, Qt 6.5+).
    Fields, combo boxes, buttons are all 22px high so rows line up. An
    editable combo's inner QLineEdit gets no border/hover/focus of its own.
    Editable combo boxes (`QComboBox:editable`) look like line edits
    (sunken, same hover/focus); selector combos stay raised like buttons.
  - Code editor (CodeEditor, widgets.qss): syntax colors from the palettes'
    `--syntax-*` tokens (keyword, constant, self, builtin, function,
    decorator, string, number, comment — after VS Code Dark+/Light+; no bold,
    italic comments); font = first installed of Cascadia Mono / JetBrains
    Mono / Consolas; the line-number gutter is ruled off by a divider;
    focus = accent border like a line edit; translucent selection.
  - Segmented control (`SegmentedControl`, widgets.qss): sunken track
    (`--segment-track-top/-track`), raised pill (`--segment-pill-top/-pill`)
    that slides to the picked option; keyboard focus is deliberately not
    drawn (an accent border on a mere click was confusing). For a handful of often-switched
    options (Maya Gate's environments); long lists stay combo boxes.
  - Tabs: underline style (base.qss); hovering a tab lays a soft rounded
    tint under it. `BaseTabWidget` / `BaseTabBar` (atoms/tabs/) paint the
    accent indicator themselves so it SLIDES to the new tab and stretches
    to its width (qproperty indicatorColor; widgets.qss drops the static
    QSS underline for BaseTabBar). Maya Gate's tabs use BaseTabWidget.
  - Check boxes: unchecked = sunken like a line edit, checked = the primary
    button's gradient + a check. `BaseCheckbox` paints it (qproperty boxColor
    / boxTopColor / borderColor / hoverBorderColor / fillColor / fillTopColor
    / checkmarkColor / textColor; the fill grows from the center, the border
    melts into it, the checkmark is drawn in; disabled = dimmed); plain
    QCheckBox gets the same look from base.qss (`actions/check` via icon()).
  - Plain controls (QPushButton, QLineEdit, QComboBox, ...) are styled by the
    template `msl/ui/theme/base.qss` — rules use `var(--token)` and
    `alpha(<color>, N%)` and CSS `linear-gradient(to bottom, <c1>, <c2>)`
    (-> qlineargradient; write gradients this way — Qt's own
    `qlineargradient(x1:0, ...)` is a syntax error for PyCharm, which
    parses .qss as CSS here), and `icon(<sub_folder/name>, <color>)` ->
    `url(<file>)` (an assets/icons SVG recolored with a theme color, cached
    in %TEMP%/msl_tools/qss_icons — for sub-control images like
    `QComboBox::down-arrow`, which QSS only takes from a file);
    `StylesheetBuilder.build(theme)` resolves them
    (unknown token -> warning + `transparent`). Applied per-window, never
    `QApplication`-wide (inside Maya, the QApplication is Maya's own). No
    blanket `QWidget { background }` rule — nested containers must stay
    transparent.
  - Custom widgets take colors from QSS, not from a Theme object (atoms,
    compositions and tools done; there are NO set_theme() forwarding chains
    anymore — only windows listen to `theme_changed` and re-apply QSS):
    - a custom-painted widget declares each color as a Qt property with
      `ui/theme/qss.py:color_property()`; `ui/theme/widgets.qss` sets it
      (`GlyphButton { qproperty-glyphColor: var(--text-secondary); }`).
      Qt re-applies qproperty-* whenever the window stylesheet changes, so
      theme switches and hot reload need no set_theme() chain.
    - state that changes colors = a dynamic property selected in QSS
      (`BaseProgressBar[state="error"]::chunk`, `QLabel#versionStatus[status=...]`);
      call `repolish(widget)` after changing it.
    - QSS can't animate. A property that should change smoothly (the
      scroll-bar handle widening 4px -> 6px over the bar) is painted by the
      widget (`SlimScrollBar`), with its colors still from qproperty-*.
      Also: `::handle:hover` means "over the handle", and
      `QScrollBar:hover::handle` is mis-parsed by Qt — don't use it.
    - never set those colors from code — the next polish overwrites them.
    - widgets take NO `theme=` param and have NO `set_theme()`. Until the
      stylesheet applies (or outside a styled window) their color
      properties hold `ThemeRegistry.fallback()` colors (`_seed_colors()`).
      Don't reintroduce theme params/forwarding for new widgets — add a
      color property + a qproperty rule instead.
    - Tool-specific rules live with the tool: a tool registers its own
      template with `StylesheetBuilder.register_template(path)` at import
      (Maya Gate: `tools/desktop/maya_gate/maya_gate.qss`, registered in
      variable_group.py). Hot reload watches registered templates too.
    - Type selectors are Python class names and match subclasses.
    - OrbitThemeToggle/BaseToggle/SunMoonToggle draw fixed illustration
      colors (not theme tokens) — intentionally not migrated.
  - Hot reload (dev): `ThemeHotReloader` (ui/theme/) watches the palettes
    and every QSS template (incl. registered tool ones); on save it calls `ThemeManager.reload()`, which re-emits
    `theme_changed` for the current theme — so it refreshes exactly what a
    normal theme switch refreshes. `run_hub.py` turns it on in a git
    checkout; `MSL_THEME_HOT_RELOAD=0/1` overrides. Never enabled inside Maya.
  - Popups (QMenu, QMessageBox, other dialogs) are separate windows but
    inherit the window QSS when created WITH a parent inside a styled
    window — always pass one (`QMenu(self)`); a parentless popup stays
    native. Popups Qt creates parentless itself (QCompleter.popup() —
    setPopup() detaches it) go through `ui/theme/qss.py:adopt_popup(popup,
    parent)`: re-parenting alone keeps the native white look, adopt_popup
    also forces Qt to resolve the style again. Rules for them are in base.qss. Don't put `min-width` on
    QMessageBox buttons: it pins every button to that width and clips text.
    Rounded popups: a popup is an OS window (always a rectangle), so QSS
    `border-radius` alone leaves square corners — pass the popup through
    `ui/theme/qss.py:make_rounded_popup()` (frameless + translucent, no
    native shadow, Fusion base style) and the QSS radius shows. The Fusion
    base matters: Qt 6.7+'s default "windows11" style paints its own shadow
    into a QMenu's bottom-right corner, ignoring QSS (a dark notch). For questions use
    `ui/widgets/windows/confirm_dialog.py:ConfirmDialog.ask()` (FramelessDialog-
    based, rounded + themed; first choice = accent primary) instead of
    QMessageBox, whose native frame can't be rounded or themed. `kind=`
    "question" / "warning" / "danger" sets a tone badge (ToneBadge: ? ! ×
    in --accent / --warning / --danger) and, for "danger", a red primary
    (`QPushButton[primary="true"][danger="true"]`) — and there Enter means
    the LAST choice (cancel), so a stray Enter never destroys anything;
    ask() blurs a frameless parent window (`set_blurred`) while it's open.
  - Window buttons (header minimize / maximize / close, `BaseNavButton` /
    `CloseNavButton`) are migrated: the windows only hand them icon SHAPES
    (window/*.svg); colors are qproperty iconColor / hoverIconColor /
    hoverColor / pressedColor in widgets.qss (close = `--danger` /
    `--danger-pressed`, white `--on-danger` icon).
  - Not migrated, deliberately: the rest of the window layer (the window /
    content-surface backgrounds in FramelessDialog/FramelessMainWindow
    `_apply_theme`, the theme toggle's colors, SnapLayoutFlyout — a separate
    top-level window the window's QSS doesn't cascade into) and
    DraggableList's drop indicator (fixed, non-theme colors).
- **Icons**: `UiResources().iconManager.get_icon(name, sub_folder=None, color=None)`.
  - Layout: `msl/assets/icons/<category>/<name>.svg`, names in snake_case,
    named by what the icon IS, not the gesture (`drag_handle`, not
    `dragAndDrop`). Categories: `window/` (chrome: close/maximize/...),
    `actions/` (row/toolbar actions: `drag_handle`, `copy`, `delete`,
    `browse`, `folder_add`, `clear`, `arrow_right`, `chevron_down`, `add`, `check`, `select_all`; add new action icons here),
    `apps/` (third-party application logos: `maya`; later houdini, blender...
    — named after the app, not the tool that uses it, so several tools can
    share one), `tools/` (sidebar icons of our OWN hub tools, one-color like
    action icons: `cube`, `layers` — the stub tools' placeholders), `brand/` (our own app icons: `hub` — an "M" monogram, full-color, NOT the
    #000000 one-color convention: used as the window/taskbar icon, never
    tinted). Per-theme variants only when the SHAPE
    differs: `<name>_dark.svg` / `<name>_light.svg`.
  - SVGs use a literal `#000000` as their color (placeholder for
    `color=` substitution).
  - Icons in buttons are ONE-COLOR shapes tinted from QSS via
    `ui/icon_manager.py:tint_icon()` — no `color=`, no per-theme files:
    `GlyphButton.set_icon()` (borderless; glyph colors idle/hover/disabled)
    and `IconPushButton` (framed QPushButton; `qproperty-iconColor`). Use
    monochrome 24-grid SVGs, `stroke-width="2"`, color `#000000`.
  - In use: drag_handle + browse (EnvVarRow), copy (EnvVarRow name +
    CopyableLineEdit), delete / arrow_right (bulk delete / copy-to),
    clear (BulkActionBar). Each call site keeps a Unicode glyph / text as
    fallback if the file is missing. Icons are cached at startup — hot
    reload doesn't pick up SVG edits, restart the hub.
- **Config**: `Resources().configsCoreMng` / `configsMayaMng` /
  `configsDesktopHubMng` are the `ConfigManager` instances
  (`msl/core/resources.py`); loggers likewise `logs` / `logsMaya` /
  `logsDesktopHub`. Maya-side tools use `configsMayaMng`, hub tools (never
  inside Maya) `configsDesktopHubMng` + `logsDesktopHub.get("<tool_name>")`.
  `get_config("<tool_name>", defaults={...})` returns a
  `JsonConfig`/`ConfigNode` (MutableMapping, supports `move_key_left`/
  `move_key_right`/`reorder_keys`, detached-node pattern so reads don't
  create phantom keys).
- **Testing widgets**: use `ThemedWidgetPlaygroundDialog`
  (`ui/widgets/themed_widget_playground_dialog.py`) in a file's
  `if __name__ == "__main__":` block, NOT the older
  `WidgetPlaygroundDialog` — it's `FramelessDialog`-based with a live
  theme toggle in the header; added widgets re-theme through the window
  stylesheet like everywhere else.

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
  (a frozen dataclass: `id`, `title`, `widget_factory: Callable[[], QWidget]`,
  optional `icon` + `icon_sub_folder` for the sidebar entry — Maya Gate:
  `icon="maya", icon_sub_folder="apps"`).
  Built on `FramelessDialog`, not `FramelessMainWindow` — the hub only needs a
  title bar + one content area (`add_widget()`), which `FramelessDialog`
  already gives; `FramelessMainWindow` (menu bar/toolbar/status bar) is
  unused so far, and untested in practice.
  Two visual zones (Zoom-style): the sidebar sits on the window chrome
  (`chrome-background`, same as the title bar); the page sits on a rounded
  `BasePanel` card (`surface`) — HubWindow._apply_theme makes
  FramelessDialog's own content surface transparent and colors the card.
  Header: breadcrumb "MSL Tools › <open tool>" (`WindowHeader.set_subtitle`,
  set on every tool switch); icon + title stay at the window's left edge.
  Header title / subtitle fonts live in base.qss (`QLabel#headerTitle` /
  `#headerSubtitle`).
  Sidebar entries are checkable `IconTileButton#hubNavButton` tiles (Zoom-
  style: 20px icon on top, 11px label under it; sidebar 76px wide) styled in
  `widgets.qss` (checked entry = card color, subtle `--nav-*` gradient).
  The open tool's pill is painted by `HubSidebar` UNDER the tiles and
  slides to a newly opened tool (qproperty pillTopColor / pillColor /
  pillEdgeTopColor / pillEdgeBottomColor from --nav-*); the checked tile
  itself is transparent. `footer_text` (run_hub: `v{msl.__version__}`) is a
  quiet text button at the sidebar's bottom (`QPushButton#hubFooter`);
  clicking it emits `footer_clicked` — run_hub opens "What's new".
  Icons are tinted from QSS: `--text-secondary`, and `--text-primary`
  on the open tool via the dynamic property `current="true"` (qproperty-*
  is only applied from rules without pseudo-states, so not `:checked`).
  The first tool opens on start.
  `BaseNavButton` isn't used: it's built for the header's icon-only row.
  Window size: the START size is `width=900, height=600` in
  HubWindow.__init__ (then run_hub restores the saved placement). The
  MINIMUM is not a number anywhere — FramelessWindowMixin's own floor is
  `_MIN_WIDTH/_MIN_HEIGHT` (240x160), the real limit is the layout's
  minimum, i.e. the widest thing on any tool page (~554px now: Maya Gate's
  toolbar / variable adder row). One long non-wrapping QLabel sets it for
  the whole window — make hint lines `setWordWrap(True)`. StableScrollArea
  reports its content's minimum width (it never scrolls sideways), so
  scrolled content can't be cut off by narrowing the window.
- `msl/tools/desktop/registry.py` — `TOOLS: list[ToolDescriptor]`, one import
  + one line per tool. The hub iterates this and knows nothing about any
  individual tool.
- `msl/run_hub.py` — the only place a `QApplication` gets created
  for the hub, via `QtApplicationContext`. It passes the `brand/hub` icon to HubWindow
  (header + OS window icon: FramelessWindowMixin sets both) and gives the
  process its own Windows AppUserModelID, so the taskbar shows that icon,
  not python.exe's. It also owns the hub's own
  config (`configsDesktopHubMng` "hub": `current_tool`, `window`): HubWindow
  stays storage-agnostic — `current_tool_id=` in, `tool_changed(str)` out.
  Window placement: first start = default; on close (`finished`) it stores
  `normal_geometry()`, next start calls `restore_normal_geometry()` — both
  on `FramelessWindowMixin`, so any frameless window can remember itself.
  Maximized/snapped state isn't kept (the un-maximized rect is); a rect
  whose header is on no screen is ignored, an oversized one is clamped.

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
- Version tiles (`ApplicationButton`): the whole tile (icon + name) is the
  target — hover = shake (kept from the original) + a soft card (qproperty
  hoverColor / hoverBorderColor); no frame around the icon. After a click
  the tile is busy for BUSY_MS ("Starting…" in the accent, icon greyed,
  clicks ignored) so a double click can't launch Maya twice. Tooltips name
  the environment (`MayaVersionRow.set_environment()`, called by the page);
  no installs -> "No Maya installation found".
- Config: `configs/desktop/maya_gate/config.json` (moved from
  configs/maya/ — the hub is a desktop app). Layout, both variable
  branches the same shape: `"maya": {"<env>": {...}}`,
  `"custom": {"<env>": {...}}`, `"_ui": {year, environment, tab,
  collapsed}` (page state restored on start; a saved year is used only
  while that Maya is still installed; tab stored by key, not index).
- Variables are fully per-environment (changed from the original, where
  "Additional" was one global section applied to every environment):
  `"maya"."<env>"` = that environment's Maya variables,
  `"custom"."<env>"` = its custom ones. The Variables tab shows
  two `CollapsibleVariableGroup`s — "Maya Variables · <env>" and
  "Custom Variables · <env>" (the second is handed the `custom` branch as
  its config) — named after the two `EnvVariableAdder` inputs ("Maya
  variable…" dropdown → Maya group, "Custom variable…" field → Custom
  group), both in the CURRENT environment. Older layouts (Maya variables
  at the top level, "additional", `_ui.collapsed` "environment"/
  "additional") are moved over once by
  `MayaGatePage._migrate_legacy_config()`. Nothing is
  shared between environments — the "Copy to…" bulk action (➜) copies
  selected variables with values into another environment (conflicts:
  replace / skip / cancel; `copy_items_to()` is the non-interactive core).
  A shared "Common" layer was deliberately NOT added yet — add it only if
  the same variables keep getting copied everywhere.
- Browse button per variable kind (`maya_variables.py` → `EnvVarRow`
  `BrowseMode`, mapped in page.py): PATH_LIST vars (PYTHONPATH,
  MAYA_MODULE_PATH, ...) APPEND the picked folder with os.pathsep, skipping
  duplicates (folder_add icon) — replacing would silently drop the other
  entries; PATH vars and unknown/custom ones REPLACE (folder icon); VALUE
  flags (MAYA_DISABLE_CIP/CER/CLIC_IPM) have no browse button (space kept
  so fields stay aligned). EnvVarRow itself knows nothing about Maya.
- Window-resize-on-content-change was intentionally NOT ported (the
  original chained `.update_size()` calls up to its own standalone
  top-level window). Maya Gate is now one page inside the hub's
  fixed-size dialog, not its own window — the advanced editor is wrapped
  in its own `QScrollArea` instead.
- The original's "advanced" toggle (and its stale `environment_vis`
  attribute) is gone: the page has two always-visible tabs, "Variables"
  and "userSetup", both following the toolbar's environment. A group is
  visible whenever its section has variables.
- userSetup tab: one Python script per environment, stored as
  `configs/desktop/maya_gate/user_setup/<env>.py` (`UserSetupStore`, Qt-free).
  At launch a never-changing wrapper `user_setup/launch/<env>/userSetup.py`
  is prepended to PYTHONPATH — Maya runs EVERY userSetup.py on sys.path
  (checked in maya/app/startup/basic.py, 2020–2026), so the user's own
  Documents userSetup still runs. The wrapper exec()s the script inside
  try/except (Maya runs all userSetups in ONE try block, so ours must not
  raise) and never changes content, so Maya 2022+'s userSetup trust-hash
  prompt appears once, not after every edit. Must stay Python-2.7-valid
  (Maya 2020). Verified end-to-end with mayapy 2020 and 2025 standalone.
  Every launch also puts the folder holding the msl_tools package
  (`FileSystemManager.PARENT_DIR`) on PYTHONPATH — baked into
  `UserSetupStore.launch_environment()`, deliberately NOT a variable in the
  config (per-machine path; must not be editable away) — so scripts just
  `from msl_tools...`. A never-saved script reads as
  `UserSetupStore.DEFAULT_SCRIPT` = the 3-line `MENU_SNIPPET`
  (`from msl_tools.msl.startup import bootstrap; bootstrap()`), so a fresh
  install gets the msl menu in every environment; a script saved empty stays
  empty (not injected). "Insert MSL menu" restores the snippet and rewrites
  the old long form (the one that set MSL_PARENT_DIR / sys.path) via
  `upgrade_menu_snippet()`. Verified with mayapy 2026.
  The tab's status (`QLabel#userSetupStatus[state=...]`, maya_gate.qss)
  says where the script stands: "editing" while typing, then after each
  save / load "saved", "off" (blank — Maya starts without it) or "error"
  (`UserSetupStore.syntax_error()`; the line is marked in the editor with
  `CodeEditor.set_error_line()` — qproperty errorLineColor /
  errorNumberColor; the script is saved anyway). "Edited" means the TEXT
  differs from what's saved: QPlainTextEdit.textChanged also fires on a
  mere re-highlight (theme switch), which must not mark the script dirty.

- One scroll area for the whole Variables tab (no per-group scroll, no row
  cap); groups fold via their header instead. Fold state is persisted under
  the `_ui` key of the `maya_gate` config — never merged into a launch
  environment (`_launch` reads only `"maya"."<env>"` + `"custom"."<env>"`).
  Launches are logged to `logs/desktop/maya_gate/` (file: warnings+).
- Widgets in a `RowHoverMenu` never take keyboard focus: they hide when the
  pointer leaves the row, and a hidden focused widget passes focus to the
  row's line edit, which then selects all its text.
- Rows flag missing folders: a value (each entry of a PATH_LIST) that looks
  like a path but doesn't exist marks its field `pathState="missing"`
  (warning border, widgets.qss) and names the folder in the tooltip; path
  lists get a one-entry-per-line tooltip (✓/✗). Checked on a daemon thread
  (a row signal carries the result back; NOT a QThread — a row can be
  deleted mid-check), on first show and 400ms after edits. Empty values
  show an "empty" placeholder; copy buttons flash a check
  (`GlyphButton.flash_icon()`).
- Bulk bar: `set_count(selected, total)`; "select all" is built in (hidden
  once everything is selected); a destructive action is added with
  `add_action(..., danger=True)` -> `GlyphButton[danger="true"]`, red on
  hover (widgets.qss).
- Rows are selected via the hover-menu checkbox; removal is a BULK action
  only (no per-row delete button), reordering is drag-and-drop only. Bulk
  delete asks first — `ConfirmDialog` kind="danger" (no undo);
  `delete_items()` is the non-interactive core, like `copy_items_to()`.
  `CollapsibleVariableGroup` paints its own frame starting at
  `SELECTION_GUTTER`, so the drag-handle column reads as sitting outside the
  frame (Notion-style); the page indents other content by the same amount. New bulk operations go in
  `CollapsibleVariableGroup._build_bulk_actions()`. Theme changes need no
  forwarding: the rows, groups and editor are colored by the window QSS.
- Group look (maya_gate.qss): header = semibold title (`QLabel#groupTitle`),
  dimmed "· <env>" (`#groupSection`), row count as an accent pill
  (`#groupCount`); the group paints a hover tint over its header (it folds
  the group) and a divider under it while rows show (qproperty
  headerHoverColor / dividerColor). Rows (EnvVarRow) get a faint hover tint
  (qproperty hoverColor) under the accent selected tint.

Files:
```
maya_gate/
    __init__.py          TOOL_DESCRIPTOR
    page.py               MayaGatePage — assembles everything below
    toolbar.py             MayaGateToolbar (environment SegmentedControl on the left, "From <year>" filter combo on the right)
    user_setup.py          UserSetupStore (per-environment script files + launch PYTHONPATH wiring, Qt-free)
    user_setup_tab.py      UserSetupTab (CodeEditor for the script, debounced autosave)
    version_row.py         MayaVersionRow (animated row of installed versions)
    variable_group.py      CollapsibleVariableGroup (config-aware, owns persistence)
    variable_adder.py      EnvVariableAdder (known/custom variable input row)
    maya_variables.py      what each known Maya variable holds (PATH_LIST / PATH / VALUE) + the known list, Qt-free
```

New generic pieces added to `ui/widgets/` along the way:
```
atoms/buttons/application_button.py          ApplicationButton (was ApplicationButtonWdg)
atoms/buttons/icon_push_button.py         IconPushButton (framed button with a QSS-tinted one-color icon)
atoms/buttons/icon_tile_button.py         IconTileButton (QToolButton tile: QSS-tinted icon over a short label; icon-less tiles keep the icon row empty so a column stays aligned)
atoms/buttons/glyph_button.py             GlyphButton (custom-painted small icon button; QPushButton's QSS padding leaves no room for a glyph at ~20px)
atoms/comboboxes/base_combo_box.py        BaseComboBox (was QCustomComboBox)
atoms/editors/code_editor.py              CodeEditor (line numbers + gutter divider, Python highlighting from --syntax-* tokens, Tab/auto-indent)
atoms/segmented/segmented_control.py     SegmentedControl (one-of-few picker: sunken track, raised pill that slides; Left/Right keys)
atoms/tabs/base_tab_bar.py                BaseTabBar + BaseTabWidget (sliding accent indicator under the open tab)
atoms/scrollbars/slim_scroll_bar.py      SlimScrollBar (painted thin handle that widens smoothly on hover; used by StableScrollArea, CodeEditor, BaseComboBox's list and EnvVariableAdder's combo + completer lists — the one atom other atoms may use)
atoms/surfaces/stable_scroll_area.py      StableScrollArea (scroll-bar column always reserved, bar hidden when not needed, so content never shifts)
compositions/draggable_list.py            DraggableList (generic drag-reorder list)
compositions/env_var_row.py               EnvVarRow (Notion-style: hover menu at the row start, name, CopyableLineEdit value, browse)
compositions/row_hover_menu.py            RowHoverMenu (extensible hover gutter: add_widget(), set_revealed(), set_pinned())
compositions/bulk_action_bar.py           BulkActionBar (accent pill "N of M selected | select-all, actions | ×"; add_action(danger=) per bulk operation; select_all_requested / clear_requested)
compositions/copyable_line_edit.py        CopyableLineEdit (copy button appears inside the field on hover)
themed_widget_playground_dialog.py        ThemedWidgetPlaygroundDialog
windows/confirm_dialog.py                 ConfirmDialog (themed rounded question window; ask() -> choice key or None)
windows/whats_new_dialog.py               WhatsNewDialog (release notes per published version; show_for(parent, fetch_releases, current_version, releases_url))
```

Bug fixes made to EXISTING framework files along the way (not new code):
- `ui/widgets/windows/frameless_dialog.py`: `add_separator()` referenced
  `self.content_layout`, which doesn't exist on `FramelessDialog` (only on
  `BaseDialog`) — fixed to route through `self.add_widget()`.
- Combo boxes (`ui/theme/base.qss`): field look with a faint gradient
  (`--combo-top/-bottom`), the arrow set off by a line (`--combo-separator`),
  `actions/chevron_down` arrow via `icon()` for plain QComboBoxes
  (secondary / primary on hover / accent while open), menu-like list rows
  (`::item` rules need a QStyledItemDelegate on the view — BaseComboBox
  sets one). `BaseComboBox` paints its own arrow instead (widgets.qss hides
  the QSS image, keeps its size): it turns up and fades to the accent while
  the list is open, animated; colors = qproperty arrowColor /
  arrowHoverColor / arrowOpenColor. All three Maya Gate combos (year,
  environment, "Maya variable…") are BaseComboBoxes. Never give QComboBox a
  VERTICAL padding: it also pads the popup window, where the native style
  paints a light 2px band above/below the list; height = `min-height`.

Gotcha worth knowing before subclassing `FramelessDialog`/
`FramelessMainWindow` and overriding `_apply_theme()`: any state that
override reads must be set BEFORE calling `super().__init__()`, since the
base class's `__init__()` calls `self._apply_theme()` synchronously at the
end of its own construction — reaching the subclass's override before the
subclass's own `__init__` body finishes.

### What's new (release notes)

Clicking the version in the hub's sidebar opens `WhatsNewDialog`: one block
per PUBLISHED GitHub release, newest first — what changed with each version,
not every commit. The notes are the release's description on GitHub:
- `core/version/release_notes.py` (Qt-free, no I/O): `ReleaseNote`,
  `parse_releases(json)`, `split_sections(body)` — cuts the Markdown at its
  headings, so write a release description as `### New` / `### Improved` /
  `### Fixed` + bullet lists and the dialog shows labelled sections.
- `RemoteVersionChecker.get_releases()` / `VersionManager.get_releases()`
  fetch them (blocking; None on failure). The dialog calls its
  `fetch_releases` on a daemon thread ("Loading…", then the list, or an
  error with Retry). The installed version's pill reads "installed", newer
  ones "new" (`QPushButton#releaseVersion[state]`, widgets.qss — the pill
  opens that release's page); when a newer release exists a banner on top
  says "Version X is available — you have Y" (`QFrame#updateBanner`).
- The dialog lays the notes out itself (`split_blocks()` -> bullet rows /
  paragraphs, `_inline_html()` for **bold**, `code`, links) instead of
  Qt's Markdown lists, whose indent, bullets and code font can't be styled.
  `ReleaseNote.display_title` drops a leading version from the release name
  ("v0.1.0 — Desktop hub" -> "Desktop hub").
- On start, then every 30 minutes, run_hub checks for a newer release on a
  daemon thread (`_watch_for_update`) and, if there is one, calls
  `HubWindow.set_update_available(version)`: an `UpdateButton`
  (atoms/header/ — download arrow dipping into a tray, pop-in + a ring
  pulse every few seconds; qproperty iconColor / ringColor / hoverColor /
  pressedColor) appears in the header left of the theme toggle, and the
  sidebar version turns accent (`QPushButton#hubFooter[notice="true"]`).
  Both open "What's new" (`update_clicked` / `footer_clicked`), whose
  banner offers "Update now" (see "One-click update") — or, where the copy
  can't update itself (a git checkout), "Get it on GitHub" + the reason.
- Releasing: bump `msl/__init__.py:__version_tuple__`, commit, push, then
  publish a GitHub release tagged `v<version>` with the notes. No `gh` CLI
  on this machine — the release is created in the browser.

## Install (the hub is where everything starts)

Setup no longer goes through Maya: `setup_drag_drop_maya.py` and
`tools/maya/installer/` are gone, and nothing is written into Maya's
folders (no userSetup spread over Maya installs) — Maya Gate injects its
userSetup + the msl_tools path at launch. The flow, from a downloaded
release archive or a checkout:

1. `setup_express_launcher.bat` (CRLF, plain ASCII) finds Python 3.10+
   (`py -3`, then `python`; none -> a message with the download link) and
   runs `msl/core/installer/runtime_bootstrap.py --run msl/run_installer.py`.
2. `runtime_bootstrap.py` — STDLIB ONLY and run by path (it runs before
   anything is installed, so it must not import msl_tools or Qt): makes the
   hub's own Python environment, a venv in `%LOCALAPPDATA%\MSL\runtime`
   (`MSL_RUNTIME_DIR` overrides — use it in tests) and `pip install -r
   requirements.txt`. The requirements' hash is kept in a marker file, so a
   second run is instant and a changed requirements.txt reinstalls. Then it
   starts the given script detached with the environment's `pythonw.exe`.
   The runtime is separate from the install folder on purpose: reinstall /
   update replace code, not ~220 MB of PySide6.
3. `msl/run_installer.py` opens `InstallerView`. It's run BY PATH, and
   aliases the package (`sys.modules["msl_tools"]` with `__path__` = the
   root) when the folder isn't named `msl_tools` — GitHub archives unpack as
   `msl_tools-<tag>`.
4. `InstallerView` (tools/desktop/installer/, FramelessDialog): "Install
   to" folder (default `%LOCALAPPDATA%\MSL`), installed-vs-package version,
   "Create a desktop shortcut", Install / Reinstall, Uninstall (danger
   ConfirmDialog: keep settings / remove everything), "Launch MSL Tools".
   Look: two groups ruled off by a divider — what to do (folder, shortcut)
   / what is there (`VersionStatusWidget`: one quiet line, "Installed 0.1.1
   · up to date", the setup's version only when it differs; then the last
   action's outcome, the window's ONE colored line). The progress bar shows
   only while working; Uninstall is a quiet text button
   (`QPushButton#installerUninstall`); the main button reads Install /
   Reinstall / "Install <version>" (another version is installed).
   No logic of its own — `core/installer/hub_installer.py:HubInstaller`
   (Qt-free) works on a CallableWorker thread.

`HubInstaller`: an install is `<install_dir>/msl_tools/{msl/, requirements.txt,
LICENSE, README.md}`; `configs/` and `logs/` next to them are per-user and
never touched by install (uninstall removes them only when asked). It
refuses the folder it is running from. The hub starts as
`<runtime pythonw> -m msl_tools.msl.run_hub` with the install folder as the
working directory (`launch_command()`); the desktop shortcut "MSL Tools"
(`create_shortcut()`, PowerShell + WScript.Shell, values passed as
environment variables, icon `assets/icons/brand/hub.ico`) does exactly that.

## One-click update

"Update now" in What's new replaces the installed code with a published
release and restarts the hub. Two halves, because files can't be swapped
under a running hub:

- `core/installer/hub_updater.py:HubUpdater` (Qt-free, inside the hub):
  `blocked_reason()` (a `.git` folder = a developer's checkout -> no
  self-update; read-only folder), `prepare(tag, version, progress)` —
  downloads `Resources().releaseArchiveUrl` (GitHub's source zip of the
  tag; `MSL_UPDATE_ARCHIVE_URL` overrides the template, e.g. a `file:///`
  URL in tests), checks it (zip CRC, no paths outside the folder, complete
  `msl/`, `__version__` == the release's version) and stages `msl/` + root
  files in `<root>/.update/staged`; raises `UpdateError` with a message for
  the user. `start_apply(version, previous)` starts the helper;
  `take_result()` reads `.update/result.json` once on the next start.
- `core/installer/update_helper.py` — STDLIB ONLY, copied to
  `.update/apply_update.py` and run from there (the NEW version's helper,
  so a release can fix it): waits for the hub's pid, moves the current
  `msl/` + root files to `.update/backup`, the staged ones into place,
  runs `runtime_bootstrap.ensure()` if requirements.txt changed (only when
  running in the msl_tools environment), starts the hub and watches it for
  12 s. Any failure — also the new hub exiting with an error in that time —
  puts the backup back and starts the previous version. `configs/` and
  `logs/` are never touched; `.update/update.log` tells what happened; the
  backup stays until the next update. Uninstall removes `.update/`.
- Freshly unpacked folders are often held by an antivirus scan for a
  moment ("Access is denied" on rename): both halves retry a move for a
  few seconds, then copy instead.
- UI: `WhatsNewDialog(update_handler=, update_blocked_reason=, notice=)`
  stays storage-/network-agnostic — the handler (run_hub: `updater.prepare`)
  runs on a daemon thread, the banner shows progress (`QLabel#updateDetail`,
  BaseProgressBar; GitHub rarely sends a size, so usually indeterminate +
  MB), an error leaves "Try again". On success the dialog closes and
  `show_for()` returns the release; run_hub then calls `start_apply()`,
  closes the window (placement saved) and quits. After the restart
  run_hub shows What's new with a green "Updated to X" banner, or a
  ConfirmDialog saying the previous version was restored ("Show the log").
- A release must contain the updater to be updated FROM: 0.1.0 (installed
  before this existed) has to be reinstalled with the .bat once.
- Going BACK is the same road: every release in What's new that
  `HubUpdater.can_install()` accepts (`MINIMUM_VERSION` = 0.1.1, the first
  with the updater — an older one would leave no way to update again) and
  that isn't the installed one has an "Install this version" button
  (`can_install=` on the dialog; `QPushButton#releaseInstall`). An older
  version is asked first (ConfirmDialog, warning). `prepare()` stages the
  version kept in `.update/backup` straight from there — going back to the
  previous version works offline. After the restart the banner reads
  "Back on version X. Version Y is the newest." + Update now. Settings
  written by a newer version are read by the older one as they are — keep
  config changes backward-tolerant (new keys with defaults, no renames
  without a migration that survives going back).
- Verified in a sandbox with fake release archives (also with the runtime
  environment's Python): update + restart, rollback of a release that
  crashes on start, damaged archive, wrong version, missing release, a
  real GitHub download. Then for real (2026-10-01): the installed copy in
  the user's stable folder updated 0.1.1 -> 0.1.2 from the published
  release with "Update now", then 0.1.2 -> 0.1.3 and back to 0.1.2 with
  "Install this version". The AUTOMATIC rollback (a release that fails to
  start) has only run in the sandbox.

## Verified so far

Everything above was smoke-tested in an offscreen Qt session (no display,
no Maya installed) — imports, construction, and BEHAVIOR (drag-reorder,
value edits, section switching, add/remove, EnvVariableAdder's routing)
all confirmed working against a real `ConfigManager`-backed JsonConfig on
disk. NOT yet tested: against a real Maya installation (actual launch via
`ProcessLauncher.launch_maya`), or in the real GUI (only offscreen).

## Not done yet / open threads

- Setup was verified in a sandbox (own runtime dir, offscreen): the .bat,
  environment creation, install / reinstall / uninstall, shortcut, hub
  start from the installed copy. Not yet run by hand on a clean machine.
- Real icon assets for add/delete/copy/drag (currently Unicode placeholders).
- The `cmds.commandPort`-based Maya connection (future work, unstarted).
