# tools/desktop/media/page.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import MediaError, estimate
from msl_tools.msl.core.media.run import clean_up
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import FfmpegBar, link_button
from msl_tools.msl.tools.desktop.media.job_queue import JobList, JobQueue
from msl_tools.msl.tools.desktop.media.option_panels import PANELS
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, load_source, load_sources
from msl_tools.msl.tools.desktop.media.source_card import SourceCard
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.workers.result_worker import ResultWorker

StylesheetBuilder.register_template(Path(__file__).with_name("media.qss"))


class MediaPage(qt.QtWidgets.QWidget):
    """The Media tool: quick work with video and image sequences through
    ffmpeg (core/media), without knowing ffmpeg.

    Top to bottom:
    - FfmpegBar — is ffmpeg there; if not, download it or point at a copy;
    - SourceCard — what is being worked on. Drop videos, a folder of frames
      or frames of sequences anywhere on the page (or choose them); they are
      read on a worker thread. SEVERAL can be dropped at once: all videos,
      or all image sequences;
    - the action: a ChipBar of the actions that fit the sources (their
      panels are option_panels.PANELS). Most make one result per source;
      Join and Compare make one result out of all of them;
    - presets: saved settings of the picked action as chips — a click
      applies one; "+ Save preset" keeps the current settings under a name;
    - the action's panel;
    - "Save as" (one result) or a note where the results go (several);
      "Results" picks the folder (next to each source, or one folder for
      all); an estimate of the result's size and time; "Command"; the start
      button, which puts the job(s) into the queue;
    - the queue (job_queue.py): jobs run one after another; a finished one
      is opened with a click, dragged out, copied, shown in its folder.

    Nothing is copied: sources stay where they are. Settings:
    Resources().configsDesktopHubMng "media" — `settings` (ffmpeg_path,
    output_folder, action), `panels` (each panel's choices), `presets`.
    """

    TOOL_NAME = "media"
    DEFAULTS = {"settings": {"ffmpeg_path": "", "output_folder": "", "action": ""}, "panels": {}, "presets": {}}
    MESSAGE_MS = 9000
    ESTIMATE_DELAY_MS = 700

    def __init__(self, parent=None):
        super().__init__(parent)
        resources = Resources()
        self._config = resources.configsDesktopHubMng.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._settings = self._config["settings"]
        self._sources: list = []
        self._load_token = 0           # only the newest load's answer counts
        self._estimate_token = 0
        self._workers: list = []
        self._output_edited = False    # the user typed their own name: don't replace it
        self._located = False
        self._applying = False         # settings are being put into a panel: not a change by the user
        self.setAcceptDrops(True)

        self._build_widgets()
        self._build_layout()
        self._build_connections()
        self._show_sources([])

    # --- construction -----------------------------------------------------------------

    def _build_widgets(self) -> None:
        self._title_label = qt.QtWidgets.QLabel("Media")
        self._title_label.setObjectName("mediaTitle")
        self._subtitle_label = qt.QtWidgets.QLabel("· video and image sequences")
        self._subtitle_label.setObjectName("mediaSubtitle")
        self._ffmpeg = FfmpegBar(self._settings)
        self._card = SourceCard()

        self._panels = {panel.KEY: panel(self._ffmpeg.tools) for panel in PANELS}
        for key, panel in self._panels.items():
            saved = self._node("panels", key)
            if saved:
                panel.apply_settings(saved)
        self._actions = ChipBar(checkable=True)
        self._presets_caption = qt.QtWidgets.QLabel("Presets")
        self._presets_caption.setObjectName("mediaCaption")
        self._presets = ChipBar(add_text="+ Save preset", name_placeholder="Preset name, then Enter")
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
        self._output_note = qt.QtWidgets.QLabel()
        self._output_note.setObjectName("mediaCaption")
        self._output_note.setWordWrap(True)
        self._folder_button = link_button("", "Where results go: next to each source, or one folder for all")
        self._estimate_label = qt.QtWidgets.QLabel()
        self._estimate_label.setObjectName("mediaHint")
        self._estimate_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._estimate_label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._estimate_label.setToolTip("About how big the result will be and how long it will take — "
                                        "guessed from a second of it")
        self._command_button = link_button("Command", "What ffmpeg will be asked to do — to read, or to copy")
        self._start_button = qt.QtWidgets.QPushButton("Create video")
        self._start_button.setProperty("primary", True)
        self._start_button.setMinimumWidth(120)
        self._estimate_timer = qt.QtCore.QTimer(self)
        self._estimate_timer.setSingleShot(True)
        self._estimate_timer.setInterval(self.ESTIMATE_DELAY_MS)
        self._estimate_timer.timeout.connect(self._estimate)

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

        presets = qt.QtWidgets.QHBoxLayout()
        presets.setContentsMargins(0, 0, 0, 0)
        presets.setSpacing(8)
        presets.addWidget(self._presets_caption, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        presets.addWidget(self._presets, 1)

        output = qt.QtWidgets.QHBoxLayout()
        output.setContentsMargins(0, 0, 0, 0)
        output.setSpacing(8)
        output.addWidget(self._output_caption)
        output.addWidget(self._output, 1)
        output.addWidget(self._output_button)
        output.addWidget(self._output_note, 1)

        start = qt.QtWidgets.QHBoxLayout()
        start.setContentsMargins(0, 0, 0, 0)
        start.setSpacing(8)
        start.addWidget(self._folder_button)
        start.addWidget(self._estimate_label, 1)  # takes what is left, and gives way first in a narrow window
        start.addWidget(self._command_button)
        start.addWidget(self._start_button)

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
        layout.addWidget(self._actions)
        layout.addLayout(presets)
        layout.addWidget(self._stack)
        layout.addLayout(output)
        layout.addLayout(start)
        layout.addWidget(self._message_label)
        layout.addLayout(jobs)
        layout.addWidget(self._job_list, 1)

    def _build_connections(self) -> None:
        self._ffmpeg.tools_changed.connect(self._on_tools_changed)
        self._card.open_requested.connect(lambda path: self.open([path]))
        self._card.cleared.connect(lambda: self._show_sources([]))
        self._card.sequence_picked.connect(self._on_sequence_picked)
        self._actions.clicked.connect(self._on_action_picked)
        self._presets.clicked.connect(self._on_preset_clicked)
        self._presets.add_requested.connect(self._on_preset_added)
        self._presets.remove_requested.connect(self._on_preset_removed)
        for panel in self._panels.values():
            panel.changed.connect(self._on_panel_changed)
        self._output.textEdited.connect(lambda _text: setattr(self, "_output_edited", True))
        self._output_button.clicked.connect(self._on_browse_output)
        self._folder_button.clicked.connect(self._on_folder_menu)
        self._command_button.clicked.connect(self._on_show_command)
        self._start_button.clicked.connect(self._on_start)
        self._clear_button.clicked.connect(self._queue.clear_finished)
        self._job_list.show_requested.connect(self._on_show_result)
        self._job_list.open_requested.connect(self._on_open_result)
        self._job_list.command_requested.connect(
            lambda item: TextDialog.show_for(self, "Command  ·  " + item.job.output.name, item.command))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._located:  # ffmpeg is first looked for when the tool is opened, not when it is built
            self._located = True
            self._ffmpeg.locate()

    # --- settings ------------------------------------------------------------------------

    def _node(self, branch: str, key: str) -> dict:
        """A copy of `branch`.`key` of the config as a plain dict ({} if it isn't there)."""
        try:
            node = self._config[branch][key]
        except (KeyError, TypeError):
            return {}
        return node.to_dict() if hasattr(node, "to_dict") else dict(node)

    def _has_node(self, branch: str, key: str) -> bool:
        try:
            return key in self._config[branch]
        except (KeyError, TypeError):
            return False

    def _save_settings(self) -> None:
        self._config["panels"] = {key: panel.settings() for key, panel in self._panels.items()}

    # --- ffmpeg ---------------------------------------------------------------------------

    def _on_tools_changed(self, tools) -> None:
        self._card.set_enabled_for_input(tools is not None, "Media needs ffmpeg first — see the line above.")
        self._refresh_controls()
        self._schedule_estimate()

    # --- the sources -----------------------------------------------------------------------

    def open(self, paths, chosen=None) -> None:
        """Reads the files / folders at `paths` and shows them as what is worked on."""
        paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
        tools = self._ffmpeg.tools()
        if tools is None:
            self._say("Media needs ffmpeg first — see the line at the top.", "error")
            return
        self._load_token += 1
        token = self._load_token
        self._card.set_loading(Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} files")

        def work():
            if chosen is not None:
                return [load_source(tools, paths[0], chosen)], []
            return load_sources(tools, paths)

        def done(result) -> None:
            if token != self._load_token:
                return
            sources, problems = result
            self._show_sources(sources)
            if problems:
                self._say(chr(10).join(problems[:4]), "error")

        def failed(error) -> None:
            if token == self._load_token:
                self._card.set_sources(self._sources)
                self._say(str(error) if isinstance(error, MediaError) else f"Couldn’t read it: {error}", "error")

        self._run(work, done, failed)

    def _run(self, target, on_done, on_failed=None) -> None:
        worker = ResultWorker(target, parent=self)
        self._workers.append(worker)
        worker.done.connect(on_done)
        if on_failed is not None:
            worker.failed.connect(on_failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_sequence_picked(self, sequence) -> None:
        if len(self._sources) == 1 and sequence is not self._sources[0].sequence:
            self.open([str(sequence.folder)], sequence)

    def _show_sources(self, sources: list) -> None:
        self._sources = list(sources)
        self._card.set_sources(self._sources)
        self._output_edited = False
        offered = self._offered()
        for panel in offered:
            panel.set_sources(self._sources)
        self._actions.set_chips([(panel.KEY, panel.TITLE, panel.TIP) for panel in offered])
        remembered = str(self._settings.get("action", "") or "")
        if remembered in self._actions.keys():
            self._actions.set_current(remembered)
        if self._sources:
            self._message_label.hide()
        self._show_action()

    def _offered(self) -> list:
        """The panels of the actions that fit the sources."""
        return [panel for panel in self._panels.values() if self._sources and panel.accepts(self._sources)]

    def _panel(self):
        """The panel of the action that is picked (None without a source)."""
        return self._panels.get(self._actions.current()) if self._sources else None

    def _on_action_picked(self, key: str) -> None:
        self._settings["action"] = key
        self._output_edited = False
        self._show_action()

    def _show_action(self) -> None:
        panel = self._panel()
        for other in self._panels.values():
            other.setVisible(other is panel)
        self._stack.setVisible(panel is not None)
        self._actions.setVisible(panel is not None)
        if panel is not None:
            self._start_button.setText(panel.BUTTON)
        self._refresh_presets()
        self._suggest_output()
        self._refresh_controls()
        self._schedule_estimate()

    def _on_panel_changed(self) -> None:
        if self._applying:
            return
        panel = self._panel()
        if panel is not None:
            self._start_button.setText(panel.BUTTON)
        self._suggest_output()
        self._save_settings()
        self._schedule_estimate()

    def _refresh_controls(self) -> None:
        panel = self._panel()
        shown = panel is not None
        single = shown and self._one_result()
        for widget in (self._output_caption, self._output, self._output_button):
            widget.setVisible(single)
        self._output_note.setVisible(shown and not single)
        for widget in (self._folder_button, self._command_button, self._start_button, self._estimate_label):
            widget.setVisible(shown)
        self._start_button.setEnabled(shown and self._ffmpeg.tools() is not None)
        folder = self._folder()
        self._folder_button.setText("Results: " + (f"into {Path(folder).name}" if folder else "next to the source") + "  ▾")
        if shown and not single:
            self._output_note.setText(f"{len(self._sources)} results — "
                                      + (f"all into {folder}" if folder else "each next to its source") + ".")

    def _one_result(self) -> bool:
        """The picked action writes ONE file (one source, or an action that combines them)."""
        panel = self._panel()
        return panel is not None and (panel.COMBINES or len(self._sources) == 1)

    # --- presets ----------------------------------------------------------------------------

    def _presets_of(self, panel) -> dict:
        """The presets of `panel`: the user's once they changed anything, the built-in ones until then."""
        if self._has_node("presets", panel.KEY):
            return self._node("presets", panel.KEY)
        return {name: dict(settings) for name, settings in panel.PRESETS.items()}

    def _refresh_presets(self) -> None:
        panel = self._panel()
        shown = panel is not None
        self._presets_caption.setVisible(shown)
        self._presets.setVisible(shown)
        if not shown:
            return
        presets = self._presets_of(panel)
        chips = [(name, name, ",  ".join(f"{key}: {value}" for key, value in settings.items())
                  + chr(10) + "Click: use these settings  ·  right click: remove") for name, settings in presets.items()]
        self._presets.set_chips(chips, removable=set(presets))

    def _on_preset_clicked(self, name: str) -> None:
        panel = self._panel()
        settings = self._presets_of(panel).get(name) if panel is not None else None
        if settings is None:
            return
        self._applying = True
        try:
            panel.apply_settings({**panel.settings(), **settings})
        finally:
            self._applying = False
        self._on_panel_changed()
        self._say(f"“{name}” applied.")

    def _on_preset_added(self, name: str) -> None:
        panel = self._panel()
        if panel is None:
            return
        presets = self._presets_of(panel)
        replaced = name in presets
        presets[name] = panel.settings()
        self._config["presets"][panel.KEY] = presets
        self._refresh_presets()
        self._say(f"Preset “{name}” " + ("updated." if replaced else "saved."))

    def _on_preset_removed(self, name: str) -> None:
        panel = self._panel()
        if panel is None:
            return
        presets = self._presets_of(panel)
        presets.pop(name, None)
        self._config["presets"][panel.KEY] = presets
        self._refresh_presets()

    # --- where results go --------------------------------------------------------------------

    def _folder(self) -> str:
        """The one folder for all results ("" = next to each source)."""
        folder = str(self._settings.get("output_folder", "") or "")
        return folder if folder and Path(folder).is_dir() else ""

    def _on_folder_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        folder = self._folder()
        beside = menu.addAction("Next to each source")
        beside.setCheckable(True)
        beside.setChecked(not folder)
        beside.triggered.connect(lambda: self._set_folder(""))
        if folder:
            current = menu.addAction(f"Into {folder}")
            current.setCheckable(True)
            current.setChecked(True)
        menu.addSeparator()
        menu.addAction("Choose a folder…").triggered.connect(self._on_choose_folder)
        self._folder_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(self._folder_button.mapToGlobal(qt.QtCore.QPoint(0, self._folder_button.height())))

    def _on_choose_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder for results", self._folder())
        if folder:
            self._set_folder(folder)

    def _set_folder(self, folder: str) -> None:
        self._settings["output_folder"] = folder
        self._output_edited = False
        self._suggest_output()
        self._refresh_controls()

    def _suggest_output(self) -> None:
        """Puts a free name into "Save as" — unless the user typed their own."""
        panel = self._panel()
        if panel is None or self._output_edited or not self._one_result():
            return
        self._output.setText(str(panel.output_for(self._sources[0], self._folder() or None, self._queue.outputs())))
        self._output_caption.setText("Save into" if panel.INTO_FOLDER else "Save as")

    def _on_browse_output(self) -> None:
        panel = self._panel()
        if panel is not None and panel.INTO_FOLDER:
            start = Path(self._output.text().strip() or ".")
            path = qt.QtWidgets.QFileDialog.getExistingDirectory(
                self, "The folder for the frames", str(start if start.is_dir() else start.parent))
        else:
            path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Save the result as", self._output.text(),
                                                                     "All files (*.*)")
        if path:
            self._output.setText(path)
            self._output_edited = True

    # --- the jobs ----------------------------------------------------------------------------

    def _jobs(self, quiet: bool = False):
        """The Jobs for what is on screen — one, or one per source; None (and
        a message, unless `quiet`) if they can't be made."""
        panel = self._panel()
        if panel is None:
            return None
        try:
            if self._one_result():
                text = self._output.text().strip()
                if not text:
                    raise MediaError("Say where to save the result.")
                output = Path(text)
                if panel.INTO_FOLDER:
                    if output.is_file():
                        raise MediaError(f"{output.name} is a file — the frames need a folder.")
                elif not output.suffix:
                    output = output.with_suffix(panel.suffix(self._sources[0]))
                if any(not source.is_sequence and output.resolve() == source.path.resolve() for source in self._sources):
                    raise MediaError("The result can’t replace the file it is made from — pick another name.")
                if panel.COMBINES:
                    return [panel.combined_job(self._sources, output)]
                return [panel.job(self._sources[0], output)]
            jobs, taken = [], list(self._queue.outputs())
            for source in self._sources:
                output = panel.output_for(source, self._folder() or None, taken)
                taken.append(output)
                jobs.append(panel.job(source, output))
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
        for job in jobs:
            self._queue.add(job)
        self._message_label.hide()
        self._output_edited = False
        self._suggest_output()  # the next job gets the next free name

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

    def _schedule_estimate(self) -> None:
        """What is on screen changed: the old guess is gone at once, a new one follows shortly."""
        self._estimate_token += 1  # an estimate still on its way is for the old settings
        self._estimate_label.setText("…" if self._panel() is not None and self._ffmpeg.tools() is not None else "")
        self._estimate_timer.start()

    def _estimate(self) -> None:
        """Guesses the size and time of what "start" would make (on a worker thread)."""
        self._estimate_token += 1
        token = self._estimate_token
        tools = self._ffmpeg.tools()
        jobs = self._jobs(quiet=True) if tools is not None else None
        if not jobs:
            self._estimate_label.setText("")
            return
        job, count = jobs[0], len(jobs)
        self._discard(jobs[1:])
        self._estimate_label.setText("…")

        def work():
            try:
                return estimate(tools, job)
            finally:
                clean_up(job, remove_output=False)

        def done(guess) -> None:
            if token == self._estimate_token:
                text = guess.text() if guess is not None else ""
                self._estimate_label.setText(text + ("  each" if text and count > 1 else ""))

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

    # --- drops ---------------------------------------------------------------------------------

    @staticmethod
    def _dropped_paths(event) -> list:
        data = event.mimeData()
        return [url.toLocalFile() for url in (data.urls() if data.hasUrls() else []) if url.isLocalFile()]

    def dragEnterEvent(self, event) -> None:
        if self._dropped_paths(event):
            self._card.set_dragging(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._card.set_dragging(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._card.set_dragging(False)
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # One sound file dropped on one open source is its new sound, not a new source.
        if len(paths) == 1 and Path(paths[0]).suffix.lower() in AUDIO_SUFFIXES and len(self._sources) == 1:
            name = Path(paths[0]).name
            if self._sources[0].is_sequence:
                self._panels["sequence"].set_sound(paths[0])
                self._say(f"{name} will be the sound of the video.")
            else:
                self._panels["sound"].set_sound(paths[0])
                self._actions.set_current("sound")
                self._on_action_picked("sound")
                self._say(f"{name} is set as the new sound — “Replace the sound” puts it under the video.")
            return
        self.open(paths)

    # --- small things -----------------------------------------------------------------------------

    def _say(self, text: str, state: str = "") -> None:
        """A line under the settings ("" / "error")."""
        self._message_label.setText(text)
        if self._message_label.property("state") != state:
            self._message_label.setProperty("state", state)  # media.qss: QLabel#mediaMessage[state]
            repolish(self._message_label)
        self._message_label.show()
        self._message_timer.start()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        page = MediaPage()
        page.resize(760, 620)
        page.show()
