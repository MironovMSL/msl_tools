# tools/desktop/maya_gate/sessions_console.py
"""The Sessions tab's console: code sent to the selected Maya, and the snippets."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.theme.qss import make_rounded_popup


class _ConsoleMixin:
    """SessionsTab's console and its snippets (see SessionsTab). A mixin: the state it uses
    is made in SessionsTab.__init__."""

    # --- the console -------------------------------------------------------------------

    def _on_run_code(self) -> None:
        """Runs what is in the console's input, then empties it (the history keeps it)."""
        code = self._console_input.toPlainText().strip(chr(10))
        if self._run_code(code):
            self._console_input.remember(code)
            self._console_input.clear()

    def _run_code(self, code: str) -> bool:
        """Sends `code` to the selected Maya; code, output, result and traceback
        all land in that Maya's log. False if it wasn't sent (no such Maya, no
        code, or the previous run isn't back yet)."""
        session = self._session_by_pid(self._selected_pid)
        if session is None or not session.console or not code.strip() or session.pid in self._console_running:
            return False
        pid = session.pid
        self._add_to_log(pid, protocol.LOG_INPUT, code)
        # Busy is per Maya: a long script in one doesn't keep the console from another
        # (CONSOLE_TIMEOUT_MS is minutes).
        self._console_running.add(pid)
        self._sync_run_button()

        def done(reply: dict) -> None:
            self._console_running.discard(pid)
            self._sync_run_button()
            row = self._rows.get(session.session_id)
            if row is not None:
                row.set_busy(False)
            data = reply.get("data") or {}
            if not reply.get("success"):
                self._add_to_log(pid, protocol.LOG_ERROR, reply.get("error") or "the request failed")
                return
            if data.get("output"):
                self._add_to_log(pid, protocol.LOG_INFO, str(data["output"]).rstrip("\n"))
            if data.get("traceback"):
                self._add_to_log(pid, protocol.LOG_ERROR, str(data["traceback"]).rstrip("\n"))
            elif data.get("result"):
                self._add_to_log(pid, protocol.LOG_INFO, str(data["result"]))

        row = self._rows.get(session.session_id)
        if row is not None:
            row.set_busy(True)
        self._server.request(session.session_id, protocol.RUN_PYTHON, on_reply=done,
                             timeout_ms=self.CONSOLE_TIMEOUT_MS, code=code)
        return True

    # --- snippets ------------------------------------------------------------------------

    def _rebuild_snippets(self) -> None:
        """One chip per saved snippet, in front of "+ Save as snippet"."""
        if self._snippets is None:
            return
        for chip in self._snippet_chips:
            self._snippets_layout.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self._snippet_chips = []
        for name in self._snippets.names():
            chip = qt.QtWidgets.QPushButton(name, self._snippets_bar)
            chip.setObjectName("snippetChip")  # maya_gate.qss
            chip.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            lines = self._snippets.code(name).split(chr(10))
            chip.setToolTip(chr(10).join(lines[:self.SNIPPET_TIP_LINES]
                                         + (["…"] if len(lines) > self.SNIPPET_TIP_LINES else []))
                            + chr(10) + chr(10) + "Click: run it in the selected Maya  ·  right click: edit, delete")
            chip.clicked.connect(lambda _checked=False, name=name: self._run_snippet(name))
            chip.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(
                lambda position, name=name, chip=chip: self._on_snippet_menu(name, chip.mapToGlobal(position)))
            self._snippet_chips.append(chip)
        # FlowLayout keeps the order items were added in: take the two fixed ones out, add them last.
        for widget in (self._save_snippet_button, self._snippet_name):
            self._snippets_layout.removeWidget(widget)
        for widget in self._snippet_chips + [self._save_snippet_button, self._snippet_name]:
            self._snippets_layout.addWidget(widget)
            if widget is not self._snippet_name:
                widget.show()
        self._snippets_layout.invalidate()

    def _run_snippet(self, name: str) -> None:
        if not self._run_code(self._snippets.code(name)) and self._selected_pid in self._console_running:
            self._say("This Maya is still running the previous code.")

    def _sync_run_button(self) -> None:
        """Run is off only while the SELECTED Maya still runs code sent from here."""
        self._run_button.setEnabled(self._selected_pid not in self._console_running)

    def _on_snippet_menu(self, name: str, position) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.addAction(self._menu_icon("play"), "Run").triggered.connect(lambda: self._run_snippet(name))
        menu.addAction(self._menu_icon("edit"), "Edit").triggered.connect(lambda: self._edit_snippet(name))
        menu.addSeparator()
        menu.addAction(self._menu_icon("delete", danger=True), "Delete…").triggered.connect(
            lambda: self._delete_snippet(name))
        self._snippet_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(position)

    def _edit_snippet(self, name: str) -> None:
        """Puts the snippet's code into the console; saving it under the same name replaces it."""
        self._editing_snippet = name
        self._console_input.setPlainText(self._snippets.code(name))
        self._console_input.setFocus()
        self._say(f"“{name}” is in the console — change it, then “+ Save as snippet” (same name replaces it).")

    def _delete_snippet(self, name: str) -> None:
        choice = ConfirmDialog.ask(self, "Delete snippet", f"Delete the snippet “{name}”?",
                                   choices=[("delete", "Delete"), ("cancel", "Cancel")], kind="danger")
        if choice == "delete":
            self._snippets.delete(name)
            self._rebuild_snippets()

    def _on_save_snippet(self) -> None:
        if not self._console_input.toPlainText().strip():
            self._say("Write the code in the console first, then save it as a snippet.")
            return
        self._snippet_name.setText(self._editing_snippet)
        self._snippet_name.show()
        self._snippets_layout.invalidate()
        self._snippet_name.setFocus()
        self._snippet_name.selectAll()

    def _on_snippet_named(self) -> None:
        name = self._snippet_name.text().strip()
        code = self._console_input.toPlainText().strip(chr(10))
        self._snippet_name.hide()
        if not name or not code.strip():
            return
        replaced = name in self._snippets.names()
        self._snippets.save(name, code)
        self._editing_snippet = ""
        self._rebuild_snippets()
        self._say(f"Snippet “{name}” " + ("updated." if replaced else "saved."), "success")
