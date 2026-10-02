# tools/desktop/media/page.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import MediaError
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import FfmpegBar, link_button
from msl_tools.msl.tools.desktop.media.job_queue import JobList, JobQueue
from msl_tools.msl.tools.desktop.media.option_panels import SequencePanel, ShrinkPanel, TrimPanel
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, MediaSource, load_source
from msl_tools.msl.tools.desktop.media.source_card import SourceCard
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.workers.result_worker import ResultWorker

StylesheetBuilder.register_template(Path(__file__).with_name("media.qss"))


class MediaPage(qt.QtWidgets.QWidget):
    """The Media tool: quick work with video and image sequences through
    ffmpeg (core/media), without knowing ffmpeg.

    Top to bottom:
    - FfmpegBar — is ffmpeg there; if not, download it or point at a copy;
    - SourceCard — what is being worked on. Drop a video, a folder of
      frames or one frame of a sequence anywhere on the page (or choose it);
      it is read on a worker thread (load_source);
    - the action: an image sequence can be turned "To video"; a video can
      be made smaller or trimmed (a switch). Each action has its settings
      panel (option_panels.py), remembered between sessions;
    - "Save as" — where the result goes: next to the source by default, a
      name that clashes with nothing; "Command" shows what ffmpeg will be
      asked; the start button puts the job into the queue;
    - the queue (job_queue.py): jobs run one after another, each with its
      progress; a finished one can be shown in its folder.

    Nothing is copied: sources stay where they are, results go next to
    them. Settings: Resources().configsDesktopHubMng "media".
    """

    TOOL_NAME = "media"
    DEFAULTS = {"settings": {"ffmpeg_path": ""}, "panels": {}}
    MESSAGE_MS = 9000

    def __init__(self, parent=None):
        super().__init__(parent)
        resources = Resources()
        self._config = resources.configsDesktopHubMng.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._source: MediaSource | None = None
        self._load_token = 0           # only the newest load's answer counts
        self._workers: list = []
        self._output_edited = False    # the user typed their own name: don't replace it
        self._located = False
        self.setAcceptDrops(True)

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._show_source(None)

    # --- construction -----------------------------------------------------------------

    def _build_widgets(self) -> None:
        self._title_label = qt.QtWidgets.QLabel("Media")
        self._title_label.setObjectName("mediaTitle")
        self._subtitle_label = qt.QtWidgets.QLabel("· video and image sequences")
        self._subtitle_label.setObjectName("mediaSubtitle")
        self._ffmpeg = FfmpegBar(self._config["settings"])
        self._card = SourceCard()

        self._panels = {panel.KEY: panel for panel in (SequencePanel(), ShrinkPanel(), TrimPanel())}
        saved = self._config["panels"]
        for key, panel in self._panels.items():
            try:
                panel.apply_settings(dict(saved[key]))
            except (KeyError, TypeError):
                pass
        self._video_actions = SegmentedControl([self._panels["shrink"].TITLE, self._panels["trim"].TITLE],
                                               self._panels["shrink"].TITLE)
        self._action_label = qt.QtWidgets.QLabel()
        self._action_label.setObjectName("mediaAction")
        # Only the picked action's panel is shown; the holder is as tall as that one
        # panel (a stacked widget would be as tall as the tallest of them).
        self._stack = qt.QtWidgets.QWidget()
        stack_layout = qt.QtWidgets.QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        for panel in self._panels.values():
            stack_layout.addWidget(panel)
            panel.hide()

        self._output_caption = qt.QtWidgets.QLabel("Save as")
        self._output_caption.setObjectName("mediaCaption")
        self._output = qt.QtWidgets.QLineEdit()
        self._output.setToolTip("Where the result is written. A name that is free is suggested; change it if you like.")
        self._output_button = IconPushButton(UiResources().iconManager.get_icon("browse", sub_folder="actions"),
                                             "Choose where to save the result", fallback_text="…")
        self._output_button.setFixedSize(26, 22)
        self._command_button = link_button("Command", "What ffmpeg will be asked to do — to read, or to copy")
        self._start_button = qt.QtWidgets.QPushButton("Create video")
        self._start_button.setProperty("primary", True)
        self._start_button.setMinimumWidth(120)

        self._message_label = qt.QtWidgets.QLabel()
        self._message_label.setObjectName("mediaMessage")
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        self._message_timer = qt.QtCore.QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.setInterval(self.MESSAGE_MS)
        self._message_timer.timeout.connect(self._message_label.hide)

        self._jobs_title = qt.QtWidgets.QLabel("Jobs")
        self._jobs_title.setObjectName("mediaTitle")
        self._clear_button = link_button("Clear finished", "Take the jobs that are over off the list (their files stay)")
        self._queue = JobQueue(self._ffmpeg.tools, self)
        self._job_list = JobList(self._queue)

    def _build_layout(self) -> None:
        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_label)
        header.addWidget(self._subtitle_label, 1)
        header.addWidget(self._ffmpeg.status_button())

        actions = qt.QtWidgets.QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(self._action_label)
        actions.addWidget(self._video_actions)
        actions.addStretch(1)

        output = qt.QtWidgets.QHBoxLayout()
        output.setContentsMargins(0, 0, 0, 0)
        output.setSpacing(8)
        output.addWidget(self._output_caption)
        output.addWidget(self._output, 1)
        output.addWidget(self._output_button)
        output.addWidget(self._command_button)
        output.addWidget(self._start_button)

        jobs = qt.QtWidgets.QHBoxLayout()
        jobs.setContentsMargins(0, 4, 0, 0)
        jobs.addWidget(self._jobs_title, 1)
        jobs.addWidget(self._clear_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 8)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._ffmpeg)
        layout.addWidget(self._card)
        layout.addLayout(actions)
        layout.addWidget(self._stack)
        layout.addLayout(output)
        layout.addWidget(self._message_label)
        layout.addLayout(jobs)
        layout.addWidget(self._job_list, 1)

    def _build_connections(self) -> None:
        self._ffmpeg.tools_changed.connect(self._on_tools_changed)
        self._card.open_requested.connect(self.open)
        self._card.cleared.connect(lambda: self._show_source(None))
        self._card.sequence_picked.connect(self._on_sequence_picked)
        self._video_actions.current_changed.connect(lambda _title: self._on_action_changed())
        for panel in self._panels.values():
            panel.changed.connect(self._on_panel_changed)
        self._output.textEdited.connect(lambda _text: setattr(self, "_output_edited", True))
        self._output_button.clicked.connect(self._on_browse_output)
        self._command_button.clicked.connect(self._on_show_command)
        self._start_button.clicked.connect(self._on_start)
        self._clear_button.clicked.connect(self._queue.clear_finished)
        self._job_list.show_requested.connect(self._on_show_result)
        self._job_list.command_requested.connect(
            lambda item: TextDialog.show_for(self, "Command  ·  " + item.job.output.name, item.command))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._located:  # ffmpeg is first looked for when the tool is opened, not when it is built
            self._located = True
            self._ffmpeg.locate()

    # --- ffmpeg ------------------------------------------------------------------------

    def _on_tools_changed(self, tools) -> None:
        self._card.set_enabled_for_input(tools is not None, "Media needs ffmpeg first — see the line above.")
        self._refresh_controls()

    # --- the source ----------------------------------------------------------------------

    def open(self, path: str, chosen=None) -> None:
        """Reads the file or folder at `path` and shows it as the source."""
        tools = self._ffmpeg.tools()
        if tools is None:
            self._say("Media needs ffmpeg first — see the line at the top.", "error")
            return
        self._load_token += 1
        token = self._load_token
        self._card.set_loading(Path(path).name or str(path))

        def done(source) -> None:
            if token == self._load_token:
                self._show_source(source)

        def failed(error) -> None:
            if token == self._load_token:
                self._card.set_source(self._source)
                self._say(str(error) if isinstance(error, MediaError) else f"Couldn’t read it: {error}", "error")

        worker = ResultWorker(lambda: load_source(tools, path, chosen), parent=self)
        self._workers.append(worker)
        worker.done.connect(done)
        worker.failed.connect(failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_sequence_picked(self, sequence) -> None:
        if self._source is not None and sequence is not self._source.sequence:
            self.open(str(sequence.folder), sequence)

    def _show_source(self, source: MediaSource | None) -> None:
        self._source = source
        self._card.set_source(source)
        self._output_edited = False
        if source is not None:
            for panel in self._actions():
                panel.set_source(source)
            self._message_label.hide()
        self._on_action_changed()

    def _actions(self) -> list:
        """The panels that fit the source."""
        if self._source is None:
            return []
        if self._source.is_sequence:
            return [self._panels["sequence"]]
        return [self._panels["shrink"], self._panels["trim"]]

    def _panel(self):
        """The panel of the action that is picked (None without a source)."""
        actions = self._actions()
        if not actions:
            return None
        if len(actions) == 1:
            return actions[0]
        return next(panel for panel in actions if panel.TITLE == self._video_actions.current())

    def _on_action_changed(self) -> None:
        panel = self._panel()
        several = len(self._actions()) > 1
        self._video_actions.setVisible(several)
        self._action_label.setVisible(panel is not None and not several)
        if panel is not None:
            self._action_label.setText(panel.TITLE)
            for other in self._panels.values():
                other.setVisible(other is panel)
            self._start_button.setText(panel.BUTTON)
        self._stack.setVisible(panel is not None)
        self._suggest_output()
        self._refresh_controls()

    def _on_panel_changed(self) -> None:
        self._suggest_output()
        self._save_settings()

    def _refresh_controls(self) -> None:
        ready = self._source is not None and self._ffmpeg.tools() is not None
        for widget in (self._output_caption, self._output, self._output_button, self._command_button,
                       self._start_button):
            widget.setVisible(self._source is not None)
        self._start_button.setEnabled(ready)

    # --- the result's name ---------------------------------------------------------------

    def _suggest_output(self) -> None:
        """Puts a free name into "Save as" — unless the user typed their own."""
        panel = self._panel()
        if panel is None or self._output_edited:
            return
        self._output.setText(str(panel.output_for(self._source, taken=self._queue.outputs())))

    def _on_browse_output(self) -> None:
        path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Save the result as", self._output.text(),
                                                                 "Video (*.mp4 *.mov *.mkv);;All files (*.*)")
        if path:
            self._output.setText(path)
            self._output_edited = True

    # --- starting ------------------------------------------------------------------------

    def _job(self):
        """The Job for what is on screen; None (and a message) if it can't be made."""
        panel = self._panel()
        if panel is None:
            return None
        text = self._output.text().strip()
        if not text:
            self._say("Say where to save the result.", "error")
            return None
        output = Path(text)
        if not output.suffix:
            output = output.with_suffix(".mp4")
        source_file = None if self._source.is_sequence else self._source.path
        if source_file is not None and output.resolve() == source_file.resolve():
            self._say("The result can’t replace the file it is made from — pick another name.", "error")
            return None
        try:
            return panel.job(self._source, output)
        except MediaError as error:
            self._say(str(error), "error")
            return None

    def _on_start(self) -> None:
        job = self._job()
        if job is None:
            return
        if job.output in self._queue.outputs():
            self._say(f"A job is already writing {job.output.name} — pick another name.", "error")
            return
        if job.output.exists():
            choice = ConfirmDialog.ask(self, "Replace the file?", f"{job.output.name} is already there.",
                                       details=str(job.output), kind="warning",
                                       choices=[("replace", "Replace it"), ("cancel", "Cancel")])
            if choice != "replace":
                return
        self._queue.add(job)
        self._message_label.hide()
        self._output_edited = False
        self._suggest_output()  # the next job gets the next free name

    def _on_show_command(self) -> None:
        job = self._job()
        if job is not None:
            TextDialog.show_for(self, "Command  ·  " + job.output.name, job.command_text(self._ffmpeg.tools()))
            for path in job.temporary:  # a job that is only looked at leaves nothing behind
                try:
                    Path(path).unlink()
                except OSError:
                    pass

    def _on_show_result(self, item) -> None:
        if not ProcessLauncher.open_file_explorer(item.job.output):
            self._say(f"That file isn’t there any more: {item.job.output}", "error")

    # --- drops ---------------------------------------------------------------------------

    @staticmethod
    def _dropped_path(event) -> str:
        data = event.mimeData()
        for url in (data.urls() if data.hasUrls() else []):
            if url.isLocalFile():
                return url.toLocalFile()
        return ""

    def dragEnterEvent(self, event) -> None:
        if self._dropped_path(event):
            self._card.set_dragging(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._card.set_dragging(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._card.set_dragging(False)
        path = self._dropped_path(event)
        if not path:
            event.ignore()
            return
        event.acceptProposedAction()
        # Sound dropped while a sequence is open goes under that sequence.
        if Path(path).suffix.lower() in AUDIO_SUFFIXES and self._source is not None and self._source.is_sequence:
            self._panels["sequence"].set_sound(path)
            self._say(f"{Path(path).name} will be the sound of the video.")
            return
        self.open(path)

    # --- small things ---------------------------------------------------------------------

    def _say(self, text: str, state: str = "") -> None:
        """A line under the settings ("" / "error")."""
        self._message_label.setText(text)
        if self._message_label.property("state") != state:
            self._message_label.setProperty("state", state)  # media.qss: QLabel#mediaMessage[state]
            repolish(self._message_label)
        self._message_label.show()
        self._message_timer.start()

    def _save_settings(self) -> None:
        self._config["panels"] = {key: panel.settings() for key, panel in self._panels.items()}


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MediaPage()
        page.resize(760, 620)
        page.show()
