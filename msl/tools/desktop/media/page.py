# tools/desktop/media/page.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment.taskbar import TaskbarProgress
from msl_tools.msl.core.media import MediaError
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import FfmpegBar, link_button
from msl_tools.msl.tools.desktop.media.history import ResultHistory
from msl_tools.msl.tools.desktop.media.job_queue import JobList, JobQueue
from msl_tools.msl.ui.desktop_notice import DesktopNotice
from msl_tools.msl.tools.desktop.media.panels import PANELS
from msl_tools.msl.tools.desktop.media.source import load_source, load_sources, prune_temp
from msl_tools.msl.tools.desktop.media.source_card import SourceCard
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.theme.stylesheet_builder import StylesheetBuilder
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.buttons.motion_icon_button import MotionIconButton
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.labels import ElidedLabel
from msl_tools.msl.ui.widgets.compositions.action_strip import ActionStrip
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.compositions.fact_tiles import FactTiles
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.workers.result_worker import ResultWorker
from msl_tools.msl.tools.desktop.media.start_button import StartButton
from msl_tools.msl.tools.desktop.media.page_output import _OutputMixin
from msl_tools.msl.tools.desktop.media.page_jobs import _JobsMixin
from msl_tools.msl.tools.desktop.media.page_drops import _DropsMixin


StylesheetBuilder.register_template(Path(__file__).with_name("media.qss"))


class MediaPage(_OutputMixin, _JobsMixin, _DropsMixin, qt.QtWidgets.QWidget):
    """The Media tool: quick work with video and image sequences through
    ffmpeg (core/media), without knowing ffmpeg.

    Top to bottom:
    - FfmpegBar — is ffmpeg there; if not, download it or point at a copy;
    - SourceCard — what is being worked on. Drop videos, a folder of frames
      or frames of sequences anywhere on the page (or choose them); they are
      read on a worker thread. SEVERAL can be dropped at once: all videos,
      or all image sequences;
    - the actions: an ActionStrip — icon buttons — of the actions that fit
      the sources (their panels are panels.PANELS). Most make one
      result per source; Join and Compare make one result out of all;
    - the picked action's CARD, top to bottom: a header (its icon, its name
      in capitals, one line saying what it does); presets — saved settings
      of that action as chips: a click applies one, "+ Save preset" keeps
      the current settings under a name; the action's panel; then where
      the result goes and the start:
    - "Save as" (one result) or a note where the results go (several);
      where results go (next to each source, or one folder for all); an
      estimate of the result's size and time; "Preview" (a few seconds of
      the result, made with the settings on screen and opened in the
      player); "Command"; the start button, which puts the job(s) into the
      queue;
    - the queue (job_queue.py): jobs run one after another; a finished one
      is opened with a click, dragged out, copied, shown in its folder.
      The results stay listed across restarts of the hub (history.py).

    While jobs run, the window's taskbar button shows how far the batch is;
    when the last one is over and the user is looking elsewhere, the system
    shows a notice (a click on it brings the window back).

    Nothing is copied: sources stay where they are. Settings:
    Resources().configsDesktopHubMng "media" — `settings` (ffmpeg_path,
    output_folder, action, notify), `panels` (each panel's choices),
    `presets`; the results list is `history.json` next to it.
    """

    TOOL_NAME = "media"
    DEFAULTS = {"settings": {"ffmpeg_path": "", "output_folder": "", "action": "", "notify": True,
                             "jobs_folded": False, "recent": []},
                "panels": {}, "presets": {}}
    MESSAGE_MS = 9000
    RECENT_KEPT = 6
    SEND_TO_NAME = "MSL Media"   # Explorer: right click -> Send to -> MSL Media
    ESTIMATE_DELAY_MS = 700
    SEQUENCE_SIZE_FRAMES = 3000  # a longer sequence's files aren't added up for "how much smaller"

    def __init__(self, parent=None):
        super().__init__(parent)
        resources = Resources()
        self._config = resources.configsDesktopHubMng.get_config(self.TOOL_NAME, defaults=self.DEFAULTS)
        self._settings = self._config["settings"]
        self._history = ResultHistory(resources.configsDesktopHubMng.base_dir / self.TOOL_NAME)
        self._history_loaded = False
        self._history_saved: list = []  # what history.json holds now (ResultRecords compare by value)
        self._taskbar: TaskbarProgress | None = None
        self._notice: DesktopNotice | None = None
        self._sources: list = []
        self._load_token = 0           # only the newest load's answer counts
        self._estimate_token = 0
        self._preview_token = 0
        self._preview_count = 0
        self._sound_target_lit = False  # a sound file is being dragged over the page
        self._pending_recipe: dict | None = None   # "set up again": applied once its sources are loaded
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
        # The page's heading, like a card's: an accent icon, the name in capitals, a quiet line.
        self._title_icon = TintedIcon(UiResources().iconManager.get_icon("media", sub_folder="tools"), 16)
        self._title_icon.setObjectName("mediaCardIcon")
        self._title_label = qt.QtWidgets.QLabel("MEDIA")
        self._title_label.setObjectName("mediaCardTitle")
        self._subtitle_label = qt.QtWidgets.QLabel("video and image sequences")
        self._subtitle_label.setObjectName("mediaHint")
        self._ffmpeg = FfmpegBar(self._settings)
        # ffmpeg's state as a status pill: a green dot + "ffmpeg 8.0" (a click: its menu).
        self._ffmpeg_pill = qt.QtWidgets.QFrame()
        self._ffmpeg_pill.setObjectName("mediaStatusPill")
        self._ffmpeg_dot = qt.QtWidgets.QLabel()
        self._ffmpeg_dot.setObjectName("mediaStatusDot")
        self._ffmpeg_dot.setFixedSize(8, 8)
        self._ffmpeg_pill.hide()
        self._card = SourceCard()

        self._panels = {panel.KEY: panel(self._ffmpeg.tools) for panel in PANELS}
        for key, panel in self._panels.items():
            panel.bind(self._panels)
            saved = self._node("panels", key)
            if saved:
                panel.apply_settings(saved)
        self._actions = ActionStrip()
        self._action_icon = TintedIcon(None, 16)
        self._action_icon.setObjectName("mediaCardIcon")
        self._action_title = qt.QtWidgets.QLabel()
        self._action_title.setObjectName("mediaCardTitle")
        self._action_tip = qt.QtWidgets.QLabel()
        self._action_tip.setObjectName("mediaHint")
        self._action_tip.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._action_card = qt.QtWidgets.QFrame()
        self._action_card.setObjectName("mediaCard")
        icons = UiResources().iconManager
        self._presets_caption = TintedIcon(icons.get_icon("bookmark", sub_folder="actions"), 16)
        self._presets_caption.setToolTip("Presets — saved settings of this action. Click one to use it;"
                                         + chr(10) + "the bookmark with a plus keeps the current settings as a new one.")
        self._presets = ChipBar(add_text="Save these settings as a preset", name_placeholder="Preset name, then Enter",
                                add_icon=UiResources().iconManager.get_icon("bookmark_add", sub_folder="actions"))
        # Only the picked action's panel is shown; the holder is as tall as that one
        # panel (a stacked widget would be as tall as the tallest of them).
        self._stack = qt.QtWidgets.QWidget()
        stack_layout = qt.QtWidgets.QVBoxLayout(self._stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        for panel in self._panels.values():
            stack_layout.addWidget(panel)
            panel.hide()

        self._output_caption = TintedIcon(icons.get_icon("save", sub_folder="actions"), 16)
        self._output_caption.setToolTip("Save as")
        # The field holds the result's NAME; the folder it goes into is the quiet line under it
        # (a whole path in the field was cut off at the left - the name was what one couldn't see).
        self._output = qt.QtWidgets.QLineEdit()
        self._output.setToolTip("The result's name. A name that is free is suggested; change it if you like"
                                + chr(10) + "(a whole path can be typed or pasted here too).")
        self._output_dir = Path()
        self._output_folder = ElidedLabel(elide=qt.QtCore.Qt.TextElideMode.ElideLeft)
        self._output_folder.setObjectName("mediaHint")
        self._output_button = IconPushButton(UiResources().iconManager.get_icon("browse", sub_folder="actions"),
                                             "Choose where to save the result", fallback_text="…")
        self._output_button.setFixedSize(26, 22)
        self._output_note = qt.QtWidgets.QLabel()
        self._output_note.setObjectName("mediaCaption")
        self._output_note.setWordWrap(True)
        self._folder_button = self._action_button("folder_into", "▾")  # its menu: where results go
        # What to expect, as DATA: tiles like the source's facts (a pill here read as one more control).
        self._estimate_tiles = FactTiles()
        self._estimate_tiles.setToolTip("About how big the result will be and how long it will take — "
                                        "guessed from a second of it")
        self._preview_button = self._action_button("eye", "◉")
        self._command_button = self._action_button("code", "</>", "The command: what ffmpeg will be asked to do — "
                                                                  "to read, or to copy")
        self._start_button = StartButton()
        self._start_button.setObjectName("mediaStart")
        self._start_button.setText("Create video")
        self._start_button.setProperty("primary", True)
        self._start_button.setMinimumWidth(130)
        self._card_animation = qt.QtCore.QVariantAnimation(self)   # the action card's height, on a switch
        self._card_animation.setDuration(170)
        self._card_animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._card_animation.valueChanged.connect(lambda value: self._action_card.setFixedHeight(int(value)))
        self._card_animation.finished.connect(self._free_card_height)
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

        self._jobs_icon = TintedIcon(UiResources().iconManager.get_icon("report", sub_folder="actions"), 16)
        self._jobs_icon.setObjectName("mediaCardIcon")
        self._jobs_title = qt.QtWidgets.QLabel("JOBS")
        self._jobs_title.setObjectName("mediaCardTitle")
        self._jobs_fold = TintedIcon(icons.get_icon("chevron_down", sub_folder="actions"), 12)
        self._jobs_header = qt.QtWidgets.QWidget()   # a click on it folds the list away
        self._jobs_header.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._jobs_header.setToolTip("Click to fold the list away, or to bring it back")
        self._jobs_header.installEventFilter(self)
        self._jobs_divider = self._divider()
        self._filler = qt.QtWidgets.QWidget()        # takes the room under the card while the list is folded
        self._filler.hide()
        self._jobs_card = qt.QtWidgets.QFrame()
        self._jobs_card.setObjectName("mediaCard")
        self._clear_button = link_button("Clear finished", "Take the jobs that are over off the list (their files stay)")
        self._queue = JobQueue(self._ffmpeg.tools, self)
        self._job_list = JobList(self._queue)

    def _build_layout(self) -> None:
        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self._title_icon)
        header.addWidget(self._title_label)
        header.addWidget(self._subtitle_label, 1)
        pill = qt.QtWidgets.QHBoxLayout(self._ffmpeg_pill)
        pill.setContentsMargins(9, 1, 3, 1)
        pill.setSpacing(2)
        pill.addWidget(self._ffmpeg_dot)
        pill.addWidget(self._ffmpeg.status_button())
        header.addWidget(self._ffmpeg_pill)

        # The picked action's card: header · presets · its panel · where the result goes + start.
        action_header = qt.QtWidgets.QHBoxLayout()
        action_header.setContentsMargins(12, 9, 12, 2)
        action_header.setSpacing(8)
        action_header.addWidget(self._action_icon)
        action_header.addWidget(self._action_title)
        action_header.addWidget(self._action_tip, 1)

        presets = qt.QtWidgets.QHBoxLayout()
        presets.setContentsMargins(12, 2, 12, 8)
        presets.setSpacing(8)
        presets.addWidget(self._presets_caption, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        presets.addWidget(self._presets, 1)

        output = qt.QtWidgets.QHBoxLayout()
        output.setContentsMargins(12, 8, 12, 0)
        output.setSpacing(8)
        output.addWidget(self._output_caption)
        output.addWidget(self._output, 1)
        output.addWidget(self._output_button)
        output.addWidget(self._output_note, 1)
        output_folder = qt.QtWidgets.QHBoxLayout()
        output_folder.setContentsMargins(12 + 16 + 8 + 2, 0, 12, 0)  # under the field, past the icon
        output_folder.addWidget(self._output_folder, 1)

        start = qt.QtWidgets.QHBoxLayout()
        start.setContentsMargins(12, 0, 12, 10)
        start.setSpacing(8)
        start.addWidget(self._estimate_tiles, 1)  # takes what is left; clipped, never widening the window
        start.addWidget(self._folder_button)
        start.addWidget(self._preview_button)
        start.addWidget(self._command_button)
        start.addWidget(self._start_button)

        action_card = qt.QtWidgets.QVBoxLayout(self._action_card)
        action_card.setContentsMargins(1, 1, 1, 1)
        action_card.setSpacing(6)
        action_card.addLayout(action_header)
        action_card.addLayout(presets)
        action_card.addWidget(self._divider())
        action_card.addWidget(self._stack)
        action_card.addWidget(self._divider())
        action_card.addLayout(output)
        action_card.addLayout(output_folder)
        action_card.addLayout(start)

        jobs = qt.QtWidgets.QHBoxLayout(self._jobs_header)
        jobs.setContentsMargins(12, 8, 10, 6)
        jobs.setSpacing(8)
        jobs.addWidget(self._jobs_icon)
        jobs.addWidget(self._jobs_title, 1)
        jobs.addWidget(self._clear_button)
        jobs.addWidget(self._jobs_fold)
        jobs_card = qt.QtWidgets.QVBoxLayout(self._jobs_card)
        jobs_card.setContentsMargins(1, 1, 1, 1)
        jobs_card.setSpacing(0)
        jobs_card.addWidget(self._jobs_header)
        jobs_card.addWidget(self._jobs_divider)
        jobs_card.addWidget(self._job_list, 1)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 8)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._ffmpeg)
        layout.addWidget(self._card)
        layout.addWidget(self._actions)
        layout.addWidget(self._action_card)
        layout.addWidget(self._message_label)
        layout.addWidget(self._jobs_card, 1)
        layout.addWidget(self._filler, 1)
        self._set_jobs_folded(bool(self._settings.get("jobs_folded", False)), remember=False)

    @staticmethod
    def _action_button(icon: str, glyph: str, tooltip: str = "") -> GlyphButton:
        """A small accent icon button beside the start button (media.qss: GlyphButton#mediaAction)."""
        button = GlyphButton(glyph, tooltip, size=qt.QtCore.QSize(28, 24))
        button.setObjectName("mediaAction")
        button.set_icon(UiResources().iconManager.get_icon(icon, sub_folder="actions"))
        return button

    @staticmethod
    def _divider() -> qt.QtWidgets.QFrame:
        """A hairline across a card (media.qss: QFrame#mediaDivider)."""
        line = qt.QtWidgets.QFrame()
        line.setObjectName("mediaDivider")
        line.setFixedHeight(1)
        return line

    def _build_connections(self) -> None:
        self._ffmpeg.tools_changed.connect(self._on_tools_changed)
        self._card.open_requested.connect(lambda path: self.open([path]))
        self._card.cleared.connect(lambda: self._show_sources([]))
        self._card.sequence_picked.connect(self._on_sequence_picked)
        self._card.add_requested.connect(self._on_add_sources)
        self._card.recent_requested.connect(lambda paths: self.open(paths))
        self._job_list.again_requested.connect(self._set_up_again)
        paste = qt.QtGui.QShortcut(qt.QtGui.QKeySequence(qt.QtGui.QKeySequence.StandardKey.Paste), self)
        paste.setContext(qt.QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)  # a field with the focus pastes text
        paste.activated.connect(self._on_paste)
        self._card.play_requested.connect(self._on_play_source)
        self._actions.clicked.connect(self._on_action_picked)
        self._presets.clicked.connect(self._on_preset_clicked)
        self._presets.add_requested.connect(self._on_preset_added)
        self._presets.remove_requested.connect(self._on_preset_removed)
        for panel in self._panels.values():
            panel.changed.connect(self._on_panel_changed)
        self._output.textEdited.connect(self._on_output_edited)
        self._output.editingFinished.connect(self._on_output_typed)
        self._output_button.clicked.connect(self._on_browse_output)
        self._folder_button.clicked.connect(self._on_folder_menu)
        self._preview_button.clicked.connect(self._on_preview)
        self._command_button.clicked.connect(self._on_show_command)
        self._queue.changed.connect(self._on_queue_changed)
        self._queue.removed.connect(lambda _item_id: self._save_history())
        for signal in (self._queue.added, self._queue.changed, self._queue.removed, self._queue.idle):
            signal.connect(lambda *_arguments: self._refresh_jobs_title())
        self._queue.idle.connect(self._on_queue_idle)
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
            self._card.set_recent(self._recent())
            self._queue.restore(self._history.load())  # what was made before the hub was last closed
            self._history_loaded = True
            self._history_saved = self._queue.results()
            self._run(prune_temp, lambda _removed: None)  # week-old previews, thumbnails, texts

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
        self._ffmpeg_pill.setVisible(tools is not None)
        self._card.set_enabled_for_input(tools is not None, "Media needs ffmpeg first — see the line above.")
        self._queue.refresh_thumbnails()  # the pictures of earlier results waited for ffmpeg
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

    def _on_add_sources(self, paths: list) -> None:
        """More files to work on together with what is loaded."""
        self.open([str(source.path) for source in self._sources] + list(paths))

    def _on_play_source(self) -> None:
        """The source's picture was clicked: the video in its player (a sequence: its folder)."""
        if self._sources and not self._open_file(self._sources[0].path):
            self._say(f"Couldn’t open {self._sources[0].path}", "error")

    def _on_sequence_picked(self, sequence) -> None:
        if len(self._sources) == 1 and sequence is not self._sources[0].sequence:
            self.open([str(sequence.folder)], sequence)

    def _show_sources(self, sources: list) -> None:
        self._sources = list(sources)
        if self._sources:
            self._remember_recent([str(source.path) for source in self._sources])
        self._card.set_sources(self._sources)
        self._output_edited = False
        offered = self._offered()
        for panel in offered:
            panel.set_sources(self._sources)
        icons = UiResources().iconManager
        # the icon by NAME: where there is a motion icon of that name, the button's icon moves
        self._actions.set_items([(panel.KEY, panel.TITLE, panel.TIP,
                                  panel.ICON if MotionIconButton.has_icon(panel.ICON)
                                  else icons.get_icon(panel.ICON, sub_folder="actions"), panel.GROUP)
                                 for panel in offered])
        remembered = str(self._settings.get("action", "") or "")
        if remembered in self._actions.keys():
            self._actions.set_current(remembered, animate=False)
        recipe, self._pending_recipe = self._pending_recipe, None
        if recipe and self._sources and recipe.get("action") in self._actions.keys():
            self._actions.set_current(recipe["action"], animate=False)   # "set up again": its action ...
            self._settings["action"] = recipe["action"]
            self._applying = True
            try:
                self._panels[recipe["action"]].apply_settings(dict(recipe.get("settings") or {}))  # ... and settings
            finally:
                self._applying = False
            self._save_settings()
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
        height = self._action_card.height() if self._action_card.isVisible() else 0
        self._show_action()
        self._animate_card_from(height)

    def _animate_card_from(self, height: int) -> None:
        """The action card moves from `height` to what the newly picked action needs, instead of jumping."""
        card, layout = self._action_card, self._action_card.layout()
        self._card_animation.stop()
        self._free_card_height()
        layout.activate()
        wanted = layout.totalHeightForWidth(card.width()) if layout.hasHeightForWidth() else card.sizeHint().height()
        if not self.isVisible() or height <= 0 or abs(wanted - height) < 4:
            return
        self._card_animation.setStartValue(height)
        self._card_animation.setEndValue(wanted)
        card.setFixedHeight(height)
        self._card_animation.start()

    def _free_card_height(self) -> None:
        self._action_card.setMinimumHeight(0)
        self._action_card.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX

    def _show_action(self) -> None:
        panel = self._panel()
        for other in self._panels.values():
            other.setVisible(other is panel)
        self._stack.setVisible(panel is not None)
        # one action to pick from is no choice: the card's header names it
        self._actions.setVisible(panel is not None and len(self._actions.keys()) > 1)
        self._action_card.setVisible(panel is not None)
        if panel is not None:
            panel.refresh()
            self._action_icon.set_icon(UiResources().iconManager.get_icon(panel.ICON, sub_folder="actions"))
            self._action_title.setText(panel.TITLE.upper())
            self._action_tip.setText(panel.TIP)
        self._forget_error()
        self._refresh_buttons()
        self._refresh_presets()
        self._refresh_source_facts()
        self._suggest_output()
        self._refresh_controls()
        self._schedule_estimate()

    def _on_panel_changed(self) -> None:
        if self._applying:
            return
        self._forget_error()  # what it complained about has just been changed
        self._refresh_buttons()
        self._refresh_source_facts()
        self._mark_preset()
        self._suggest_output()
        self._save_settings()
        self._schedule_estimate()

    def _refresh_source_facts(self) -> None:
        """The tiles the picked action adds to the source card."""
        panel = self._panel()
        self._card.set_extra_facts(panel.source_facts(self._sources) if panel is not None else [])

    def _mark_preset(self) -> None:
        """Outlines the preset whose settings are exactly the ones on screen."""
        panel = self._panel()
        if panel is None:
            return
        current = panel.settings()
        self._presets.set_marked(name for name, settings in self._presets_of(panel).items()
                                 if settings and all(current.get(key) == value for key, value in settings.items()))

    def _on_output_edited(self, _text: str) -> None:
        self._output_edited = True
        self._forget_error()

    def _refresh_buttons(self) -> None:
        """The start and preview buttons say what the picked action does."""
        panel = self._panel()
        if panel is None:
            return
        self._start_button.setText(panel.BUTTON)
        self._start_button.set_source_icon(UiResources().iconManager.get_icon(panel.ICON, sub_folder="actions"))
        self._preview_token += 1  # a preview still being made is for other settings
        self._preview_button.setEnabled(self._ffmpeg.tools() is not None)
        self._preview_button.setToolTip("Preview: " + panel.PREVIEW_TIP[0].lower() + panel.PREVIEW_TIP[1:])

    def _refresh_controls(self) -> None:
        panel = self._panel()
        shown = panel is not None
        single = shown and self._one_result()
        for widget in (self._output_caption, self._output, self._output_button):
            widget.setVisible(single)
        self._output_note.setVisible(shown and not single)
        self._output_folder.setVisible(single)
        for widget in (self._folder_button, self._command_button, self._start_button):
            widget.setVisible(shown)
        self._preview_button.setVisible(shown and panel.PREVIEW)
        self._start_button.setEnabled(shown and self._ffmpeg.tools() is not None)
        self._refresh_buttons()
        folder = self._folder()
        self._folder_button.setToolTip("Where results go: " + (f"into {folder}" if folder else "next to each source")
                                       + chr(10) + "Click to change it.")
        if shown and not single:
            self._output_note.setText(f"{len(self._sources)} results — "
                                      + (f"all into {folder}" if folder else "each next to its source") + ".")

    def _one_result(self) -> bool:
        """The picked action writes ONE file (one source, or an action that combines them)."""
        panel = self._panel()
        return panel is not None and (panel.COMBINES or len(self._sources) == 1)

    EMPTY_JOBS_HEIGHT = 92   # the list while it only says what will show up in it

    ESTIMATING = [("…", "estimating")]

    # --- small things -----------------------------------------------------------------------------

    def _forget_error(self) -> None:
        """An error on screen is about settings that have just changed: it goes."""
        if self._message_label.isVisible() and self._message_label.property("state") == "error":
            self._message_label.hide()

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
