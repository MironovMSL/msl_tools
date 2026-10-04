# tools/desktop/maya_gate/session_rows.py
"""The rows of the Sessions tab: a running Maya, one that ended unexpectedly, one of the
history — and the scene name that is a link to its file."""
import os
import time
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.link.session import MayaSession
from msl_tools.msl.tools.desktop.maya_gate.session_history import SessionRecord
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton


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

    def __init__(self, record: SessionRecord, can_reopen: bool = False, reopened: bool = False, parent=None):
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
        self.outcome_label = qt.QtWidgets.QLabel(record.outcome_text() + ("  ·  reopened, running" if reopened else ""))
        self.outcome_label.setObjectName("sessionOutcome")
        self.outcome_label.setProperty("state", "" if record.clean else "error")
        if reopened:
            can_reopen = False  # the Maya that continues it is running: not a second one by a stray click
            self.outcome_label.setToolTip("This scene was reopened from here and that Maya is running now.")
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
