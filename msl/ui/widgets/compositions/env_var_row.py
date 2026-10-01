# ui/widgets/compositions/env_var_row.py
import os
import threading
from enum import Enum, auto

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons import GlyphButton, IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.compositions.copyable_line_edit import CopyableLineEdit
from msl_tools.msl.ui.widgets.compositions.row_hover_menu import RowHoverMenu


class BrowseMode(Enum):
    """What the row's browse button does with the picked folder."""
    REPLACE = auto()  # the value is one folder: the pick replaces it
    APPEND = auto()   # the value is a folder LIST: the pick is added (if new)
    NONE = auto()     # the value isn't a path: no browse button


def _looks_like_path(text: str) -> bool:
    """True for values worth checking on disk: anything with a path
    separator ("C:/x", "\\\\server\\share", "./rel") — not plain values like "1"."""
    return "/" in text or "\\" in text


class _RowCheckbox(BaseCheckbox):
    """Private: BaseCheckbox sized for a dense 25px row."""

    BOX_SIZE = 14
    CORNER_RADIUS = 4


class EnvVarRow(qt.QtWidgets.QWidget):
    """One row in a reorderable key/value list, laid out Notion-style:

        ⋮⋮ │ ☐ NAME [⧉]  [ value ...............⧉ ] [...]
           └ selection_gutter: where the owner draws its frame line

    - Hover menu (RowHoverMenu, start of the row): the drag handle for
      DraggableList, then a selection checkbox for bulk actions. Shown
      while the row is hovered; the checkbox stays visible while checked.
      `hover_menu` is public so owners can append more controls later.
    - selection_gutter: width of the drag handle's own column at the very
      left. An owner that draws a frame (see CollapsibleVariableGroup)
      starts it at this x, so the handle reads as sitting OUTSIDE the
      frame, like Notion's page-margin handle, while the checkbox sits
      just inside it. 0 = no separate column.
    - Name + copy-name button (shown on hover).
    - Value: CopyableLineEdit — its own copy button appears on hover.
    - Browse is a regular bordered button — it's a primary action, so it
      shouldn't look like a hover-only control. `browse_mode` decides what
      it does (the owner knows which variables are what; this row doesn't):
      REPLACE (folder icon) sets the value to the picked folder; APPEND
      (folder-add icon) adds it to a `list_separator`-joined folder list,
      skipping one that's already there; NONE hides the button but keeps
      its space, so value fields stay aligned across rows.

    There is no per-row delete or move button: removal is a bulk action on
    the selection (see BulkActionBar), reordering is drag-and-drop.

    Storage-agnostic — never touches config; the owner reacts to signals.

    The selected-row highlight is the `selectedColor` property, set by the
    window stylesheet (ui/theme/widgets.qss).

    Missing folders: a value (or, in APPEND mode, each entry of the list)
    that LOOKS like a path but doesn't exist on disk marks the field
    pathState="missing" (a warning border, widgets.qss) and names the
    missing folder(s) in the field's tooltip — a mistyped path otherwise
    fails silently in the launched application. Values that aren't paths
    ("1") and NONE-mode rows aren't checked. The check runs on a background
    thread (an unreachable network drive can block for seconds), first when
    the row is shown, then PATH_CHECK_DELAY_MS after each edit. For path
    lists the tooltip also lays the entries out one per line.

    Signals:
        value_changed(str, str) — (item_id, new_value)
        selection_changed(str, bool) — (item_id, selected)
    """

    HEIGHT = 25
    LABEL_MIN_WIDTH = 150
    BUTTON_SIZE = qt.QtCore.QSize(20, 20)
    ICON_SUB_FOLDER = "actions"     # assets/icons/actions/
    DRAG_ICON = "drag_handle"
    COPY_ICON = "copy"
    BROWSE_ICON = "browse"
    BROWSE_APPEND_ICON = "folder_add"
    BROWSE_BUTTON_SIZE = qt.QtCore.QSize(26, 22)  # value field height
    FRAME_INSET = 3            # gap between the frame line and the drag handle
    SELECTED_ALPHA = 38
    CORNER_RADIUS = 4
    PATH_CHECK_DELAY_MS = 400
    EMPTY_PLACEHOLDER = "empty"
    COPIED_ICON = "check"

    selectedColor = color_property("_selected_color")
    hoverColor = color_property("_hover_color")

    value_changed = qt.QtCore.Signal(str, str)
    selection_changed = qt.QtCore.Signal(str, bool)
    _paths_checked = qt.QtCore.Signal(int, list)  # (check id, missing entries), from the check thread

    def __init__(self, item_id: str, value: str, draggable: bool = False,
                 selection_gutter: int = 0, browse_mode: BrowseMode = BrowseMode.REPLACE,
                 list_separator: str = os.pathsep, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.value = value
        self.browse_mode = browse_mode
        self._list_separator = list_separator
        self._selected_color = qt.QtGui.QColor(ThemeRegistry.fallback().accent)  # until QSS applies
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)  # until QSS applies
        self._hovered = False
        self._selected_color.setAlpha(self.SELECTED_ALPHA)
        self._gutter = selection_gutter
        self.drag_handle: GlyphButton | None = None
        self._missing_paths: list[str] = []
        self._path_check_id = 0                           # newest check; older results are dropped
        self._path_checked_once = False
        self._path_check_timer = qt.QtCore.QTimer(self)
        self._path_check_timer.setSingleShot(True)
        self._path_check_timer.setInterval(self.PATH_CHECK_DELAY_MS)
        self._path_check_timer.timeout.connect(self._check_paths)
        self._paths_checked.connect(self._on_paths_checked)

        self.setFixedHeight(self.HEIGHT)
        self._build_widgets(draggable)
        self._build_layout()
        self._build_connections()
        self._set_hovered(False)

    def _build_widgets(self, draggable: bool) -> None:
        self.select_checkbox = _RowCheckbox()
        self.select_checkbox.setToolTip("Select for bulk actions")

        # Drag handle centered in the gutter column (outside the owner's frame),
        # then step over the frame line, then the checkbox just inside it.
        self.hover_menu = RowHoverMenu()
        handle_width = self.BUTTON_SIZE.width() if draggable else 0
        lead = max((self._gutter - handle_width) // 2, 0)
        self.hover_menu.add_spacing(lead)
        if draggable:
            self.drag_handle = self.hover_menu.add_widget(
                GlyphButton("\u22ee\u22ee", "Drag to reorder", self.BUTTON_SIZE))
            # Icon over the glyph fallback; tinted with the QSS glyph colors like any glyph.
            self.drag_handle.set_icon(UiResources().iconManager.get_icon(
                self.DRAG_ICON, sub_folder=self.ICON_SUB_FOLDER))
        self.hover_menu.add_spacing(max(self._gutter - lead - handle_width, 0) + self.FRAME_INSET)
        self.hover_menu.add_widget(self.select_checkbox)

        self.name_label = qt.QtWidgets.QLabel(self.item_id)
        self.name_label.setToolTip(self.item_id)  # full name even when the column clips it
        self.name_label.setMinimumWidth(self.LABEL_MIN_WIDTH)
        self.name_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        self.copy_name_button = GlyphButton("\u29c9", "Copy variable name", self.BUTTON_SIZE)
        self.copy_name_button.set_icon(UiResources().iconManager.get_icon(
            self.COPY_ICON, sub_folder=self.ICON_SUB_FOLDER))
        policy = self.copy_name_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.copy_name_button.setSizePolicy(policy)

        self.value_field = CopyableLineEdit(self.value)
        self.value_field.setPlaceholderText(self.EMPTY_PLACEHOLDER)

        # Framed button (base.qss), icon tinted by QSS iconColor; "..." if the asset is missing.
        # Its padding is zeroed in widgets.qss — the base 4px 10px leaves no room at this size.
        appending = self.browse_mode is BrowseMode.APPEND
        self.browse_button = IconPushButton(
            UiResources().iconManager.get_icon(self.BROWSE_APPEND_ICON if appending else self.BROWSE_ICON,
                                               sub_folder=self.ICON_SUB_FOLDER),
            "Add a folder to the list" if appending else "Browse for a folder", fallback_text="...")
        self.browse_button.setFixedSize(self.BROWSE_BUTTON_SIZE)
        self.browse_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.browse_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        if self.browse_mode is BrowseMode.NONE:
            policy = self.browse_button.sizePolicy()
            policy.setRetainSizeWhenHidden(True)  # keep the column so value fields stay aligned
            self.browse_button.setSizePolicy(policy)
            self.browse_button.hide()

    def _build_layout(self) -> None:
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(2)
        layout.addWidget(self.hover_menu)
        layout.addSpacing(2)
        layout.addWidget(self.name_label)
        layout.addWidget(self.copy_name_button)
        layout.addWidget(self.value_field, 1)
        layout.addWidget(self.browse_button)

    def _build_connections(self) -> None:
        self.value_field.textChanged.connect(self._on_value_changed)
        self.browse_button.clicked.connect(self._on_browse)
        self.copy_name_button.clicked.connect(self._on_copy_name)
        self.select_checkbox.toggled.connect(self._on_selection_toggled)

    # --- name column ---------------------------------------------------------

    def name_width_hint(self) -> int:
        """Width the name label needs to show its whole text."""
        return self.name_label.sizeHint().width()

    def set_name_width(self, width: int) -> None:
        """Pins the name column width — owners pass the same value to every
        row so the value fields line up in one column."""
        self.name_label.setFixedWidth(max(width, self.LABEL_MIN_WIDTH))

    # --- selection ---------------------------------------------------------

    def is_selected(self) -> bool:
        return self.select_checkbox.isChecked()

    def set_selected(self, selected: bool) -> None:
        """Programmatic (de)select; emits selection_changed only on change."""
        if selected != self.is_selected():
            self.select_checkbox.setChecked(selected)

    def _on_selection_toggled(self, selected: bool) -> None:
        self.hover_menu.set_pinned(self.select_checkbox, selected)
        self.update()  # selected-row highlight
        self.selection_changed.emit(self.item_id, selected)

    # --- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        # Selected rows take the accent tint; a hovered row a faint neutral one.
        fill = self._selected_color if self.is_selected() else (self._hover_color if self._hovered else None)
        if fill is not None:
            painter = qt.QtGui.QPainter(self)
            painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            # Highlight only the part inside the owner's frame, not the gutter.
            rect = qt.QtCore.QRectF(self.rect()).adjusted(self._gutter + 1, 0, 0, 0)
            painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
            painter.end()
        super().paintEvent(event)

    # --- actions -----------------------------------------------------------

    def _on_value_changed(self, text: str) -> None:
        self.value = text
        self.value_changed.emit(self.item_id, text)
        self._path_check_timer.start()  # re-check once the typing pauses

    def _on_browse(self) -> None:
        entries = self._list_entries()
        start = entries[-1] if entries else ""
        directory = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Select a Folder", start)
        if directory:
            self.value_field.setText(self.value_with_folder(directory))

    def value_with_folder(self, folder: str) -> str:
        """The value after picking `folder`: the folder itself (REPLACE), or
        the list with `folder` appended unless it's already in it (APPEND;
        compared case/slash-insensitively, like Windows paths)."""
        if self.browse_mode is not BrowseMode.APPEND:
            return folder
        entries = self._list_entries()
        normalized = {os.path.normcase(os.path.normpath(entry)) for entry in entries}
        if os.path.normcase(os.path.normpath(folder)) not in normalized:
            entries.append(folder)
        return self._list_separator.join(entries)

    def _list_entries(self) -> list[str]:
        """Non-empty entries of the current value (one entry unless APPEND)."""
        text = self.value_field.text().strip()
        if self.browse_mode is not BrowseMode.APPEND:
            return [text] if text else []
        return [entry.strip() for entry in text.split(self._list_separator) if entry.strip()]

    def _on_copy_name(self) -> None:
        qt.QtGui.QGuiApplication.clipboard().setText(self.item_id)
        self.copy_name_button.flash_icon(UiResources().iconManager.get_icon(
            self.COPIED_ICON, sub_folder=self.ICON_SUB_FOLDER))

    # --- missing folders -----------------------------------------------------

    def missing_paths(self) -> list[str]:
        """Path entries of the value that don't exist (as of the last check)."""
        return list(self._missing_paths)

    def _path_entries(self) -> list[str]:
        """The value's entries worth checking: the path-looking ones."""
        if self.browse_mode is BrowseMode.NONE:
            return []
        if self.browse_mode is BrowseMode.APPEND:
            entries = [entry.strip() for entry in self.value.split(self._list_separator)]
        else:
            entries = [self.value.strip()]
        return [entry for entry in entries if entry and _looks_like_path(entry)]

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._path_checked_once:  # lazily: no disk access at construction
            self._path_checked_once = True
            self._check_paths()

    def _check_paths(self) -> None:
        """Starts a background existence check of the current entries."""
        entries = self._path_entries()
        self._path_check_id += 1
        check_id = self._path_check_id
        if not entries:
            self._apply_path_state([])
            return

        def check() -> None:
            missing = [entry for entry in entries if not os.path.exists(entry)]
            try:
                self._paths_checked.emit(check_id, missing)  # queued to the GUI thread
            except RuntimeError:
                pass  # the row was deleted while the check ran

        # A plain daemon thread, not a QThread: the row may be deleted mid-check,
        # and a QThread destroyed while running crashes Qt.
        threading.Thread(target=check, daemon=True).start()

    def _on_paths_checked(self, check_id: int, missing: list) -> None:
        if check_id == self._path_check_id:  # else the value changed since: a newer check is coming
            self._apply_path_state(missing)

    def _apply_path_state(self, missing: list[str]) -> None:
        self._missing_paths = list(missing)
        state = "missing" if missing else ""
        if self.value_field.property("pathState") != state:
            self.value_field.setProperty("pathState", state)
            repolish(self.value_field)

        entries = self._path_entries()
        if len(entries) > 1:   # a path list: one entry per line, marked
            lines = [("\u2717  " if entry in missing else "\u2713  ") + entry for entry in entries]
            if missing:
                lines.append("")
                lines.append(f"{len(missing)} folder(s) not found")
            self.value_field.setToolTip("\n".join(lines))
        elif missing:
            self.value_field.setToolTip(f"Folder not found:\n{missing[0]}")
        else:
            self.value_field.setToolTip("")

    # --- hover -------------------------------------------------------------
    # Enter/Leave on the row itself cover all of its children: Qt does not send
    # the row a Leave when the cursor moves onto its own line edit or buttons.

    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)

    def _set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        self.hover_menu.set_revealed(hovered)
        self.copy_name_button.setVisible(hovered)
        self.update()  # hover tint


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog
    from msl_tools.msl.ui.widgets.compositions.draggable_list import DraggableList

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()

        drag_list = DraggableList(draggable=True)
        for name, value in [("MAYA_APP_DIR", "H:/ProjectsDev/Maya/MSL_Prefs"),
                             ("PYTHONPATH", "H:/ProjectsDev/Maya/MSL_Scripts"),
                             ("TEMP", "H:/ProjectsDev/Temp")]:
            row = EnvVarRow(name, value, draggable=True, selection_gutter=22)
            row.value_changed.connect(lambda i, v: print("changed:", i, "=", v))
            row.selection_changed.connect(lambda i, s: print("selected:", i, s))
            drag_list.append_widget(name, row)

        drag_list.order_changed.connect(lambda order: print("order:", order))

        dialog.add_case("EnvVarRow x3 in a DraggableList", drag_list)
        dialog.show()
