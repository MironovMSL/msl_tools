# tools/desktop/media/page_queue.py
"""The Media page's queue controls, render-farm style: pause / go on, and what happens when the
last job is over — a sound, or the computer shuts down (with time to call it off)."""
import time

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment import system_actions
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.job_queue import DONE, FAILED
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources


class _QueueMixin:
    """MediaPage's pause button, its "when the jobs are done" menu and the shutdown notice
    (methods of MediaPage; `_build_queue_controls()` makes the widgets, the page lays them out).

    "Play a sound" is remembered (`settings.when_done`). "Shut down" is NOT: it is armed for the
    jobs in the queue now and disarms itself once it fired — a forgotten setting must never turn
    a computer off days later. It asks Windows for a shutdown in SHUTDOWN_GRACE_S; the page then
    shows a bar with the countdown and "Cancel the shutdown".
    """

    WHEN_DONE = {"": "Nothing", "sound": "Play a sound", "shutdown": "Shut the computer down"}
    SHUTDOWN_GRACE_S = system_actions.SHUTDOWN_GRACE_S

    def _build_queue_controls(self) -> None:
        self._shutdown_armed = False
        self._shutdown_at = 0.0
        self._pause_button = self._action_button("pause", "❚❚", "Pause the jobs — the running one is frozen where "
                                                                "it is, nothing else starts until you go on")
        self._when_done_button = self._action_button("bell", "◔", "")
        self._when_done_note = qt.QtWidgets.QLabel()
        self._when_done_note.setObjectName("mediaWhenDone")
        self._shutdown_bar = qt.QtWidgets.QFrame()
        self._shutdown_bar.setObjectName("mediaShutdown")
        self._shutdown_text = qt.QtWidgets.QLabel()
        self._shutdown_text.setObjectName("mediaShutdownText")
        self._shutdown_text.setWordWrap(True)
        self._shutdown_cancel = link_button("Cancel the shutdown", "The computer stays on")
        bar = qt.QtWidgets.QHBoxLayout(self._shutdown_bar)
        bar.setContentsMargins(12, 6, 10, 6)
        bar.setSpacing(8)
        bar.addWidget(self._shutdown_text, 1)
        bar.addWidget(self._shutdown_cancel)
        self._shutdown_bar.hide()
        self._shutdown_timer = qt.QtCore.QTimer(self)
        self._shutdown_timer.setInterval(1000)
        self._shutdown_timer.timeout.connect(self._tick_shutdown)
        self._pause_button.clicked.connect(self._on_pause_clicked)
        self._when_done_button.clicked.connect(self._on_when_done_menu)
        self._shutdown_cancel.clicked.connect(self._on_cancel_shutdown)
        self._queue.paused_changed.connect(lambda _paused: self._refresh_queue_controls())
        for signal in (self._queue.added, self._queue.idle):
            signal.connect(lambda *_arguments: self._refresh_queue_controls())
        self._refresh_queue_controls()

    def _when_done(self) -> str:
        if self._shutdown_armed:
            return "shutdown"
        value = str(self._settings.get("when_done", "") or "")
        return value if value in self.WHEN_DONE and value != "shutdown" else ""

    def _refresh_queue_controls(self) -> None:
        busy, paused = self._queue.busy(), self._queue.is_paused()
        self._pause_button.setVisible(busy or paused)
        icons = UiResources().iconManager
        self._pause_button.set_icon(icons.get_icon("play" if paused else "pause", sub_folder="actions"))
        self._pause_button.setToolTip("Go on with the jobs" if paused else
                                      "Pause the jobs — the running one is frozen where it is, nothing else "
                                      "starts until you go on")
        when = self._when_done()
        notes = {"": "", "sound": "then a sound", "shutdown": "then shut down"}
        self._when_done_note.setText("  ·  ".join(part for part in ("paused" if paused else "", notes[when]) if part))
        self._when_done_note.setVisible(bool(self._when_done_note.text()))
        if self._when_done_note.property("state") != when:
            self._when_done_note.setProperty("state", when)   # media.qss: QLabel#mediaWhenDone[state="shutdown"]
            repolish(self._when_done_note)
        self._when_done_button.setToolTip(f"When the jobs are done: {self.WHEN_DONE[when].lower()}" + chr(10)
                                          + "Click to change")

    def _on_pause_clicked(self) -> None:
        if self._queue.is_paused():
            self._queue.resume()
            self._say("The jobs go on.")
        else:
            self._queue.pause()
            self._say("Paused. Nothing new starts until you go on" + (
                " — the running job is frozen where it is." if self._queue.busy() else "."))

    def _on_when_done_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.setToolTipsVisible(True)
        current = self._when_done()
        for key, title in self.WHEN_DONE.items():
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(lambda _checked=False, key=key: self._set_when_done(key))
            if key == "shutdown":
                action.setToolTip(f"Once — for the jobs in the queue now. Windows gets "
                                  f"{self.SHUTDOWN_GRACE_S // 60} minutes' notice, which you can call off.")
        self._when_done_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(self._when_done_button.mapToGlobal(qt.QtCore.QPoint(0, self._when_done_button.height())))

    def _set_when_done(self, key: str) -> None:
        self._shutdown_armed = key == "shutdown"
        if key != "shutdown":
            self._settings["when_done"] = key
        self._refresh_queue_controls()
        if key == "shutdown":
            self._say("The computer shuts down when the last job is over"
                      + ("." if self._queue.busy() else " — start the jobs."))

    def _after_batch(self, batch: list) -> None:
        """The queue went idle: what was asked for "when the jobs are done"."""
        ran = [item for item in batch if item.state in (DONE, FAILED)]
        if not ran:
            return  # everything was cancelled: nobody waited for this
        when = self._when_done()
        if when == "sound":
            system_actions.chime()
        elif when == "shutdown":
            self._shutdown_armed = False  # once
            failed = sum(1 for item in ran if item.state == FAILED)
            if self._schedule_shutdown():
                self._shutdown_at = time.monotonic() + self.SHUTDOWN_GRACE_S
                self._shutdown_bar.show()
                self._tick_shutdown()
                self._shutdown_timer.start()
                if failed:
                    self._shutdown_text.setToolTip(f"{failed} job{'s' if failed != 1 else ''} failed — "
                                                   "see the list before it goes off")
            else:
                self._say("Windows didn’t take the shutdown — the computer stays on.", "error")
            self._refresh_queue_controls()

    def _schedule_shutdown(self) -> bool:
        return system_actions.schedule_shutdown(self.SHUTDOWN_GRACE_S, "MSL Tools: the Media jobs are done.")

    def _tick_shutdown(self) -> None:
        left = max(int(round(self._shutdown_at - time.monotonic())), 0)
        self._shutdown_text.setText(f"The jobs are done — the computer shuts down in {left // 60}:{left % 60:02d}.")
        if left <= 0:
            self._shutdown_timer.stop()

    def _on_cancel_shutdown(self) -> None:
        self._shutdown_timer.stop()
        self._shutdown_bar.hide()
        if system_actions.cancel_shutdown():
            self._say("Shutdown called off.")
        else:
            self._say("Windows had no shutdown to call off.", "error")
