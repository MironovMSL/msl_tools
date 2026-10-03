# tools/desktop/maya_gate/sessions_tab.py
import os
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import protocol
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.core.environment.processes import is_process_running, process_memory, terminate_process
from msl_tools.msl.tools.desktop.maya_gate.snippets import SnippetStore
from msl_tools.msl.tools.desktop.maya_gate.session_history import (
    LOG_FOLDER_NAME, SessionHistory, SessionRecord, find_autosave, read_log, write_log)
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.maya_link.server import MayaLinkServer
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tinted_menu_icon
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.editors import CodeEditor, LogView
from msl_tools.msl.ui.widgets.atoms.layouts import FlowLayout
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog


class _ConsoleInput(CodeEditor):
    """Private: the console's input — a small Python editor. Ctrl+Enter
    sends it; Ctrl+Up / Ctrl+Down walk through what was sent before."""

    HEIGHT = 74
    HISTORY_KEPT = 50

    run_requested = qt.QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(self.HEIGHT)  # the least; the splitter above it gives it more
        self.setPlaceholderText("Python for the selected Maya \u2014 Ctrl+Enter runs it, Ctrl+Up / Down: earlier code")
        self._history: list[str] = []
        self._history_index = 0   # == len(history): the line being written, not an old one
        self._draft = ""

    def remember(self, code: str) -> None:
        """Adds `code` to the history (called once it was sent)."""
        if code and (not self._history or self._history[-1] != code):
            self._history.append(code)
            del self._history[:-self.HISTORY_KEPT]
        self._history_index = len(self._history)
        self._draft = ""

    def keyPressEvent(self, event) -> None:
        control = bool(event.modifiers() & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        key = event.key()
        if control and key in (qt.QtCore.Qt.Key.Key_Return, qt.QtCore.Qt.Key.Key_Enter):
            self.run_requested.emit()
        elif control and key in (qt.QtCore.Qt.Key.Key_Up, qt.QtCore.Qt.Key.Key_Down) and self._history:
            self._walk_history(-1 if key == qt.QtCore.Qt.Key.Key_Up else 1)
        else:
            super().keyPressEvent(event)

    def _walk_history(self, step: int) -> None:
        if self._history_index == len(self._history):
            self._draft = self.toPlainText()  # what was being written comes back at the end
        self._history_index = max(0, min(len(self._history), self._history_index + step))
        at_end = self._history_index == len(self._history)
        self.setPlainText(self._draft if at_end else self._history[self._history_index])
        self.moveCursor(qt.QtGui.QTextCursor.MoveOperation.End)


class _NameField(qt.QtWidgets.QLineEdit):
    """Private: a one-line field that asks for a name in place — Enter takes
    it (returnPressed), Esc or clicking elsewhere gives up (cancelled)."""

    cancelled = qt.QtCore.Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == qt.QtCore.Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.cancelled.emit()


class _SceneLabel(qt.QtWidgets.QLabel):
    """Private: a scene's file name — "hero_rig_v07.ma", with a "*" while it
    has unsaved changes (as in Maya's title bar). When the scene is a file,
    the NAME (not the empty space after it) is a link: a click shows the file
    in the system's file manager, a right click offers that and "Copy path",
    and it can be DRAGGED — onto a Maya version tile (open it in that Maya),
    or anywhere else that takes a file.

    Signals:
        reveal_failed(str) — neither the file nor its folder is there any more.
    """

    reveal_failed = qt.QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionScene")
        # The scene's name is what gives way in a narrow window (clipped), not the rest.
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self._path = ""
        self._pressed = False
        self._press_position = qt.QtCore.QPoint()

    def set_scene(self, path: str, modified: bool = False) -> None:
        self._path = path
        self.setText((os.path.basename(path) if path else "untitled") + ("*" if modified else ""))
        lines = [path or "This scene hasn’t been saved to a file yet."]
        if modified:
            lines.append("It has unsaved changes.")
        if path:
            lines.append("Click: show in folder  ·  drag onto a Maya version: open it there  ·  "
                         "right click: copy the path")
        self.setToolTip(chr(10).join(lines))

    def reveal(self) -> None:
        """Shows the scene file in the file manager (its folder, if the file is gone)."""
        path = Path(self._path)
        target = path if path.exists() else path.parent
        if not (self._path and target.exists() and ProcessLauncher.open_file_explorer(target)):
            self.reveal_failed.emit(self._path)

    def _over_name(self, event) -> bool:
        return bool(self._path) and event.position().x() <= self.fontMetrics().horizontalAdvance(self.text())

    def _set_hover(self, hover: bool) -> None:
        if bool(self.property("hover")) != hover:
            self.setProperty("hover", hover)  # maya_gate.qss: QLabel#sessionScene[hover="true"]
            repolish(self)
            if hover:
                self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()

    def drag_data(self) -> qt.QtCore.QMimeData:
        """What a drag of this scene carries: the file (as a URL) and its path (as text)."""
        data = qt.QtCore.QMimeData()
        data.setUrls([qt.QtCore.QUrl.fromLocalFile(self._path)])
        data.setText(self._path)
        return data

    def _start_drag(self) -> None:
        drag = qt.QtGui.QDrag(self)
        drag.setMimeData(self.drag_data())
        name_width = min(self.fontMetrics().horizontalAdvance(self.text()) + 4, self.width())
        drag.setPixmap(self.grab(qt.QtCore.QRect(0, 0, name_width, self.height())))
        drag.exec(qt.QtCore.Qt.DropAction.CopyAction)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed and (event.position().toPoint() - self._press_position).manhattanLength() \
                >= qt.QtWidgets.QApplication.startDragDistance():
            self._pressed = False  # it became a drag: the release that follows is not a click
            self._start_drag()
            return
        self._set_hover(self._over_name(event))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hover(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self._over_name(event):
            self._pressed = True
            self._press_position = event.position().toPoint()
            event.accept()  # a click on the name is for the file, not for selecting the row
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed:
            self._pressed = False
            if self._over_name(event):
                self.reveal()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if not self._path:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.addAction("Show in folder").triggered.connect(self.reveal)
        menu.addAction("Copy path").triggered.connect(
            lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._path))
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(event.globalPos())


class _SessionRow(qt.QtWidgets.QWidget):
    """Private: one running Maya — a live dot, "Maya 2025", its environment,
    the open scene, a "boost" mark, how many errors / warnings it has
    printed, how long it has been connected, and ONE "more" button for what
    can be asked of it (a right click on the row opens the same menu). A
    click on the row selects it (its log is shown below the list). The row
    only says what was clicked; the tab builds the menu and talks to Maya."""

    HEIGHT = 30
    DOT_SIZE = 8
    MENU_BUTTON_SIZE = qt.QtCore.QSize(24, 22)

    menu_requested = qt.QtCore.Signal(int)    # session id
    selected = qt.QtCore.Signal(int)

    def __init__(self, session: MayaSession, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)  # for the selected tint (QSS)
        self.setFixedHeight(self.HEIGHT)
        self.dot = qt.QtWidgets.QLabel()
        self.dot.setObjectName("sessionDot")
        self.dot.setFixedSize(self.DOT_SIZE, self.DOT_SIZE)
        self.version_label = qt.QtWidgets.QLabel()
        self.version_label.setObjectName("sessionVersion")
        self.environment_label = qt.QtWidgets.QLabel()
        self.environment_label.setObjectName("sessionEnvironment")
        self.boost_label = qt.QtWidgets.QLabel("boost")
        self.boost_label.setObjectName("sessionBoost")
        self.busy_label = qt.QtWidgets.QLabel("busy")
        self.busy_label.setObjectName("sessionBusy")
        self.busy_label.setToolTip("This Maya isn’t answering right now: it is working "
                                   "(a long script, a heavy scene)." + chr(10) + "Requests wait until it is free.")
        self.scene_label = _SceneLabel()
        self.time_label = qt.QtWidgets.QLabel()
        self.time_label.setObjectName("sessionTime")
        self.errors_label = qt.QtWidgets.QLabel()
        self.errors_label.setObjectName("sessionErrors")
        self.warnings_label = qt.QtWidgets.QLabel()
        self.warnings_label.setObjectName("sessionWarnings")
        self.menu_button = GlyphButton("⋯", "Report, reload code, plug-ins, close, restart",
                                       self.MENU_BUTTON_SIZE)
        icon = UiResources().iconManager.get_icon("more", sub_folder="actions")
        if icon is not None and not icon.isNull():
            self.menu_button.set_icon(icon)
        self.menu_button.clicked.connect(lambda: self.menu_requested.emit(self.session_id))
        self.pending = False  # a request to this Maya is on its way

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)
        layout.addWidget(self.dot)
        layout.addWidget(self.version_label)
        layout.addWidget(self.environment_label)
        layout.addWidget(self.boost_label)
        layout.addWidget(self.busy_label)
        layout.addWidget(self.scene_label, 1)
        layout.addWidget(self.errors_label)
        layout.addWidget(self.warnings_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.menu_button)
        self.set_session(session)
        self.set_problems(0, 0)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.session_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.menu_requested.emit(self.session_id)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            self.setProperty("selected", selected)  # maya_gate.qss: QWidget#sessionRow[selected="true"]
            repolish(self)

    def set_problems(self, errors: int, warnings: int) -> None:
        """Counters of what this Maya printed since it connected (or since "Clear")."""
        self.errors_label.setText(str(errors))
        self.errors_label.setToolTip(f"{errors} error(s) in this Maya’s Script Editor")
        self.errors_label.setVisible(errors > 0)
        self.warnings_label.setText(str(warnings))
        self.warnings_label.setToolTip(f"{warnings} warning(s) in this Maya’s Script Editor")
        self.warnings_label.setVisible(warnings > 0)

    @staticmethod
    def _action(text: str, tooltip: str) -> qt.QtWidgets.QPushButton:
        """A quiet accent link (maya_gate.qss: QPushButton#sessionAction)."""
        button = qt.QtWidgets.QPushButton(text)
        button.setObjectName("sessionAction")
        button.setFlat(True)
        button.setToolTip(tooltip)
        button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        return button

    def set_busy(self, busy: bool) -> None:
        """While Maya works on a request, nothing else can be asked of it: the
        menu stays reachable (a Maya that never answers can still be force
        closed from it), its requests are off."""
        self.pending = busy

    def set_session(self, session: MayaSession, memory: int | None = None) -> None:
        """`memory`: bytes that Maya's process uses right now (None = unknown), for the tooltip."""
        self.session_id = session.session_id
        self.version_label.setText(f"Maya {session.version}")
        self.environment_label.setText(session.environment)
        # Safe here (unlike on a parentless widget): the labels already belong to this row.
        self.environment_label.setVisible(bool(session.environment))
        self.boost_label.setVisible(session.boosted)
        self.busy_label.setVisible(session.busy)
        state = "busy" if session.busy else ""
        if self.dot.property("state") != state:
            self.dot.setProperty("state", state)  # maya_gate.qss: QLabel#sessionDot[state]
            repolish(self.dot)
        self.scene_label.set_scene(session.scene, session.modified)
        self.time_label.setText(session.connected_for())
        lines = [f"Maya {session.full_version or session.version}  ·  process {session.pid}"
                 + (f"  ·  memory {_size(memory)}" if memory else ""),
                 f"Scene: {session.scene or 'untitled'}" + (" (unsaved changes)" if session.modified else "")]
        if session.startup_seconds:
            lines.append(f"Started in {session.startup_seconds:.0f} s"
                         + (f" with boost ({len(session.skipped)} plug-ins not loaded)" if session.boosted else ""))
        elif session.boosted:
            lines.append(f"Started with boost ({len(session.skipped)} plug-ins not loaded)")
        if session.busy and session.busy_since:
            lines.append("Not answering for " + _duration(time.time() - session.busy_since))
        lines.append("Autosave: on" if session.autosave else "Autosave: off — after a crash there is nothing to go back to")
        if session.msl_version:
            lines.append(f"msl_tools {session.msl_version} in that Maya")
        self.setToolTip(chr(10).join(lines))


def _size(size: int) -> str:
    """"640 MB", "3.2 GB"."""
    megabytes = size / 1024 ** 2
    return f"{megabytes:.0f} MB" if megabytes < 1024 else f"{megabytes / 1024:.1f} GB"


def _duration(seconds: float) -> str:
    """"40 s", "3 min", "1 h 05 min"."""
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def _autosave_tip(autosave: str, ended: float) -> str:
    """Tooltip of an "Open autosave" action: which file, and how old it was when Maya went away."""
    try:
        age = _duration(max(ended - os.path.getmtime(autosave), 0)) + " before Maya went away"
    except OSError:
        age = "the file isn’t there any more"
    return ("Start this Maya again with the newest autosave of the scene" + chr(10) + autosave + chr(10)
            + f"Written {age}. Save it under the scene's own name once it is open.")


class _EndedRow(qt.QtWidgets.QWidget):
    """Private: a Maya that is gone without saying goodbye — it crashed, was
    killed, or was force closed from here. Stays in the list until
    dismissed; a click shows its log. If Maya left an autosave of the scene
    that is newer than the scene file, "Open autosave" starts Maya with it."""

    selected = qt.QtCore.Signal(int)        # pid
    file_requested = qt.QtCore.Signal(int)
    reopen_requested = qt.QtCore.Signal(int)
    autosave_requested = qt.QtCore.Signal(int)
    dismissed = qt.QtCore.Signal(int)

    def __init__(self, session: MayaSession, when: float, has_file: bool, can_reopen: bool = False,
                 forced: bool = False, autosave: str = "", parent=None):
        super().__init__(parent)
        self.pid = session.pid
        self.setObjectName("sessionRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(_SessionRow.HEIGHT)

        dot = qt.QtWidgets.QLabel()
        dot.setObjectName("sessionDot")
        dot.setProperty("state", "ended")
        dot.setFixedSize(_SessionRow.DOT_SIZE, _SessionRow.DOT_SIZE)
        version_label = qt.QtWidgets.QLabel(f"Maya {session.version}")
        version_label.setObjectName("sessionVersion")
        environment_label = qt.QtWidgets.QLabel(session.environment)
        environment_label.setObjectName("sessionEnvironment")
        ended_label = qt.QtWidgets.QLabel(("force closed at " if forced else "ended unexpectedly at ")
                                          + time.strftime("%H:%M", time.localtime(when))
                                          + (" · unsaved changes" if session.modified else ""))
        ended_label.setObjectName("sessionEnded")
        ended_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        file_button = _SessionRow._action("Log file", "Show the log saved when this Maya went away")
        file_button.clicked.connect(lambda: self.file_requested.emit(self.pid))
        dismiss_button = _SessionRow._action("Dismiss", "Remove this line (it stays in Recent sessions)")
        dismiss_button.clicked.connect(lambda: self.dismissed.emit(self.pid))

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(dot)
        layout.addWidget(version_label)
        layout.addWidget(environment_label)
        layout.addWidget(ended_label, 1)
        layout.addWidget(file_button)
        if can_reopen and autosave:
            autosave_button = _SessionRow._action("Open autosave", _autosave_tip(autosave, when))
            autosave_button.clicked.connect(lambda: self.autosave_requested.emit(self.pid))
            layout.addWidget(autosave_button)
        if can_reopen and session.scene:
            reopen_button = _SessionRow._action("Reopen", "Start this Maya again, in the same environment, "
                                                          "with this scene as it was last SAVED")
            reopen_button.clicked.connect(lambda: self.reopen_requested.emit(self.pid))
            layout.addWidget(reopen_button)
        layout.addWidget(dismiss_button)
        environment_label.setVisible(bool(session.environment))  # safe: it already belongs to this row
        file_button.setVisible(has_file)
        lines = [f"Maya {session.full_version or session.version}  ·  process {session.pid}",
                 "It was force closed from here." if forced else
                 "Its connection dropped without a goodbye: Maya crashed or was closed by force.",
                 f"Scene at the time: {session.scene or 'untitled'}"
                 + (" (with unsaved changes)" if session.modified else "")]
        if autosave:
            lines.append("Autosave: " + autosave)
        elif session.modified:
            lines.append("No autosave of it was found" + ("." if session.autosave else " — Maya's autosave was off."))
        self.setToolTip(chr(10).join(lines))

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.pid)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            self.setProperty("selected", selected)
            repolish(self)


class _HistoryRow(qt.QtWidgets.QWidget):
    """Private: a Maya session that is over (a SessionRecord). A hollow dot =
    it quit, a red one = it ended unexpectedly. A click selects it — its
    saved log is shown below the list; "Log file" shows that file, "Reopen"
    starts that Maya again with the same scene; the scene's name is the
    same link as in a live row."""

    selected = qt.QtCore.Signal(object)           # the record's key
    file_requested = qt.QtCore.Signal(str)        # path of the saved log
    reopen_requested = qt.QtCore.Signal(object)   # the record
    autosave_requested = qt.QtCore.Signal(object)

    def __init__(self, record: SessionRecord, can_reopen: bool = False, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("sessionRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)  # for the selected tint (QSS)
        self.setFixedHeight(_SessionRow.HEIGHT)

        dot = qt.QtWidgets.QLabel()
        dot.setObjectName("sessionDot")
        dot.setProperty("state", "closed" if record.clean else "ended")
        dot.setFixedSize(_SessionRow.DOT_SIZE, _SessionRow.DOT_SIZE)
        version_label = qt.QtWidgets.QLabel(f"Maya {record.version}")
        version_label.setObjectName("sessionVersion")
        version_label.setProperty("past", True)
        environment_label = qt.QtWidgets.QLabel(record.environment)
        environment_label.setObjectName("sessionEnvironment")
        self.scene_label = _SceneLabel()
        self.scene_label.set_scene(record.scene, record.modified)
        self.scene_label.setProperty("past", True)
        self.outcome_label = qt.QtWidgets.QLabel(record.outcome_text())
        self.outcome_label.setObjectName("sessionOutcome")
        self.outcome_label.setProperty("state", "" if record.clean else "error")
        self.time_label = qt.QtWidgets.QLabel(f"{record.ended_text()}  ·  {record.duration_text()}")
        self.time_label.setObjectName("sessionTime")

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(dot)
        layout.addWidget(version_label)
        layout.addWidget(environment_label)
        layout.addWidget(self.scene_label, 1)
        layout.addWidget(self.outcome_label)
        if record.log_file:
            file_button = _SessionRow._action("Log file", "Show the file this session’s log was saved to")
            file_button.clicked.connect(lambda: self.file_requested.emit(self.record.log_file))
            layout.addWidget(file_button)
        if can_reopen and record.autosave:
            autosave_button = _SessionRow._action("Autosave", _autosave_tip(record.autosave, record.ended_at))
            autosave_button.clicked.connect(lambda: self.autosave_requested.emit(self.record))
            layout.addWidget(autosave_button)
        if can_reopen and record.scene:
            reopen_button = _SessionRow._action("Reopen", "Start this Maya again, in the same environment, "
                                                          "with this scene")
            reopen_button.clicked.connect(lambda: self.reopen_requested.emit(self.record))
            layout.addWidget(reopen_button)
        layout.addWidget(self.time_label)
        if not record.environment:
            environment_label.hide()
        lines = [f"Maya {record.version}  ·  process {record.pid}",
                 "Started " + time.strftime("%d %b %H:%M", time.localtime(record.connected_at))
                 + ", " + record.outcome_text() + " "
                 + time.strftime("%d %b %H:%M", time.localtime(record.ended_at)) + f" ({record.duration_text()})",
                 f"Scene at the end: {record.scene or 'untitled'}"
                 + (" (with unsaved changes)" if record.modified else "")]
        if not record.clean:
            lines.append("It was force closed from here." if record.forced else
                         "Its connection dropped without a goodbye: Maya crashed or was closed by force.")
        if record.autosave:
            lines.append("Autosave: " + record.autosave)
        lines.append("Click: show what it reported" if record.log_file else "It reported no warnings or errors.")
        self.setToolTip(chr(10).join(lines))

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.selected.emit(self.record.key)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            self.setProperty("selected", selected)
            repolish(self)


class SessionsTab(qt.QtWidgets.QWidget):
    """Maya Gate's "Sessions" tab: the Mayas running right now that were
    started from the hub — live, through the hub <-> Maya link
    (ui/maya_link/server.py; each Maya connects by itself on startup).

    Unlike the other tabs it isn't about ONE environment's settings: it
    lists every connected Maya, whatever environment it was started in.

    Each row shows version, environment, open scene, boost and the time
    since it connected. A Maya that closes (or crashes) leaves the list at
    once — its connection drops.

    What can be asked of a running Maya (MayaLinkServer.request(), a fixed
    list — see core/link/protocol.py):
    - Report: its launch report, shown here in a TextDialog;
    - Reload code: re-read msl_tools from disk in that Maya (its link
      restarts on the new code, so the row blinks out and back);
    - Plug-ins (boosted sessions): a menu of the plug-ins boost start left
      out — load one, or all, in that Maya without restarting it.
    The outcome of the last request is the line under the list.

    The log (below the list): what the SELECTED Maya's Script Editor prints,
    as it happens — warnings and errors, or everything except command echo
    with the "All" switch (asked of Maya with SET_LOG_LEVEL, so plain
    messages don't travel unless someone wants them). Each row counts its
    errors / warnings. Logs are kept per Maya PROCESS (pid), so "Reload
    code" — which gives the session a new id — doesn't lose them; a Maya
    that closed (or crashed) keeps its log on screen for GONE_GRACE_S.

    Around the list: a Maya that doesn't answer the server's pings shows
    "busy" (its dot turns to the warning tone). A Maya that went away
    WITHOUT a goodbye (MayaLinkServer.session_ended, clean=False) — crashed
    or killed — stays as an "ended unexpectedly" line until dismissed, with
    its log written to logs/desktop/maya_gate/sessions/. Errors that come
    in while the tab isn't on screen are counted for the server's
    unread_errors (the tab's title and the header's indicator show a mark),
    and cleared when the tab is shown.

    Scenes: a row's scene name carries a "*" while that scene has unsaved
    changes, and is a link to the file (_SceneLabel).

    History: every session that is over is kept (SessionHistory — it
    survives a hub restart) together with what it reported, as a log file.
    "Recent sessions" sits under the live rows: open while nothing runs,
    folded (a click on its caption opens it) while a Maya does. A click on
    one of them shows its saved log below; "Reopen" starts that Maya again
    with the same scene. A link restart ("Reload code") and the hub's own
    shutdown are not ends of a session.

    Close / Restart (a row's "Close"): asks first — with unsaved changes it
    offers to save, to drop them, or to leave Maya alone — then sends QUIT.
    Maya checks the scene again itself and refuses if it changed meanwhile.
    A restart waits until that Maya's process is really gone (it is still
    writing its preferences), then starts the same version in the same
    environment with the same scene.

    A Maya that doesn't answer (busy) gets "Force close…" in its menu: its
    process is ended after a question; it then reads "force closed", not
    "ended unexpectedly". After any unclean end the newest autosave Maya
    wrote for the scene (find_autosave — Maya reports its autosave folder)
    is offered as "Open autosave".

    The tab launches nothing itself: `launch(year, environment, scene)` is
    handed in by the page (it returns "" or what went wrong); without it
    there is no Restart / Reopen. `settings` is where the log's "Wrap"
    switch is remembered ("log_wrap").

    The console (under the log, only while the selected Maya allows it —
    one started in a Dev environment): a small Python editor; Ctrl+Enter or
    "Run" sends the code to that Maya (RUN_PYTHON), which runs it like its
    Script Editor would. The code, what it printed, its result or its
    traceback go into that Maya's log. Whether a Maya accepts code is
    decided by Maya itself (it was launched with MSL_GATE_CONSOLE=1); the
    tab only hides the console where it would be refused.
    Snippets (SnippetStore): code saved under a name becomes a chip above
    the input — a click runs it in the selected Maya, a right click offers
    Edit (the code goes into the input) and Delete. "+ Save as snippet"
    asks for the name in place (_NameField).

    Colors: maya_gate.qss (SessionsTab ...).
    """

    REFRESH_MS = 30_000  # "12 min" labels
    CONSOLE_TIMEOUT_MS = 600_000  # code may run long; Maya is busy meanwhile anyway
    MESSAGE_MS = 8000    # how long the last request's outcome stays
    REPORT_TIMEOUT_MS = 15_000
    RELOAD_TIMEOUT_MS = 20_000
    PLUGINS_TIMEOUT_MS = 180_000  # loading heavy plug-ins takes Maya a while
    LIST_ROWS_SHOWN = 4           # the list is this tall at most; the log gets the rest
    LOG_PROBLEMS, LOG_ALL = "Problems", "All"
    LOG_KEPT = 2000               # entries kept per Maya
    GONE_GRACE_S = 60             # how long a Maya that left keeps its log (and the selection)
    RELOAD_GRACE_S = 5            # ... and how long one that left with an empty log does
    QUIT_TIMEOUT_MS = 120_000     # "save and close": saving a heavy scene takes Maya a while
    RESTART_WAIT_S = 90           # how long a restart waits for the old Maya's process to be gone
    LOG_PLACEHOLDER = "Warnings and errors from the selected Maya’s Script Editor appear here."
    SNIPPET_TIP_LINES = 12        # lines of a snippet's code shown in its chip's tooltip
    MENU_ICON_SIZE = 16

    # Colors of the row menu's icons (maya_gate.qss): a menu's icons are QIcons, which QSS
    # can't tint - the tab takes the colors as properties and tints them when the menu opens.
    menuIconColor = color_property("_menu_icon_color", None)
    menuDangerColor = color_property("_menu_danger_color", None)
    HISTORY_CAPTION_HEIGHT = 24

    def __init__(self, server: MayaLinkServer, history: SessionHistory | None = None, launch=None,
                 settings=None, snippets: SnippetStore | None = None, parent=None):
        super().__init__(parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._menu_icon_color = qt.QtGui.QColor(fallback.text_secondary)
        self._menu_danger_color = qt.QtGui.QColor(fallback.error)
        self._snippets = snippets                 # None: the console has no snippets
        self._snippet_chips: list = []
        self._snippets_shown = False              # the snippet file is first read when the console shows
        self._editing_snippet = ""                # the snippet whose code was put into the editor to change
        self._server = server
        self._history = history                   # None: finished sessions aren't kept
        self._launch = launch                     # (year, environment, scene) -> "" or an error; None: can't launch
        self._settings = settings                 # a mapping that remembers "log_wrap"; None: not remembered
        self._history_open: bool | None = None    # None: open while nothing runs, folded otherwise
        self._history_open_while = False          # ... the caption's click holds while this stays as it was
        self._history_shown_open = False
        self._history_selected = None             # key of the finished session whose log is shown
        self._restarts: dict[int, tuple] = {}     # pid -> (asked at, version, environment, scene): start again once gone
        self._forced: set[int] = set()            # pids force closed from here (their end isn't a crash)
        self._history_rows: list[_HistoryRow] = []
        self._history_key = None                  # what the history rows on screen were built from
        self._seen = False                        # the history file is first read when the tab is shown
        self._names: dict[int, str] = {}          # pid -> "Maya 2025 · Dev" (for a closed Maya's log title)
        self._rows: dict[int, _SessionRow] = {}
        self._logs: dict[int, list] = {}          # pid -> [(level, text, time), ...]
        self._problems: dict[int, list] = {}      # pid -> [errors, warnings]
        self._selected_pid = 0
        self._gone: dict[int, float] = {}         # pid -> when that Maya left (its log is kept a while)
        self._ended: dict[int, dict] = {}         # pid -> {"session", "when", "file"}: gone without a goodbye
        self._ended_rows: dict[int, _EndedRow] = {}
        self._log_all = False

        self._title_label = qt.QtWidgets.QLabel("Sessions")
        self._title_label.setObjectName("sessionsTitle")
        self._summary_label = qt.QtWidgets.QLabel()
        self._summary_label.setObjectName("sessionsSummary")
        self._status_label = qt.QtWidgets.QLabel()
        self._status_label.setObjectName("sessionsStatus")

        self._list = qt.QtWidgets.QWidget()
        self._list_layout = qt.QtWidgets.QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(0)
        self._empty_label = qt.QtWidgets.QLabel()
        self._empty_label.setObjectName("sessionsEmpty")
        self._empty_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._list_layout.addWidget(self._empty_label)
        self._history_caption = qt.QtWidgets.QWidget()
        self._history_caption.setFixedHeight(self.HISTORY_CAPTION_HEIGHT)
        self._history_toggle = qt.QtWidgets.QPushButton()
        self._history_toggle.setObjectName("sessionsHistoryToggle")
        self._history_toggle.setFlat(True)
        self._history_toggle.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._history_toggle.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._history_toggle.setToolTip("The Maya sessions that are over — click to show or fold them")
        self._clear_history_button = _SessionRow._action("Clear", "Forget these sessions and delete their saved logs")
        caption_layout = qt.QtWidgets.QHBoxLayout(self._history_caption)
        caption_layout.setContentsMargins(8, 0, 6, 0)
        caption_layout.addWidget(self._history_toggle)
        caption_layout.addStretch(1)
        caption_layout.addWidget(self._clear_history_button)
        self._history_toggle.clicked.connect(self._on_toggle_history)
        self._list_layout.addWidget(self._history_caption)
        self._history_caption.hide()
        self._clear_history_button.clicked.connect(self._on_clear_history)
        self._list_layout.addStretch(1)
        self._scroll = StableScrollArea()
        self._scroll.setObjectName("sessionsScroll")
        self._scroll.setWidget(self._list)

        self._log_title = qt.QtWidgets.QLabel("Log")
        self._log_title.setObjectName("sessionsTitle")
        self._log_section = qt.QtWidgets.QLabel()
        self._log_section.setObjectName("sessionsSummary")
        self._log_section.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._level_switch = SegmentedControl([self.LOG_PROBLEMS, self.LOG_ALL], self.LOG_PROBLEMS)
        self._level_switch.setToolTip("Problems: warnings and errors.\nAll: also what scripts print (not the command echo).")
        self._copy_log_button = _SessionRow._action("Copy", "Copy the log")
        self._clear_log_button = _SessionRow._action("Clear", "Empty this Maya\u2019s log here (nothing changes in Maya)")
        self._log_view = LogView(self.LOG_PLACEHOLDER)
        wrap = bool(self._settings.get("log_wrap", True)) if self._settings is not None else True
        self._log_view.set_wrap(wrap)
        self._wrap_button = qt.QtWidgets.QPushButton("Wrap")
        self._wrap_button.setObjectName("sessionToggle")  # maya_gate.qss: quiet, accent while on
        self._wrap_button.setFlat(True)
        self._wrap_button.setCheckable(True)
        self._wrap_button.setChecked(wrap)
        self._wrap_button.setToolTip("Long lines continue on the next line instead of running off to the right")
        self._wrap_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._wrap_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self._wrap_button.toggled.connect(self._on_wrap_toggled)

        self._console_input = _ConsoleInput()
        self._run_button = qt.QtWidgets.QPushButton("Run")
        self._run_button.setProperty("primary", True)
        self._run_button.setToolTip("Run this code in the selected Maya (Ctrl+Enter)")
        # Snippets: saved pieces of code as chips above the input - one click runs one.
        self._save_snippet_button = _SessionRow._action(
            "+ Save as snippet", "Keep the code in the console under a name — it becomes a chip here, "
                                 "one click runs it in the selected Maya")
        self._snippet_name = _NameField()
        self._snippet_name.setPlaceholderText("Snippet name, then Enter")
        self._snippet_name.setFixedWidth(190)
        self._snippets_bar = qt.QtWidgets.QWidget()
        self._snippets_layout = FlowLayout(self._snippets_bar, spacing=6)
        self._snippets_layout.addWidget(self._save_snippet_button)
        self._snippets_layout.addWidget(self._snippet_name)
        self._snippet_name.hide()
        self._save_snippet_button.clicked.connect(self._on_save_snippet)
        self._snippet_name.returnPressed.connect(self._on_snippet_named)
        self._snippet_name.cancelled.connect(self._snippet_name.hide)

        self._console = qt.QtWidgets.QWidget()
        input_row = qt.QtWidgets.QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)
        input_row.addWidget(self._console_input, 1)
        input_row.addWidget(self._run_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignBottom)
        console_layout = qt.QtWidgets.QVBoxLayout(self._console)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(4)
        console_layout.addWidget(self._snippets_bar)
        console_layout.addLayout(input_row)
        if self._snippets is None:
            self._snippets_bar.hide()
        self._console.hide()
        self._console_input.run_requested.connect(self._on_run_code)
        self._run_button.clicked.connect(self._on_run_code)

        self._message_label = qt.QtWidgets.QLabel()
        self._message_label.setObjectName("sessionsMessage")
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(self.MESSAGE_MS)
        self._message_timer.timeout.connect(self._message_label.hide)

        self._hint_label = qt.QtWidgets.QLabel(
            "Every Maya started from here connects to MSL Tools by itself and shows up in this list. "
            "Maya 2020 and Mayas started some other way don’t.")
        self._hint_label.setObjectName("sessionsHint")
        self._hint_label.setWordWrap(True)

        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_label)
        header.addWidget(self._summary_label, 1)
        header.addWidget(self._status_label)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        log_header = qt.QtWidgets.QHBoxLayout()
        log_header.setContentsMargins(0, 2, 0, 0)
        log_header.setSpacing(6)
        log_header.addWidget(self._log_title)
        log_header.addWidget(self._log_section, 1)
        log_header.addWidget(self._wrap_button)
        log_header.addWidget(self._copy_log_button)
        log_header.addWidget(self._clear_log_button)
        log_header.addWidget(self._level_switch)

        layout.addLayout(header)
        layout.addWidget(self._scroll)
        layout.addWidget(self._message_label)
        layout.addLayout(log_header)
        # The log over the console, with a handle between them: drag it to give the console the
        # room of a real editor (taken from the log) or to get the log back. Remembered.
        self._split = qt.QtWidgets.QSplitter(qt.QtCore.Qt.Orientation.Vertical)
        self._split.setObjectName("sessionsSplit")
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(6)
        self._split.addWidget(self._log_view)
        self._split.addWidget(self._console)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        self._split.splitterMoved.connect(self._on_split_moved)
        self._log_view.setMinimumHeight(60)
        layout.addWidget(self._split, 1)
        layout.addWidget(self._hint_label)

        self._server.log_received.connect(self._on_log)
        self._server.session_ended.connect(self._on_session_ended)
        self._level_switch.current_changed.connect(self._on_level_changed)
        self._copy_log_button.clicked.connect(
            lambda: qt.QtGui.QGuiApplication.clipboard().setText(self._log_view.plain_text()))
        self._clear_log_button.clicked.connect(self._on_clear_log)

        self._timer = qt.QtCore.QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._server.sessions_changed.connect(self.refresh)
        self._server.listening_changed.connect(self.refresh)
        self.refresh()

    def _place_split(self) -> None:
        """The console at its remembered height (the first time: just its few lines)."""
        if not self._console.isVisible():
            return
        least = self._console.minimumSizeHint().height()
        wanted = least
        if self._settings is not None:
            try:
                wanted = int(self._settings.get("console_height", least) or least)
            except (TypeError, ValueError):
                wanted = least
        total = self._split.height() - self._split.handleWidth()
        height = max(least, min(wanted, total - self._log_view.minimumHeight()))
        self._split.setSizes([max(0, total - height), height])

    def _on_split_moved(self, *_args) -> None:
        if self._settings is not None and self._console.isVisible():
            self._settings["console_height"] = self._split.sizes()[1]

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._server.set_unread_errors(0)  # whatever came in meanwhile is being looked at now
        self._seen = True
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self) -> None:
        """Brings the rows in line with the server's sessions."""
        sessions = {session.session_id: session for session in self._server.sessions()}
        for session_id in [key for key in self._rows if key not in sessions]:
            row = self._rows.pop(session_id)
            row.hide()
            row.deleteLater()
        for index, (session_id, session) in enumerate(sessions.items()):
            row = self._rows.get(session_id)
            if row is None:
                row = _SessionRow(session)
                row.set_session(session, process_memory(session.pid))
                row.menu_requested.connect(self._on_row_menu)
                row.selected.connect(self._select_session)
                row.scene_label.reveal_failed.connect(self._on_reveal_failed)
                self._rows[session_id] = row
                if self._log_all:  # a Maya that just joined (or reloaded) starts on "Problems"
                    self._server.request(session_id, protocol.SET_LOG_LEVEL, **{"all": True})
                self._list_layout.insertWidget(index, row)
            else:
                row.set_session(session, process_memory(session.pid))

        # Mayas that ended unexpectedly: listed under the live ones until dismissed.
        live_pids = {session.pid for session in sessions.values()}
        for pid in [pid for pid in self._ended if pid in live_pids]:
            info = self._ended.pop(pid)  # it is back (an older Maya restarting its link): not ended after all
            if self._history is not None:
                self._history.discard(pid, info["when"])
        for pid in [pid for pid in self._ended_rows if pid not in self._ended]:
            row = self._ended_rows.pop(pid)
            row.hide()
            row.deleteLater()
        for offset, (pid, info) in enumerate(self._ended.items()):
            if pid not in self._ended_rows:
                row = _EndedRow(info["session"], info["when"], info["file"] is not None, self._launch is not None,
                                info.get("forced", False), info.get("autosave", ""))
                row.reopen_requested.connect(self._on_reopen_ended)
                row.autosave_requested.connect(lambda pid: self._open_autosave(
                    self._ended[pid]["session"].version, self._ended[pid]["session"].environment,
                    self._ended[pid]["autosave"]) if pid in self._ended else None)
                row.selected.connect(self._select_pid)
                row.file_requested.connect(self._on_show_log_file)
                row.dismissed.connect(self._on_dismiss_ended)
                self._ended_rows[pid] = row
                self._list_layout.insertWidget(len(sessions) + offset, row)

        count = len(sessions)
        self._summary_label.setText("" if not count else f"· {count} running")
        if self._server.is_listening():
            self._status_label.setText(f"listening on port {self._server.port()}")
            self._status_label.setProperty("state", "")
            self._empty_label.setText("No Maya is running from here.\nStart one with the icons above.")
        else:
            self._status_label.setText("not listening")
            self._status_label.setProperty("state", "error")
            self._empty_label.setText("MSL Tools isn’t listening for Maya sessions.\n"
                                      + (self._server.error_text() or "It starts with the first launch."))
        repolish(self._status_label)
        # The sessions that are over: under the live ones — open while nothing runs, folded
        # while a Maya does (unless the caption was clicked). One that still waits above as
        # an "ended unexpectedly" line isn't listed twice.
        listed = count + len(self._ended)
        waiting = {(pid, info["when"]) for pid, info in self._ended.items()}
        records = [record for record in self._history_records() if record.key not in waiting]
        if self._history_open is not None and self._history_open_while != bool(listed):
            self._history_open = None  # the caption was clicked in the other situation: back to the default
        opened = self._history_open if self._history_open is not None else not listed
        if self._history_selected is not None and self._history_selected not in {record.key for record in records}:
            self._history_selected = None  # it was cleared away
            self._show_log()
        self._show_history(records, opened)
        self._empty_label.setVisible(not listed and not records)
        if records and not count:
            self._summary_label.setText("· none running")

        # The list is as tall as its rows (up to LIST_ROWS_SHOWN); the log gets the rest.
        if not listed and not records:
            self._scroll.setFixedHeight(_SessionRow.HEIGHT + 10 + 26)
        else:
            rows = listed + (len(records) if opened else 0)
            self._scroll.setFixedHeight(min(rows, self.LIST_ROWS_SHOWN) * _SessionRow.HEIGHT
                                        + (self.HISTORY_CAPTION_HEIGHT if records else 0) + 10)

        # Selection follows the PROCESS. A Maya that leaves keeps its log (and the selection)
        # for GONE_GRACE_S: "Reload code" makes it leave and rejoin under a new session id,
        # and a Maya that just crashed is exactly the one whose log one wants to read.
        pids = {session.pid: session for session in sessions.values()}
        now = time.time()
        for pid in list(self._logs) + [self._selected_pid]:
            if pid and pid not in pids and pid not in self._ended:  # an ended Maya keeps its log until dismissed
                self._gone.setdefault(pid, now)
        for pid in [pid for pid in self._gone if pid in pids]:
            del self._gone[pid]
        expired = {pid for pid, since in self._gone.items() if now - since > self.GONE_GRACE_S}
        for pid, session in pids.items():
            self._names[pid] = f"Maya {session.version}" + (f" · {session.environment}" if session.environment else "")
        selected_here = self._selected_pid in pids or self._selected_pid in self._ended
        # A Maya that left with nothing in its log holds the selection only long enough to
        # come back from a "Reload code"; one with a log holds it for the whole grace time.
        left_empty = (not self._logs.get(self._selected_pid)
                      and now - self._gone.get(self._selected_pid, now) > self.RELOAD_GRACE_S)
        if not selected_here and self._history_selected is None \
                and (not self._selected_pid or self._selected_pid in expired or left_empty):
            if pids:
                self._selected_pid = next(iter(pids))
                self._show_log()
            elif self._selected_pid and not self._logs.get(self._selected_pid):
                self._selected_pid = 0  # that Maya is gone and left nothing to read
        for pid in expired:
            if pid != self._selected_pid:
                self._logs.pop(pid, None)
                self._problems.pop(pid, None)
                self._gone.pop(pid, None)
                self._names.pop(pid, None)
        for session_id, row in self._rows.items():
            session = sessions[session_id]
            row.set_selected(session.pid == self._selected_pid)
            row.set_problems(*self._problems.get(session.pid, [0, 0]))
        for pid, row in self._ended_rows.items():
            row.set_selected(pid == self._selected_pid)
        for row in self._history_rows:
            row.set_selected(row.record.key == self._history_selected)
        self._clear_log_button.setEnabled(self._history_selected is None)
        self._update_log_title(pids.get(self._selected_pid))
        # The console: only for a selected Maya that is here and accepts code.
        selected = pids.get(self._selected_pid)
        console_was_shown = self._console.isVisible()
        self._console.setVisible(selected is not None and selected.console)
        if self._console.isVisible() and not console_was_shown:
            qt.QtCore.QTimer.singleShot(0, self._place_split)  # once the splitter knows its own height
        if self._console.isVisible() and not self._snippets_shown:
            self._snippets_shown = True  # first time the console is on screen: read the snippets
            self._rebuild_snippets()

    # --- the log ---------------------------------------------------------------------

    def _session_by_pid(self, pid: int) -> MayaSession | None:
        return next((session for session in self._server.sessions() if session.pid == pid), None)

    def _update_log_title(self, session: MayaSession | None) -> None:
        record = self._selected_record()
        if record is not None:
            text = (f"· Maya {record.version}" + (f" · {record.environment}" if record.environment else "")
                    + " · " + record.outcome_text() + " " + record.ended_text())
        elif session is not None:
            text = "· " + self._names.get(session.pid, f"Maya {session.version}")
        elif self._selected_pid in self._ended:
            ended = self._ended[self._selected_pid]["session"]
            text = (f"· Maya {ended.version}" + (f" · {ended.environment}" if ended.environment else "")
                    + (" · force closed" if self._ended[self._selected_pid].get("forced") else " · ended unexpectedly"))
        elif self._selected_pid and self._logs.get(self._selected_pid):
            # A Maya that closed: its log stays readable for a while. Without a log there is nothing to title.
            text = "· " + self._names.get(self._selected_pid, "that Maya") + " · closed"
        else:
            text = ""
        self._log_section.setText(text)

    def _select_session(self, session_id: int) -> None:
        session = self._server.session(session_id)
        if session is None or (session.pid == self._selected_pid and self._history_selected is None):
            return
        if self._selected_pid in self._gone:  # leaving a closed Maya's log: it isn't kept any longer
            self._logs.pop(self._selected_pid, None)
            self._problems.pop(self._selected_pid, None)
            self._gone.pop(self._selected_pid, None)
        self._history_selected = None
        self._selected_pid = session.pid
        self._show_log()
        self.refresh()

    def _selected_record(self) -> SessionRecord | None:
        """The finished session whose saved log is shown (None: a live Maya's log is)."""
        if self._history_selected is None:
            return None
        return next((row.record for row in self._history_rows if row.record.key == self._history_selected), None) \
            or next((record for record in self._history_records() if record.key == self._history_selected), None)

    def _show_log(self) -> None:
        record = self._selected_record()
        if record is None:
            self._log_view.setPlaceholderText(self.LOG_PLACEHOLDER)
            self._log_view.set_entries(self._logs.get(self._selected_pid, []))
            return
        entries = read_log(record.log_file, record.ended_at) if record.log_file else []
        self._log_view.setPlaceholderText("That Maya reported no warnings or errors." if entries is not None
                                          else "The saved log of that session isn’t there any more.")
        self._log_view.set_entries(entries or [])

    def _on_log(self, session_id: int, entries: list) -> None:
        """Script Editor output of one Maya: kept for that process, shown if it is the selected one."""
        session = self._server.session(session_id)
        if session is None:
            return
        now = time.time()
        log = self._logs.setdefault(session.pid, [])
        problems = self._problems.setdefault(session.pid, [0, 0])
        for level, text in entries:
            log.append((level, text, now))
            if level == protocol.LOG_ERROR:
                problems[0] += 1
            elif level == protocol.LOG_WARNING:
                problems[1] += 1
            if session.pid == self._selected_pid:
                self._log_view.append_entry(level, text, now)
        del log[:-self.LOG_KEPT]
        row = self._rows.get(session_id)
        if row is not None:
            row.set_problems(*problems)
        # Errors that arrive while this tab isn't on screen: the tab's title and the
        # header's indicator carry a mark until someone looks.
        new_errors = sum(1 for level, _text in entries if level == protocol.LOG_ERROR)
        if new_errors and not self.isVisible():
            self._server.set_unread_errors(self._server.unread_errors() + new_errors)

    # --- a Maya that ended unexpectedly ---------------------------------------------------

    def _on_session_ended(self, session: MayaSession, clean: bool, reason: str) -> None:
        """A session is gone. Every real end goes into the history, with what
        that Maya reported saved as a file; one without a goodbye (a crash, a
        killed process) also stays in the list until dismissed."""
        if reason in (protocol.BYE_RESTART, MayaLinkServer.ENDED_BY_HUB):
            return  # its link restarts ("Reload code") / the hub is the one leaving: that Maya is still running
        now = time.time()
        record = SessionRecord(
            pid=session.pid, version=session.version, environment=session.environment, scene=session.scene,
            modified=session.modified, boosted=session.boosted, connected_at=session.connected_at,
            ended_at=now, clean=clean)
        if not clean:
            record.forced = session.pid in self._forced
            self._forced.discard(session.pid)
            # What Maya itself saved along the way: the newest autosave of this scene, if any.
            record.autosave = find_autosave(session.autosave_folder, session.scene, session.connected_at)
        entries = self._logs.get(session.pid, [])
        file = None
        if entries or not clean:
            folder = Path(Resources().fsManager.logsDesktop) / "maya_gate" / LOG_FOLDER_NAME
            file = write_log(folder, record, entries, session.full_version)
            record.log_file = str(file) if file is not None else ""
        if not clean:
            self._ended[session.pid] = {"session": session, "when": now, "file": file,
                                        "forced": record.forced, "autosave": record.autosave}
            self._gone.pop(session.pid, None)
            self._say(f"Maya {session.version} " + ("was force closed" if record.forced else "ended unexpectedly")
                      + " — its log was saved."
                      + (" Its newest autosave can be opened from its line." if record.autosave else ""), "error")
            if not self.isVisible() and not record.forced:
                self._server.set_unread_errors(self._server.unread_errors() + 1)
        if self._history is not None:
            self._history.add(record)
        self.refresh()
        restart = self._restarts.pop(session.pid, None)
        if restart is not None and clean and now - restart[0] < self.RESTART_WAIT_S:
            self._start_when_gone(session.pid, *restart[1:], deadline=now + self.RESTART_WAIT_S)

    # --- the sessions that are over ---------------------------------------------------------

    def _history_records(self) -> list:
        """The finished sessions. Nothing before the tab was first shown: the
        history file isn't read while the page is being built."""
        if self._history is None or not self._seen:
            return []
        return self._history.records()

    def _show_history(self, records: list, opened: bool) -> None:
        """Brings the caption and the history rows in line with `records`
        ([] = no history at all); rows only while `opened`."""
        self._history_shown_open = opened
        self._history_caption.setVisible(bool(records))
        self._history_toggle.setText(("▾" if opened else "▸") + f"  Recent sessions · {len(records)}")
        self._clear_history_button.setVisible(opened)
        key = ([record.key for record in records], opened)
        if key == self._history_key:
            return
        self._history_key = key
        for row in self._history_rows:
            row.hide()
            row.deleteLater()
        self._history_rows = []
        first = self._list_layout.indexOf(self._history_caption) + 1
        for offset, record in enumerate(records if opened else []):
            row = _HistoryRow(record, self._launch is not None)
            row.selected.connect(self._select_history)
            row.file_requested.connect(self._on_show_history_file)
            row.reopen_requested.connect(lambda r: self._start(r.version, r.environment, r.scene))
            row.autosave_requested.connect(lambda r: self._open_autosave(r.version, r.environment, r.autosave))
            row.scene_label.reveal_failed.connect(self._on_reveal_failed)
            self._history_rows.append(row)
            self._list_layout.insertWidget(first + offset, row)

    def _on_toggle_history(self) -> None:
        self._history_open = not self._history_shown_open
        self._history_open_while = bool(self._rows or self._ended)  # (something is listed above the caption)
        self.refresh()

    def _select_history(self, key) -> None:
        """Shows the saved log of a finished session."""
        if key == self._history_selected:
            return
        self._history_selected = key
        self._selected_pid = 0
        self._show_log()
        self.refresh()

    def _on_clear_history(self) -> None:
        if self._history is not None:
            for record in self._history.records():
                if record.log_file and record.pid not in self._ended:  # a waiting "ended" line keeps its file
                    try:
                        if Path(record.log_file).parent.name == LOG_FOLDER_NAME:
                            Path(record.log_file).unlink()
                    except OSError:
                        pass
            self._history.clear()
        self.refresh()

    def _on_show_history_file(self, path: str) -> None:
        if not ProcessLauncher.open_file_explorer(path):
            self._say("That log file isn’t there any more.", "error")

    def _on_reveal_failed(self, path: str) -> None:
        self._say(f"That scene isn’t there any more: {path}", "error")

    # --- starting, closing, restarting a Maya -----------------------------------------------

    def _start(self, version: str, environment: str, scene: str) -> None:
        """Asks the page to start Maya `version` in `environment` with `scene`; says how it went."""
        if self._launch is None:
            return
        error = self._launch(version, environment, scene)
        if error:
            self._say(error, "error")
        else:
            self._say(f"Starting Maya {version}" + (f" with {os.path.basename(scene)}" if scene else "") + "…")

    def _open_autosave(self, version: str, environment: str, autosave: str) -> None:
        """Starts Maya with an autosave file as its scene."""
        if not os.path.isfile(autosave):
            self._say(f"That autosave isn’t there any more: {autosave}", "error")
            return
        self._start(version, environment, autosave)

    def _on_reopen_ended(self, pid: int) -> None:
        info = self._ended.get(pid)
        if info is not None:
            session = info["session"]
            self._start(session.version, session.environment, session.scene)

    def _menu_icon(self, name: str, sub_folder: str = "actions", danger: bool = False) -> qt.QtGui.QIcon:
        """A one-color icon for a menu item, in the theme's color (an empty icon if the file is missing)."""
        return tinted_menu_icon(UiResources().iconManager.get_icon(name, sub_folder=sub_folder),
                                self._menu_danger_color if danger else self._menu_icon_color,
                                self.devicePixelRatioF(), self.MENU_ICON_SIZE)

    def _on_row_menu(self, session_id: int) -> None:
        """Everything that can be asked of one running Maya, as a menu under the
        row's button. While that Maya works on a request, or doesn't answer at
        all, the requests are greyed out — and one that doesn't answer gets
        "Force close…"."""
        row, session = self._rows.get(session_id), self._server.session(session_id)
        if row is None or session is None:
            return
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.setToolTipsVisible(True)
        reachable = not row.pending and not session.busy

        def add(text: str, icon: tuple, tooltip: str, handler, danger: bool = False, enabled: bool = True) -> None:
            action = menu.addAction(self._menu_icon(*icon, danger=danger), text)
            action.setToolTip(tooltip)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False: handler())

        add("Launch report", ("report", "actions"), "How this Maya was started: environment, preferences, "
            "variables, userSetup files, plug-ins", lambda: self._on_report(session_id), enabled=reachable)
        add("Reload code", ("code", "actions"), "Re-read msl_tools from disk in this Maya and rebuild the MSL menu"
            + chr(10) + "(open windows keep their old code until reopened)", lambda: self._on_reload(session_id),
            enabled=reachable)
        if session.skipped:
            add("Load plug-ins…", ("plugin", "plugins"), "Load plug-ins that boost start left out — in this "
                "running Maya, no restart", lambda: self._on_plugins(session_id), enabled=reachable)
        menu.addSeparator()
        if self._launch is not None:
            add("Restart Maya…", ("restart", "actions"), "Close this Maya and start it again: same version, "
                "environment and scene (asks first)", lambda: self._close_maya(session_id, restart=True),
                enabled=reachable)
        add("Close Maya…", ("power", "actions"), "Close this Maya (asks first)",
            lambda: self._close_maya(session_id, restart=False), danger=not session.busy, enabled=reachable)
        if session.busy:
            menu.addSeparator()
            add("Force close…", ("stop", "actions"), "This Maya isn’t answering. End its process at once — "
                "what wasn’t saved is lost (asks first)", lambda: self._force_close(session_id), danger=True)
        self._row_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(row.menu_button.mapToGlobal(qt.QtCore.QPoint(0, row.menu_button.height())))

    def _force_close(self, session_id: int) -> None:
        """Ends the process of a Maya that doesn't answer — after asking."""
        session = self._server.session(session_id)
        if session is None:
            return
        name = self._names.get(session.pid, f"Maya {session.version}")
        silent = ("for " + _duration(time.time() - session.busy_since)) if session.busy_since else "right now"
        details = [session.scene or "untitled scene"]
        if session.modified:
            details.append("It has unsaved changes." + (
                " Maya’s autosave is on: if it wrote one, “Open autosave” will offer it afterwards."
                if session.autosave else " Maya’s autosave is off — they can’t be brought back."))
        choice = ConfirmDialog.ask(
            self, f"Force close {name}",
            f"It hasn’t answered {silent}. It may only be busy — a long playblast, a cache, a heavy scene — "
            f"and come back by itself. Force closing ends it at once: what wasn’t saved is lost.",
            details=chr(10).join(details), choices=[("force", "Force close"), ("cancel", "Wait")], kind="danger")
        if choice != "force":
            return
        self._forced.add(session.pid)
        if not terminate_process(session.pid):
            self._forced.discard(session.pid)
            self._say(f"{name} couldn’t be closed — Windows refused.", "error")

    def _close_maya(self, session_id: int, restart: bool) -> None:
        """Closes (or restarts) a Maya after asking: unsaved changes are saved,
        dropped, or keep Maya open — never lost silently."""
        session = self._server.session(session_id)
        if session is None:
            return
        verb = "Restart" if restart else "Close"
        name = self._names.get(session.pid, f"Maya {session.version}")
        save = False
        if session.modified:
            choices = [("save", f"Save and {verb.lower()}")] if session.scene else []
            choices += [("discard", f"{verb} without saving"), ("cancel", "Cancel")]
            choice = ConfirmDialog.ask(
                self, f"{verb} {name}", f"{session.scene_name} has unsaved changes.",
                details=session.scene or "The scene has no file yet, so it can’t be saved from here.",
                choices=choices, kind="warning" if session.scene else "danger")
            if choice not in ("save", "discard"):
                return
            save = choice == "save"
        else:
            choice = ConfirmDialog.ask(
                self, f"{verb} {name}", f"{verb} this Maya? Its scene has no unsaved changes.",
                details=session.scene or None, choices=[("yes", verb), ("cancel", "Cancel")], kind="question")
            if choice != "yes":
                return
        scene = session.scene

        def done(session: MayaSession, _data: dict) -> None:
            self._say(f"{name} is closing" + (" and will start again." if restart else "."))
            if restart:
                self._restarts[session.pid] = (time.time(), session.version, session.environment, scene)

        self._ask(session_id, protocol.QUIT, done, self.QUIT_TIMEOUT_MS, save=save,
                  discard=session.modified and not save)

    def _start_when_gone(self, pid: int, version: str, environment: str, scene: str, deadline: float) -> None:
        """Starts the new Maya of a restart once the old one's process is gone —
        it said goodbye, but is still writing its preferences on the way out."""
        if is_process_running(pid):
            if time.time() < deadline:
                qt.QtCore.QTimer.singleShot(
                    500, lambda: self._start_when_gone(pid, version, environment, scene, deadline))
            else:
                self._say(f"Maya {version} is still closing — start it again yourself once it is gone.", "error")
            return
        self._start(version, environment, scene)

    def _select_pid(self, pid: int) -> None:
        """Shows the log of the Maya with process id `pid` (an ended one)."""
        if pid == self._selected_pid and self._history_selected is None:
            return
        self._history_selected = None
        self._selected_pid = pid
        self._show_log()
        self.refresh()

    def _on_show_log_file(self, pid: int) -> None:
        info = self._ended.get(pid)
        if info is not None and info["file"] is not None:
            ProcessLauncher.open_file_explorer(info["file"])

    def _on_dismiss_ended(self, pid: int) -> None:
        self._ended.pop(pid, None)
        self._logs.pop(pid, None)
        self._problems.pop(pid, None)
        if self._selected_pid == pid:
            self._selected_pid = 0
            self._log_view.clear_entries()
        self.refresh()

    def _add_to_log(self, pid: int, level: str, text: str) -> None:
        """A line of ours in Maya `pid`'s log (console input / output) — not counted as a problem."""
        now = time.time()
        self._logs.setdefault(pid, []).append((level, text, now))
        if pid == self._selected_pid:
            self._log_view.append_entry(level, text, now)

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
        if session is None or not session.console or not code.strip() or not self._run_button.isEnabled():
            return False
        pid = session.pid
        self._add_to_log(pid, protocol.LOG_INPUT, code)
        self._run_button.setEnabled(False)

        def done(reply: dict) -> None:
            self._run_button.setEnabled(True)
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
        if not self._run_code(self._snippets.code(name)) and not self._run_button.isEnabled():
            self._say("Maya is still running the previous code.")

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

    def _on_level_changed(self, option: str) -> None:
        """Problems / All — for every connected Maya (and those that join later)."""
        self._log_all = option == self.LOG_ALL
        for session in self._server.sessions():
            self._server.request(session.session_id, protocol.SET_LOG_LEVEL, **{"all": self._log_all})

    def _on_wrap_toggled(self, wrap: bool) -> None:
        self._log_view.set_wrap(wrap)
        if self._settings is not None:
            self._settings["log_wrap"] = wrap

    def _on_clear_log(self) -> None:
        self._logs.pop(self._selected_pid, None)
        self._problems.pop(self._selected_pid, None)
        self._log_view.clear_entries()
        self.refresh()

    # --- requests to a running Maya ------------------------------------------------

    def _say(self, text: str, state: str = "") -> None:
        """The outcome of the last request, under the list ("" / "success" / "error")."""
        self._message_label.setText(text)
        if self._message_label.property("state") != state:
            self._message_label.setProperty("state", state)  # maya_gate.qss: QLabel#sessionsMessage[state]
            repolish(self._message_label)
        self._message_label.show()
        self._message_timer.start()

    def _ask(self, session_id: int, name: str, on_done, timeout_ms: int, **data) -> None:
        """Sends request `name`; the row is busy until `on_done(session, reply)`
        ran. A failed reply is reported here and `on_done` isn't called."""
        session = self._server.session(session_id)
        if session is None:
            return
        row = self._rows.get(session_id)
        if row is not None:
            row.set_busy(True)

        def finished(reply: dict) -> None:
            current = self._rows.get(session_id)
            if current is not None:
                current.set_busy(False)
            if reply.get("success"):
                on_done(session, reply.get("data") or {})
            else:
                self._say(f"Maya {session.version}: {reply.get('error') or 'the request failed'}", "error")

        self._server.request(session_id, name, on_reply=finished, timeout_ms=timeout_ms, **data)

    def _on_report(self, session_id: int) -> None:
        self._ask(session_id, protocol.LAUNCH_REPORT,
                  lambda session, data: TextDialog.show_for(
                      self, f"Launch report \u00b7 Maya {session.version} \u00b7 {session.environment or 'no environment'}",
                      str(data.get("text", "")).strip("\n")),
                  self.REPORT_TIMEOUT_MS)

    def _on_reload(self, session_id: int) -> None:
        def done(session: MayaSession, data: dict) -> None:
            menu = ", MSL menu rebuilt" if data.get("menu") else ""
            self._say(f"Maya {session.version}: msl_tools reloaded \u2014 {data.get('modules', 0)} modules will be "
                      f"re-read from disk{menu}.", "success")

        self._ask(session_id, protocol.RELOAD_CODE, done, self.RELOAD_TIMEOUT_MS)

    def _on_plugins(self, session_id: int) -> None:
        """Asks which of the skipped plug-ins are loaded by now, then offers the rest."""
        self._ask(session_id, protocol.PLUGIN_STATE,
                  lambda session, data: self._show_plugins_menu(session, set(data.get("loaded") or [])),
                  self.REPORT_TIMEOUT_MS, names=list(self._server.session(session_id).skipped))

    def _show_plugins_menu(self, session: MayaSession, loaded: set) -> None:
        row = self._rows.get(session.session_id)
        if row is None:
            return
        waiting = [name for name in session.skipped if name not in loaded]
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if len(waiting) > 1:
            menu.addAction(f"Load all {len(waiting)}").triggered.connect(
                lambda: self._load_plugins(session.session_id, waiting))
            menu.addSeparator()
        for name in session.skipped:
            if name in loaded:
                action = menu.addAction(f"{name}  \u2014 loaded")
                action.setEnabled(False)
            else:
                menu.addAction(name).triggered.connect(
                    lambda _checked=False, name=name: self._load_plugins(session.session_id, [name]))
        self._plugins_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(row.menu_button.mapToGlobal(qt.QtCore.QPoint(0, row.menu_button.height())))

    def _load_plugins(self, session_id: int, names: list) -> None:
        def done(session: MayaSession, data: dict) -> None:
            loaded, failed = data.get("loaded") or [], data.get("failed") or {}
            parts = []
            if loaded:
                parts.append("loaded " + ", ".join(loaded))
            if failed:
                parts.append("failed: " + "; ".join(f"{name} ({why})" for name, why in failed.items()))
            self._say(f"Maya {session.version}: " + (" \u2014 ".join(parts) or "nothing to load") + ".",
                      "error" if failed else "success")

        self._say("Loading " + ", ".join(names) + "\u2026")
        self._ask(session_id, protocol.LOAD_PLUGINS, done, self.PLUGINS_TIMEOUT_MS, names=list(names))
