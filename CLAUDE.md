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
    ref/                    the user's local collection of OTHER people's scripts, kept as
                            references to learn from — NOT in git (.gitignore), not part of
                            msl_tools, never installed. Read it for ideas; don't edit or import it.
    msl/
        run_hub.py            standalone entry point for the desktop hub
        run_installer.py      standalone entry point of the setup window (run by path, see "Install")
        assets/               icons/, themes/ — SVG assets, sparse right now
        core/                 Qt-FREE layer: config, fs, logger,
                              environment, theme, version, installer, network,
                              resources.py (core.Resources singleton)
                              (known Qt leftovers: config/ini_config.py uses QSettings,
                              fs/qt_paths.py imports Qt lazily)
        ui/                   Qt-DEPENDENT layer: qt_bindings shim (QtCore/Gui/Widgets/Svg/Network), icon_manager,
                              maya_link/ (MayaLinkServer: the hub's end of the hub <-> Maya link),
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
    `browse`, `folder_add`, `clear`, `arrow_right`, `chevron_down`, `add`, `check`, `select_all`, `more`, `report`, `code`, `restart`, `power`, `play`, `edit`, `scene`, `stop`; add new action icons here),
    `apps/` (third-party application logos: `maya`; later houdini, blender...
    — named after the app, not the tool that uses it, so several tools can
    share one), `tools/` (sidebar icons of our OWN hub tools, one-color like
    action icons: `cube`, `layers` — the stub tools' placeholders), `plugins/`
    (Maya plug-in families on the Boost start tab, our own neutral glyphs —
    NOT the vendors' logos: `plugin` (any), `bifrost`, `arnold`, `xgen`,
    `mash`, `usd`, `bullet`, `redshift`, `flow`, `lookdevx`; the file name is
    the family's name in lower case), `brand/` (our own app icons: `hub` — an "M" monogram, full-color, NOT the
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
  individual tool. The stub tools are listed only in a git checkout (a
  `.git` folder at the root): an installed copy shows real tools only.
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
- Value editor per variable kind (`maya_variables.py`: `VariableSpec` —
  name, kind, description, choices, on_value; `spec_of()`, `kind_of()`).
  page.py turns a spec into the row's `ValueSpec` (`_value_spec_for`);
  EnvVarRow itself knows nothing about Maya and just builds the editor:
  - PATH_LIST (PYTHONPATH, MAYA_MODULE_PATH, ...): text field; browse
    APPENDS the picked folder with os.pathsep, skipping duplicates
    (folder_add icon) — replacing would silently drop the other entries.
  - PATH and unknown/custom variables: text field; browse REPLACES.
  - FILE: text field; browse picks a file (`BrowseMode.FILE`).
  - FLAG (MAYA_DISABLE_CIP/CER/CLIC_IPM): an Off / On SegmentedControl
    with a dimmed note ("= 1" / "not set"). On stores `on_value`, Off
    stores "" — and an EMPTY value of any kind is not passed to Maya
    (`launch_values()` in `_launch`): many Maya flags only check that the
    variable exists, so "=0" would still switch them on. An off flag keeps
    its row. A flag is ADDED switched on (`VariableSpec.default_value`,
    the group's `default_value_for`); any non-empty stored value shows On.
  - CHOICE: a BaseComboBox of `choices` + "not set" (""); a stored value
    outside the choices is kept as an extra entry.
  - VALUE: text field without a browse button (space kept so fields align).
  Values stay plain strings in the config.
  Narrow rows: the value editor is what gives way (the drop-down shrinks
  from 170 to 70px, the switch's note is clipped); RowHoverMenu has a fixed
  width and the group's _ClipBody passes the rows' minimum WIDTH on, so the
  window can't get narrower than its rows need — otherwise a row's layout
  takes the missing pixels from the hover menu and the name, and those rows
  jump out of the column.
- The catalog (`maya_variables.py:GROUPS`): 49 variables in 7 groups
  (Search paths, Folders, Startup & interface, Python & scripts, Viewport,
  Color management, Scenes & rendering), each with a one-line description.
  A CURATED part of Maya's variables, Windows only. Every name was checked
  to exist in the local Maya 2025 install (`grep -rhoaw` over bin/*.dll,
  *.exe, scripts/, Python/.../maya); kinds / allowed values follow
  Autodesk's "Environment variables" help (General, File path, Rendering
  variables). Do both checks before adding one — a wrong kind silently
  writes a wrong value into every launch. `on_value` isn't always "1"
  (MAYA_FORCE_PANEL_FOCUS: "0"). MAYA_SHADER_PATH / MAYA_ICON_PATH from the
  old list weren't found in Maya: out of the dropdown, kept in `_LEGACY` so
  a config that has them keeps the folder-list editor.
  EnvVariableAdder lists the catalog by group — header rows are disabled
  items (`QComboBox QAbstractItemView::item:disabled`, base.qss), each
  variable's description is its tooltip (also on the row's name and in the
  completer); the list opens as wide as the longest name, wider than the
  field.
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
  `from msl_tools...`. The PYTHONPATH inherited from the hub's own process
  is passed on minus IDE helper folders (PyCharm's `helpers/pycharm_*`,
  pydev): a hub run from PyCharm would otherwise hand them to Maya. A
  PYTHONPATH the environment sets itself is passed untouched. A never-saved script reads as
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

- Boost start tab (`boost.py` BoostStore, Qt-free + `boost_tab.py` BoostTab):
  per environment, which of Maya's auto-load plug-ins Maya starts WITHOUT.
  Config: `"boost": {"<env>": {"enabled": bool, "skip": [names]}}` — a SKIP
  list, so a plug-in Maya gains later is loaded by default. A boosted
  launch = `maya.exe -noAutoloadPlugins` (`ProcessLauncher.launch_maya(
  arguments=)`) + a second generated userSetup.py on PYTHONPATH
  (`boost/launch/`, constant content, parameters in MSL_GATE_BOOST_*
  environment variables, Python-2.7-valid) that reads Maya's own list from
  `prefs/pluginPrefs.mel` and loads everything except the skipped ones,
  timing each into `boost/report_<year>.json` (shown per row on the tab).
  THE TRAP, measured with Maya 2025: started with -noAutoloadPlugins, Maya
  REWRITES pluginPrefs.mel on exit from the session's autoload flags —
  44 entries became 1. So the loader first flags every plug-in of the
  original list for autoload BY FILE PATH (`pluginInfo -e -autoload true
  <path>` works unloaded; by name only for loaded ones; a Python `atexit`
  hook never runs, Maya exits hard), and Maya writes the full list back
  (44 -> 44 in 2025, 42 -> 42 in 2020, 45 -> 45 in 2026). A plug-in whose
  file isn't found is loaded anyway rather than dropped. Therefore: never
  pass the flag when the loader can't run — MAYA_SKIP_USERSETUP_PY blocks
  boost (`BoostStore.blocked_reason`, a notice on the tab); every boosted
  launch stores a copy of pluginPrefs.mel (`boost/backup/<year>/`, last 5,
  never replaced by a list that lost entries), and the tab offers Restore /
  "It's fine" when Maya's list has lost plug-ins since. Verified too: a
  scene whose `requires` names a skipped plug-in loads it on open; a
  skipped plug-in can still come up as a dependency (LookdevX -> USD).
  Measured (windowed Maya 2025, incl. an 8 s wait before quitting):
  normal start 45 s, with 34 of 44 plug-ins 30 s. `BoostStore.HEAVY` names
  the costly families (Bifrost, Arnold, XGen, MASH, USD, Bullet, Redshift,
  Flow, LookdevX — the last two from measurements) for "Heavy off".
  Test any change to the loader on a COPY of the preferences first.
  Also not boosted: a Maya with no pluginPrefs.mel yet in the environment's
  preferences folder (a fresh MAYA_APP_DIR) — no list to load from, and
  Maya would save a near-empty one instead of its defaults; its first start
  is a normal one (`_launch` checks `autoload_plugins()`, the tab says so).
  The list and the backups follow the environment's MAYA_APP_DIR.
  The skip list is ONE per environment, shared by every Maya version (the
  tab lists the union of all versions' auto-load lists). The tab's version
  filter ("All versions" / "Maya 2025" ...) is a VIEW: it shows exactly one
  version's list with that version's load times, so one can see what that
  Maya will and won't load; "All on" / "Heavy off" act on the rows shown.
  Per-version skip lists were considered and deliberately not built.
- Startup time is measured, for every launch: `LaunchLog` (boost.py)
  writes `boost/launches/<stamp>_<year>.json` at the click (year,
  environment, boosted), and the boost loader — on PYTHONPATH in EVERY
  launch now (`BoostStore.attach_loader`), boosting only when asked — adds
  `ready_seconds` from a lowest-priority `evalDeferred`: the first idle
  moment after Maya's startup work, plug-ins included. The Boost tab shows
  "Last start of Maya 2025 here: 28.0 s with boost (plug-ins 3.6 s) ·
  52.0 s without boost" (those are real numbers: windowed Maya 2025 on
  this machine, 9 heavy plug-ins skipped); Print Launch Report shows the
  session's own. No userSetup (MAYA_SKIP_USERSETUP_PY) = no measurement.
  Next to that line a `BarStrip` (atoms/charts/) draws the last
  CHART_BARS (24) timed starts of that version in the environment
  (`LaunchLog.measured()`), oldest on the left: accent = with boost, muted
  = without; each bar's tooltip says its time and date. Shown from two
  timed launches on.
- Sessions tab + the hub <-> Maya link (step 1 of the Maya connection):
  the HUB is the server, every Maya a client — the reverse of Maya's
  commandPort. One port, any number of Mayas, both sides can speak over the
  one connection, and a Maya that closes or crashes leaves the list at once.
  - `core/link/protocol.py` (Qt-free, runs in Maya too): a message is a
    JSON object framed as 10 ASCII digits (body size) + UTF-8 body; kinds
    event / request / reply, replies matched to requests by `id`.
    `FrameDecoder.feed()` cuts the stream; a bad header / body raises
    ProtocolError and the connection is dropped.
  - `core/link/session.py`: `MayaSession` (pid, version, environment,
    scene, modified, boosted, busy, connected_at).
  - `ui/maya_link/server.py`: `MayaLinkServer` (QTcpServer, signals only,
    nothing blocks) — `instance()` is the hub's one server, run_hub calls
    `ensure_listening()`. 127.0.0.1 only; port 47611 (next free of 10 if
    taken — a second hub) and a random token, both kept in
    `configs/desktop/maya_link`, so a Maya that outlives a hub restart
    reconnects. A connection becomes a session only after a `hello` with
    the token (5 s to say it); anything else is dropped. Nothing the hub
    RECEIVES is executed.
  - `tools/maya/hub_link.py` (inside Maya): QTcpSocket in Maya's main
    thread, hello on connect, a `scene` event on SceneOpened /
    NewSceneOpened / SceneSaved (sent once per real change), retry every
    5 s while the hub is away. Owned by the QApplication so "Reload Code"
    doesn't kill it. NOT through the Qt shim, and Python-3.9-valid: Maya
    2023 / 2024 ship PySide2 (the shim is PySide6-only), 2023 is 3.9.
    Started by the loader (third job) from `MSL_GATE_LINK_PORT` / `_TOKEN`.
    Maya 2020 (Python 2) doesn't connect.
  - `sessions_tab.py`: every connected Maya (not per environment): dot,
    version, environment, boost, scene, time connected; the tab's title
    carries the count ("Sessions · 2"). Read-only so far.
  - Requests hub -> Maya (step 2): `MayaLinkServer.request(session_id,
    name, on_reply, timeout_ms, **data)` — `on_reply(reply)` runs exactly
    once: Maya's answer, or a failure if it left or didn't answer in time;
    only the Maya that was asked may answer (matched by id AND connection).
    Maya's side (`HubLink._HANDLERS`) is a FIXED list, each handler runs in
    Maya's main thread, an exception becomes a failure reply:
    `launch_report` (-> text; launch_report.py is Python-3.9-safe and
    imports no other msl module for that reason), `reload_code` (drops
    msl_tools from sys.modules, rebuilds the MSL menu only if that Maya has
    one, then restarts its own link on the fresh code — the session leaves
    and comes back with a new id), `plugin_state` / `load_plugins` (names
    -> loaded / failed). The hello carries `skipped` (what boost left out).
    Session rows have quiet link buttons — Report (shown in `TextDialog`,
    ui/widgets/windows/text_dialog.py: fixed-width text + "Copy all"),
    Reload code, Plug-ins (boosted sessions: a menu of the skipped plug-ins,
    "Load all N" or one; already loaded ones are greyed) — and the outcome
    of the last request is the line under the list. A row is busy (buttons
    off) while its Maya works.
  - The log stream Maya -> hub (step 3): `HubLink._watch_output()` has
    Maya call `_on_output` for everything the Script Editor prints
    (`maya.api.OpenMaya.MCommandMessage.addCommandOutputCallback`). The
    callback only FILTERS and COLLECTS (it runs for every output line and
    must never print or raise — that would come straight back to it);
    `_flush_log` sends the batch every 250 ms as a `log` event
    `{"entries": [[level, text], ...], "dropped": n}`. Levels: error,
    warning, trace, info; command echo (kHistory) is never sent, info
    (print, displayInfo, results) only after the hub's `set_log_level
    {"all": true}` — and every new connection starts on problems only (the
    hub re-asks sessions that join while its switch is on "All"). Caps:
    400 lines per flush in Maya, 500 entries / 8000 chars per entry
    accepted by the hub. What arrives from a windowed Maya (measured, 2023
    + 2025): cmds.warning, MEL warnings and errors, Python `logging`
    warnings / errors, MGlobal.displayError, uncaught Python exceptions;
    with "All" also Python print, MEL print, displayInfo. A `cmds.error`
    caught by a try does not.
    `MayaLinkServer.log_received(session_id, entries)` -> the Sessions tab:
    the list (as tall as its rows, 4 at most) + a log panel under it for
    the SELECTED Maya (click a row): `LogView` (atoms/editors/log_view.py:
    fixed-width, time-stamped, colored by level from QSS, follows the tail
    while scrolled to the bottom), a Problems / All switch, Copy, Clear;
    each row counts its errors / warnings. Logs and selection are keyed by
    Maya's PID, not the session id ("Reload code" changes the id), and a
    Maya that left keeps its log on screen for GONE_GRACE_S (60 s) — a
    crashed Maya is the one whose log is wanted.
  - The console (step 4): the ONE request that carries code,
    `run_python` {"code"} -> {"output", "result", "traceback"} (not
    "error": a reply's own `error` field means the request failed — the
    name clash once swallowed every traceback). Maya's handler runs the
    code like the Script Editor would: in `__main__` (names persist and are
    the Script Editor's own), the value of a final expression is the
    result, stdout / stderr are captured into the reply AND passed on to
    Maya's own (`_Tee`), so the Script Editor shows the code, its output,
    "# Result: ..." or the traceback — whoever sits at Maya sees what was
    run. While it runs the log stream is paused (`_console_running`), or
    the hub would get that output twice (checked with the switch on "All").
    The traceback starts at the user's code, the whole run is one undo
    step, and BaseException is caught (`sys.exit()` must not take Maya
    down).
    WHO MAY: only a Maya launched with `MSL_GATE_CONSOLE=1`, which Maya
    Gate sets for `MayaGatePage.CONSOLE_ENVIRONMENTS` = ("Dev",). The
    decision is made in Maya (`hub_link.console_allowed()`, checked on
    every call) — the hub merely hides the console for sessions whose
    hello says `console: false`. On the tab: `_ConsoleInput` (a small
    CodeEditor; Ctrl+Enter runs, Ctrl+Up / Down walk the history) + Run,
    under the log, shown only for a selected Maya that allows it; the
    code (level "input", ">>>" in the accent), its output, result and
    traceback go into that Maya's log and don't count as its problems.
    Verified with real Maya 2023 + 2025.
  - Around the sessions (seen without opening the tab):
    - Header indicator: `LinkStatusButton` (atoms/header/) left of the
      theme toggle, put there by run_hub (`_add_link_indicator`,
      `HubWindow.add_header_widget()`): hollow ring = not listening, green
      dot + the number of connected Mayas = listening, red pulsing dot =
      unread errors. A click = `HubWindow.open_tool("maya_gate")` +
      `MayaGatePage.show_sessions()`. The atom knows nothing about Maya.
    - Unread errors: `MayaLinkServer.unread_errors()` /
      `set_unread_errors()` + `attention_changed`. The Sessions tab counts
      errors (and Mayas that ended unexpectedly) that arrive while it is
      NOT on screen and clears the number in showEvent; the tab's title
      gets " · !" and the indicator turns to attention. Warnings don't count.
    - Version tiles: `ApplicationButton.set_badge("2")` — a green pill on
      the icon's corner = how many of that Maya are connected
      (`MayaVersionRow.set_running({year: n})`, fed by the page).
    - Busy: the server pings every Maya each PING_INTERVAL_MS (4 s); no
      answer within PING_TIMEOUT_MS (3 s) sets `MayaSession.busy` (Maya's
      main thread is working) until a ping is answered — the row shows a
      "busy" pill and a warning-tone dot. Measured with real Maya: a 9 s
      `time.sleep` in the main thread = busy for that time, then free.
    - Goodbye: Maya sends a `bye` event when it quits (scriptJob
      `quitApplication`) and when its link restarts ("Reload code");
      `MayaLinkServer.session_ended(session, clean, reason)` is clean=True
      then, and when the hub itself closes; `reason` = protocol.BYE_QUIT /
      BYE_RESTART / `ENDED_BY_HUB` / "" (broke). A connection that just breaks is
      clean=False — Maya crashed or was killed: the tab keeps an "ended
      unexpectedly at HH:MM" line (`_EndedRow`; Log file / Dismiss; a click
      shows its log, kept until dismissed) and writes that Maya's log to
      `logs/desktop/maya_gate/sessions/maya<year>_<stamp>_pid<pid>.log`.
      A Maya whose code predates `bye` (started before this was built)
      reads as ended unexpectedly on a normal quit.
    - Unsaved changes: Maya has no event for "the scene was modified", so
      HubLink polls `cmds.file(q=True, modified=True)` every SCENE_POLL_MS
      (2 s) and sends a `scene` event {"scene", "modified"} only on a change
      (the hello carries both). A row's scene name gets a "*" (as in Maya's
      title bar); an "ended unexpectedly" line says "· unsaved changes".
      Measured with real Maya 2025: new cube -> modified within 2 s, save ->
      clean + the new name, the next edit -> modified again.
      `_on_quit` reports the scene once more before the goodbye: a save
      right before quitting (Maya's "Save changes?" on exit) reaches neither
      the scene events nor the poll — Maya is gone before its next idle
      moment, and the history would keep a wrong "*" (it did, Maya 2024).
    - The scene's name is a link (`_SceneLabel`, sessions_tab.py): only the
      NAME, not the empty space after it (the label stretches over the
      row) — a click shows the file in the file manager (its folder if the
      file is gone), a right click offers that and "Copy path"; the click
      doesn't select the row. An untitled scene is no link.
    - History: `session_history.py` (`SessionHistory` / `SessionRecord`,
      Qt-free) keeps the last 30 finished sessions in
      `configs/desktop/maya_gate/sessions/history.json` — version,
      environment, scene, unsaved flag, start / end, clean or not, the saved
      log's path. Recorded on session_ended for reasons quit and "" only: a
      link restart and the hub's own shutdown are NOT ends. What a session
      reported is saved with it (any end with entries, every unclean end):
      `write_log()` / `read_log()` in the same module are the two ends of
      that text format (`logs/desktop/maya_gate/sessions/`); a log leaves
      with its record (history overflow, "Clear").
      On the tab "Recent sessions" sits under the live rows: open while
      nothing runs, folded while a Maya does — a click on the caption
      (`QPushButton#sessionsHistoryToggle`) flips it until that situation
      changes. `_HistoryRow`: hollow dot = closed, red = ended unexpectedly;
      a click shows its saved log in the log panel (`_history_selected`;
      Clear is off there), "Log file" shows the file, "Reopen" starts that
      Maya again with the scene. A session still waiting as an "ended
      unexpectedly" line isn't listed twice. The history file is first read
      when the tab is shown.
    - A live row has ONE "more" button (GlyphButton, `actions/more`; a
      right click on the row opens the same menu — `_on_row_menu`): Launch
      report, Reload code, Load plug-ins… (boosted sessions), Close Maya…,
      Restart Maya…. Separate link buttons made a full row need ~776 px.
      The items carry icons (`actions/report`, `code`, `restart`, `power`,
      `plugins/plugin`). A menu's icons are QIcons, which QSS can't tint:
      the tab takes the colors as properties (qproperty menuIconColor /
      menuDangerColor - "Close Maya" is in the danger tone) and tints them
      with `tint_icon()` when the menu opens (`_menu_icon`), so they follow
      the theme. `QMenu::icon` (base.qss) sets every menu's icons in from
      the item's edge.
    - Close / Restart (the row's menu): the request `quit_maya`
      {"save", "discard"}. The hub asks first (ConfirmDialog: with unsaved
      changes "Save and close" / "Close without saving" / Cancel — no save
      offered for an untitled scene, and that dialog is "danger"); MAYA
      checks again — without save / discard a modified scene refuses
      (`protocol.QUIT_UNSAVED`), so a change made after the question can't
      be lost. Maya replies, then quits 300 ms later (`cmds.quit(force=True)`).
      Restart: once the session ended cleanly, `_start_when_gone` waits
      until the PROCESS is gone (`core/environment/processes.py:
      is_process_running` — never `os.kill(pid, 0)` on Windows, it
      terminates; Maya still writes its preferences for ~0.3 s after its
      goodbye), then starts the same version + environment + scene.
    - Force close: a Maya that doesn't answer (`session.busy`, with
      `busy_since`) gets "Force close…" in its menu — asks (danger; the
      default is "Wait"), then `terminate_process(pid)`
      (core/environment/processes.py). The end that follows is marked
      `forced` (ended row "force closed at …", `SessionRecord.forced`), and
      doesn't count as an unread error. A row never disables its menu
      button: while a request is out (`row.pending`) or Maya is busy, the
      menu's requests are greyed instead — otherwise a hung Maya's menu
      couldn't be opened at all.
    - Autosave after an unclean end: Maya reports its autosave state in the
      hello and the `scene` event (`autosave`, `autosave_folder` =
      `cmds.autoSave(q=True, destinationFolder=True)`, the folder in
      effect). `find_autosave(folder, scene, since)` (session_history.py)
      picks the newest `<scene name>.<number>.ma|mb` (`__AUTO-SAVE__
      untitled.…` for a scene with no file — names measured with Maya 2025)
      written since the session connected AND newer than the scene file.
      Found: "Open autosave" on the ended row / "Autosave" on the history
      row (`SessionRecord.autosave`) starts that Maya with the autosave as
      its scene. Verified with real Maya 2025: killed 2 s after an autosave,
      the hub found that file. Probing autosave needs a TEMP PROJECT
      (`cmds.workspace(dir, newWorkspace=True)` + openWorkspace): with a
      copied MAYA_APP_DIR the project is still the user's real one, and the
      autosaves land in their Documents (it happened; cleaned up).
    - A live row's tooltip: process memory (`process_memory(pid)`, read at
      each refresh), how long the start took (`startup_seconds` — hub_link
      measures it once at its first start from MSL_GATE_LAUNCH_TIME and
      keeps it in MSL_GATE_STARTUP_SECONDS, so "Reload code" doesn't
      re-measure), boost + plug-ins not loaded, "Not answering for …",
      autosave on / off.
    - The tab launches nothing itself: the page hands it
      `launch(year, environment, scene) -> "" | error`
      (`MayaGatePage._launch_scene`: version still installed, scene still
      there) and `settings` (the `_ui` node: "log_wrap").
      `MayaGatePage._launch(year, environment=None, scene="")` takes the
      named environment's variables, userSetup and boost settings — not
      the toolbar's — and passes the scene as `-file <path>`.
    - Launch preview: a tile's menu -> "What Maya will get…" ->
      `MayaGatePage.launch_preview(year)` in a TextDialog: executable,
      arguments, boost (or why it isn't applied), userSetup, then every
      variable — the environment's own first, what MSL Tools adds or
      extends second (folder lists one entry per line; the link token is
      "(hidden)"). `_prepare_launch(..., preview=True)` is the launch
      itself minus its traces: no pluginPrefs backup
      (`BoostStore.prepare_launch(backup=False)`), no launch record, the
      userSetup editor isn't saved. `_launch` = `_prepare_launch` + the
      launch record + the process.
    - Menu icons: `ui/icon_manager.py:tinted_menu_icon(icon, color, ratio)`
      — the version tile's menu (MayaGatePage qproperty menuIconColor) and
      the snippet chip's menu use it like the row menu does (`actions/play`,
      `browse`, `report`, `scene`, `edit`, `delete`, `stop`).
    - Launch with a scene: drop a .ma / .mb on a version tile
      (`ApplicationButton.set_drop_suffixes()` -> `file_dropped`), or right
      click it (`menu_requested` -> the page's menu: Launch, "Open a
      scene…", the scenes of running + recent sessions) — in the CURRENT
      environment. Measured with real Maya 2025, boost on: the scene opens,
      unmodified. (A hand-written minimal .ma shows as modified right after
      opening — that is Maya filling in what the file lacks, not the launch.)
      A scene's name in ANY session row (live, ended, history) can also be
      dragged onto a tile: `_SceneLabel` starts a QDrag carrying the file
      as a URL (`drag_data()`), so the tile's file drop takes it like one
      from the file manager — and so does anything else that takes files.
      A drop goes through `_open_scene` (a scene that is gone = a message).
    - Log lines wrap by default ("Wrap" switch, `LogView.set_wrap()`,
      remembered in `_ui.log_wrap`).
    - Console snippets: `snippets.py` (`SnippetStore`, Qt-free;
      `configs/desktop/maya_gate/console/snippets.json`, in the order
      added). Chips (`QPushButton#snippetChip`, in a `FlowLayout` that
      wraps) above the console's input: a click runs the snippet in the
      selected Maya (`_run_code`, the same road as Run — the input isn't
      touched), a right click offers Run / Edit (the code goes into the
      input; saving under the same name replaces it in place) / Delete
      (asks). "+ Save as snippet" asks for the name in place (`_NameField`:
      Enter takes it, Esc / a click elsewhere gives up) — no dialog. The
      file is first read when the console first shows.
    - Selection: a Maya that left with an EMPTY log holds the selection only
      RELOAD_GRACE_S (5 s — a "Reload code" comes back sooner) and the log
      title stays blank; one with a log keeps it GONE_GRACE_S, titled
      "· Maya 2025 · Dev · closed".
    Verified with real Maya 2023 + 2025 too: `quit_maya` refused on an
    unsaved scene, then save + quit (the file grew, the session ended
    clean and unmodified); 2025 also with discard.
    Verified with real Maya 2023 + 2025: quit -> clean, killed process ->
    not clean, busy on and off. Tests that read raw requests from a fake
    Maya stop the ping timer first (`server._ping_timer.stop()`).
  - Offscreen tests of the link must `listen()` on a private port / token,
    never `ensure_listening()`: with the real ones, a real Maya running on
    the machine joins the test hub (it happened).
  Verified with real windowed Maya 2023, 2024, 2025 (copies of the
  preferences): connect, scene change, hub away and back (rejoined in
  ~2 s), exit; and in 2023 + 2025 every request above — report ~1 s,
  loading MASH into a boosted Maya 0.15 s, reload + rejoin 0.3 s, an unknown
  request refused, Maya's own auto-load list intact after loading a plug-in
  this way. All four planned steps of the link are built.
  Long work in Maya must answer later by `id`, never block the socket.
- Every launch tells Maya what it is: `MSL_GATE_ENVIRONMENT` (the
  environment) and `MSL_GATE_VARIABLES` (names of the variables this launch
  set). The MSL menu's Dev > "Print Launch Report"
  (`tools/maya/launch_report.py`, runs inside Maya, read-only) prints them
  with the preferences folders, the variables Maya Gate set (folder lists
  entry by entry with ok / MISSING), the other MAYA_* ones (lists summed
  up — Maya extends them with dozens of module folders), the userSetup
  files on sys.path, the boost report (loaded / skipped / failed, slowest,
  notes) and the loaded plug-ins and modules.
- `_migrate_legacy_config()` treats only ENVIRONMENT-named top-level keys
  as legacy Maya variables. It used to take any unknown dict — and swept
  the new "boost" branch into "maya" on every start, resetting it. A new
  top-level config branch must never look like legacy data to it.
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
    boost.py               BoostStore (Maya's auto-load list, the boosted launch + its loader, reports, backups, Qt-free)
    boost_tab.py           BoostTab (per-environment plug-in list: checked = loaded at startup)
    sessions_tab.py        SessionsTab (the Mayas connected to the hub right now; the finished ones while none is)
    snippets.py            SnippetStore (named pieces of code for the console, Qt-free)
    session_history.py     SessionHistory / SessionRecord (the sessions that are over, kept across hub restarts, Qt-free)
    version_row.py         MayaVersionRow (animated row of installed versions)
    variable_group.py      CollapsibleVariableGroup (config-aware, owns persistence)
    variable_adder.py      EnvVariableAdder (known/custom variable input row)
    maya_variables.py      what each known Maya variable holds (PATH_LIST / PATH / VALUE) + the known list, Qt-free
```

New generic pieces added to `ui/widgets/` along the way:
```
atoms/buttons/application_button.py          ApplicationButton (was ApplicationButtonWdg; set_badge(text): a small pill on the icon's corner; set_drop_suffixes() -> file_dropped; right click -> menu_requested)
atoms/header/link_status_button.py        LinkStatusButton (header status dot + count: off / on / attention with a pulse; shows what it is told — set_state())
atoms/buttons/icon_push_button.py         IconPushButton (framed button with a QSS-tinted one-color icon)
atoms/buttons/icon_tile_button.py         IconTileButton (QToolButton tile: QSS-tinted icon over a short label; icon-less tiles keep the icon row empty so a column stays aligned)
atoms/icons/tinted_icon.py                TintedIcon (passive one-color icon tinted from QSS: qproperty-iconColor; dimmed when disabled)
atoms/buttons/glyph_button.py             GlyphButton (custom-painted small icon button; QPushButton's QSS padding leaves no room for a glyph at ~20px)
atoms/comboboxes/base_combo_box.py        BaseComboBox (was QCustomComboBox)
atoms/charts/bar_strip.py                 BarStrip (a handful of measurements as thin bars in two tones, each with a tooltip; scaled from zero; qproperty accentColor / mutedColor)
atoms/layouts/flow_layout.py              FlowLayout (items left to right, wrapping like words; height-for-width; hidden widgets take no room)
atoms/editors/log_view.py                 LogView (read-only log: time-stamped entries colored by level — error / warning / info / trace — from qproperty colors; follows the tail; its QSS `color` exists only to color the placeholder — a QPlainTextEdit without one draws it near-black)
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
windows/text_dialog.py                    TextDialog (a block of fixed-width text to read and copy: reports, logs; show_for(parent, title, text))
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

Gotcha: never call `setVisible(True)` / `show()` on a widget that has no
parent yet (typically in a `_build_widgets()` before the layout adopts it):
Qt shows it as a tiny top-level window of its own for a moment. Write
`if not wanted: widget.hide()` instead of `widget.setVisible(wanted)` there.
(This flashed a window on every environment switch with the Boost tab open.)

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
- The Maya connection (sessions, requests, log stream, console) is built
  on our own link, not `cmds.commandPort`. Not built: "open a scene" from
  the hub INTO A RUNNING Maya (it can discard unsaved work — needs a
  confirmation; starting a new Maya with a scene is built), Mayas not
  started from the hub joining it, Maya 2020 (Python 2).
- Boost start: built and verified against real Maya 2020 / 2025 / 2026 on
  COPIES of the preferences (MAYA_APP_DIR in %TEMP%); not yet used on the
  user's real preferences, nor released.
