# tools/desktop/media/page_jobs.py
"""The Media page's jobs: start, preview, estimate, what the queue reports."""
import os
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment.taskbar import TaskbarProgress
from msl_tools.msl.core.media import Estimate, MediaError, estimate, preview
from msl_tools.msl.core.media.run import clean_up
from msl_tools.msl.tools.desktop.media.job_queue import DONE, FAILED
from msl_tools.msl.ui.desktop_notice import DesktopNotice
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog


class _JobsMixin:
    """MediaPage's jobs: starting them, the preview, the estimate, what the queue reports, the
    jobs card (methods of MediaPage, moved as they were)."""

    # --- the jobs ----------------------------------------------------------------------------

    def _jobs(self, quiet: bool = False):
        """The Jobs for what is on screen — one, or one per source; None (and
        a message, unless `quiet`) if they can't be made."""
        panel = self._panel()
        if panel is None:
            return None
        try:
            if self._one_result():
                output = self._output_path()
                if output is None:
                    raise MediaError("Say where to save the result.")
                if panel.INTO_FOLDER:
                    if output.is_file():
                        raise MediaError(f"{output.name} is a file — the frames need a folder.")
                elif not output.suffix:
                    output = output.with_suffix(panel.suffix(self._sources[0]))
                if any(not source.is_sequence and output.resolve() == source.path.resolve() for source in self._sources):
                    raise MediaError("The result can’t replace the file it is made from — pick another name.")
                if panel.COMBINES:
                    return [panel.combined_job(self._sources, output)]
                return panel.jobs(self._sources[0], output)
            jobs, taken = [], list(self._queue.outputs())
            for source in self._sources:
                output = panel.output_for(source, self._folder() or None, taken, self._name_template())
                made = panel.jobs(source, output)
                taken += [job.output for job in made]
                jobs += made
            return jobs
        except MediaError as error:
            if not quiet:
                self._say(str(error), "error")
            return None

    def _on_start(self) -> None:
        jobs = self._jobs()
        if not jobs:
            return
        for job in jobs:
            if job.output in self._queue.outputs():
                self._say(f"A job is already writing {job.output.name} — pick another name.", "error")
                self._discard(jobs)
                return
        existing = [job.output for job in jobs if job.output.exists()]
        if existing:
            folder = existing[0].is_dir()
            choice = ConfirmDialog.ask(
                self, "Write into that folder?" if folder else "Replace the file?",
                f"{existing[0].name} is already there." + (" Pictures with the same names in it are replaced; "
                                                           "everything else stays." if folder else ""),
                details=str(existing[0]), kind="warning",
                choices=[("replace", "Write into it" if folder else "Replace it"), ("cancel", "Cancel")])
            if choice != "replace":
                self._discard(jobs)
                return
        panel = self._panel()
        # compared with its source only where jobs and sources pair up one to one
        compared = panel.COMPARES_SIZE and not panel.COMBINES and len(jobs) == len(self._sources)
        for index, job in enumerate(jobs):
            self._queue.add(job, self._source_size(self._sources[index]) if compared else 0,
                            recipe=self._recipe(panel, index, len(jobs)))
        self._message_label.hide()
        self._output_edited = False
        self._suggest_output()  # the next job gets the next free name

    def _source_size(self, source) -> int:
        """Bytes of a source: the video file, or all the frames of a sequence (0 if it can't be told quickly)."""
        if not source.is_sequence:
            return int(source.info.size or 0)
        frames = source.sequence.frames
        if len(frames) > self.SEQUENCE_SIZE_FRAMES:
            return 0
        try:
            return sum(os.path.getsize(source.sequence.file(frame)) for frame in frames)
        except OSError:
            return 0

    @staticmethod
    def _discard(jobs: list) -> None:
        """Jobs that were built but won't run leave nothing behind."""
        for job in jobs:
            clean_up(job, remove_output=False)

    def _on_show_command(self) -> None:
        jobs = self._jobs()
        if jobs:
            text = (chr(10) * 2).join(job.command_text(self._ffmpeg.tools()) for job in jobs)
            title = jobs[0].output.name if len(jobs) == 1 else f"{len(jobs)} jobs"
            self._discard(jobs)
            TextDialog.show_for(self, "Command  ·  " + title, text)

    # --- preview ---------------------------------------------------------------------------------

    def _preview_dir(self) -> Path:
        return Path(tempfile.gettempdir()) / "msl_tools" / "media" / "preview"

    def _on_preview(self) -> None:
        """Makes a few seconds of the result with the settings on screen (on a
        worker thread) and opens them in the player. With several sources it
        is the first one's."""
        panel, tools = self._panel(), self._ffmpeg.tools()
        jobs = self._jobs() if panel is not None and tools is not None else None
        if not jobs:
            return
        job = jobs[0]
        self._discard(jobs[1:])
        if panel.PREVIEW_FROM_START:
            job.sample = []  # no piece from the middle: the result's own beginning
        seconds = float(panel.PREVIEW_SECONDS)
        self._preview_token += 1
        self._preview_count += 1
        token = self._preview_token
        folder = self._preview_dir()
        for old in folder.glob(f"preview_{os.getpid()}_*") if folder.is_dir() else []:
            try:
                old.unlink()  # the previous preview (a player that still holds it keeps it; it is cleared later)
            except OSError:
                pass
        suffix = job.output.suffix or panel.suffix(self._sources[0]) or ".mp4"
        target = folder / f"preview_{os.getpid()}_{self._preview_count}{suffix}"
        self._preview_button.setEnabled(False)  # dimmed while the preview is being made
        self._preview_button.setToolTip("Making the preview…")
        self._say("Making the preview…")

        def work():
            try:
                return preview(tools, job, target, seconds)
            finally:
                clean_up(job, remove_output=False)

        def restore() -> bool:
            if token != self._preview_token:
                return False  # the settings changed meanwhile: the buttons were refreshed already
            self._refresh_buttons()  # enabled again, its tooltip back
            self._message_label.hide()
            return True

        def done(path) -> None:
            if restore() and not self._open_file(path):
                self._say(f"Couldn’t open the preview: {path}", "error")

        def failed(error) -> None:
            if restore():
                self._say(str(error) if isinstance(error, MediaError) else f"The preview failed: {error}", "error")

        self._run(work, done, failed)

    # --- what the queue reports -------------------------------------------------------------------

    def _notifies(self) -> bool:
        return bool(self._settings.get("notify", True))

    def _save_history(self) -> None:
        if not self._history_loaded:  # never before the old list was read: it would be overwritten
            return
        records = self._queue.results()
        if records == self._history_saved:
            return  # a finished row only got its picture (50 of them on a start): nothing new to keep
        self._history.save(records)
        self._history_saved = records

    def _on_queue_changed(self, item) -> None:
        if item.state == DONE:
            self._save_history()
        if not self._queue.busy():
            return  # a finished row changed (its picture arrived): nothing is running
        if self._taskbar is None:
            # made at the first job: by then the page sits in its window, and the window has its id
            self._taskbar = TaskbarProgress(int(self.window().winId())
                                            if qt.QtGui.QGuiApplication.platformName() == "windows" else 0)
        self._taskbar.set(self._queue.overall())
        self._start_button.set_progress(self._queue.overall())

    # --- the jobs card's header ----------------------------------------------------------------------

    def _refresh_jobs_title(self) -> None:
        """"JOBS · 4", and while jobs run "JOBS · 1 of 3 done"."""
        over, batch = self._queue.batch_counts()
        total = len(self._queue.items())
        self._fit_jobs_card()
        self._jobs_title.setText(f"JOBS  ·  {over} of {batch} done" if batch else f"JOBS  ·  {total}" if total else "JOBS")

    def eventFilter(self, watched, event) -> bool:
        if watched is self._jobs_header and event.type() == qt.QtCore.QEvent.Type.MouseButtonRelease \
                and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._set_jobs_folded(self._job_list.isVisibleTo(self._jobs_card))
            return True
        return super().eventFilter(watched, event)

    def _set_jobs_folded(self, folded: bool, remember: bool = True) -> None:
        """Folds the jobs list away (only its header stays) or brings it back."""
        self._job_list.setVisible(not folded)
        self._jobs_divider.setVisible(not folded)
        self._fit_jobs_card()
        self._jobs_fold.set_icon(UiResources().iconManager.get_icon("chevron_right" if folded else "chevron_down",
                                                                    sub_folder="actions"))
        if remember:
            self._settings["jobs_folded"] = folded

    def _fit_jobs_card(self) -> None:
        """The jobs card takes the room that is left only while it has jobs to show: folded, or
        empty, it is as small as it can be, and a filler takes the room under it."""
        empty = not self._queue.items()
        grows = self._job_list.isVisibleTo(self._jobs_card) and not empty
        self._job_list.setMaximumHeight(self.EMPTY_JOBS_HEIGHT if empty else 16777215)
        self._filler.setVisible(not grows)
        self.layout().setStretchFactor(self._jobs_card, 1 if grows else 0)

    def _on_queue_idle(self) -> None:
        batch = self._queue.last_batch()
        self._after_batch(batch)  # page_queue.py: a sound, or the shutdown
        self._start_button.set_progress(None)
        if self._taskbar is not None:
            self._taskbar.clear()
        done = [item for item in batch if item.state == DONE]
        failed = [item for item in batch if item.state == FAILED]
        window = self.window()
        if not (done or failed) or not self._notifies() or (self.isVisible() and window.isActiveWindow()):
            return
        if len(done) == 1 and not failed:
            text = f"{done[0].job.output.name} is ready."
        elif len(failed) == 1 and not done:
            text = f"{failed[0].job.output.name} failed: {failed[0].message}"
        else:
            text = f"{len(done)} result{'s are' if len(done) != 1 else ' is'} ready" + \
                   (f", {len(failed)} failed." if failed else ".")
        if self._notice is None:
            self._notice = DesktopNotice(UiResources().iconManager.get_icon("hub", sub_folder="brand"), self)
            self._notice.clicked.connect(self._on_notice_clicked)
        self._notice.show("MSL Tools · Media", text)
        qt.QtWidgets.QApplication.alert(window)  # the taskbar button asks for attention too

    def _on_notice_clicked(self) -> None:
        """The notice was clicked: this page, in front."""
        window = self.window()
        open_tool = getattr(window, "open_tool", None)  # the hub; a page shown on its own has none
        if callable(open_tool):
            open_tool(self.TOOL_NAME)
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()

    def _set_estimate(self, pairs: list) -> None:
        """The estimate's tiles ([] = nothing to say)."""
        self._estimate_tiles.set_pairs(pairs)

    def _estimate_pairs(self, guess, count: int, source_size: int) -> list:
        """An Estimate as tiles: the result's size, how it compares with the source, the time."""
        if guess is None:
            return []
        pairs = []
        if guess.size:
            pairs.append((Estimate(size=guess.size).text(), "each result" if count > 1 else "result"))
            if source_size:
                change = max(round((guess.size / source_size - 1) * 100), -99)  # "−100 %" would say nothing is left
                pairs.append((f"{'+' if change > 0 else '−'}{abs(change)} %", "bigger" if change > 0 else "smaller"))
        if guess.seconds:
            pairs.append((Estimate(seconds=guess.seconds).text(), "each, to make" if count > 1 else "to make"))
        return pairs

    def _schedule_estimate(self) -> None:
        """What is on screen changed: the old guess is gone at once, a new one follows shortly."""
        self._estimate_token += 1  # an estimate still on its way is for the old settings
        self._set_estimate(self.ESTIMATING if self._panel() is not None and self._ffmpeg.tools() is not None else [])
        self._estimate_timer.start()

    def _estimate(self) -> None:
        """Guesses the size and time of what "start" would make (on a worker thread)."""
        self._estimate_token += 1
        token = self._estimate_token
        tools = self._ffmpeg.tools()
        jobs = self._jobs(quiet=True) if tools is not None else None
        if not jobs:
            self._set_estimate([])
            return
        job, count = jobs[0], len(jobs)
        self._discard(jobs[1:])
        self._set_estimate(self.ESTIMATING)
        panel = self._panel()
        compared = panel.COMPARES_SIZE and not panel.COMBINES and job.folder is None
        source_size = self._source_size(self._sources[0]) if compared else 0

        def work():
            try:
                return estimate(tools, job)
            finally:
                clean_up(job, remove_output=False)

        def done(guess) -> None:
            if token == self._estimate_token:
                self._set_estimate(self._estimate_pairs(guess, count, source_size))

        self._run(work, done, lambda _error: done(None))

    def _on_show_result(self, item) -> None:
        if not ProcessLauncher.open_file_explorer(item.job.output):
            self._say(f"That file isn’t there any more: {item.job.output}", "error")

    def _on_open_result(self, item) -> None:
        if not item.job.output.exists() or not self._open_file(item.job.output):
            self._say(f"That file isn’t there any more: {item.job.output}", "error")

    @staticmethod
    def _open_file(path: Path) -> bool:
        """Opens a file with the program Windows uses for it (a video: the player)."""
        return bool(qt.QtGui.QDesktopServices.openUrl(qt.QtCore.QUrl.fromLocalFile(str(path))))
