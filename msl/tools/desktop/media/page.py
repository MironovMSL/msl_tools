# tools/desktop/media/page.py
import os
import sys
import tempfile
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment.send_to import create_send_to, has_send_to, remove_send_to
from msl_tools.msl.core.environment.taskbar import TaskbarProgress
from msl_tools.msl.core.media import Estimate, MediaError, estimate, preview
from msl_tools.msl.core.media.run import clean_up
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import FfmpegBar, link_button
from msl_tools.msl.tools.desktop.media.history import ResultHistory
from msl_tools.msl.tools.desktop.media.job_queue import DONE, FAILED, JobList, JobQueue
from msl_tools.msl.ui.desktop_notice import DesktopNotice
from msl_tools.msl.tools.desktop.media.option_panels import PANELS
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES, load_source, load_sources
from msl_tools.msl.tools.desktop.media.source_card import SourceCard
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
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
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.text_dialog import TextDialog
from msl_tools.msl.ui.workers.result_worker import ResultWorker

StylesheetBuilder.register_template(Path(__file__).with_name("media.qss"))


class StartButton(IconPushButton):
    """The button that starts the picked action: its icon beside its text,
    and — while jobs run — a thin bar along its bottom edge showing how far
    the whole batch is. Colors: qproperty iconColor (IconPushButton),
    progressColor / progressTrackColor (media.qss)."""

    BAR_HEIGHT = 3

    progressColor = color_property("_progress_color")
    progressTrackColor = color_property("_progress_track_color")

    def __init__(self, parent=None):
        super().__init__(None, parent=parent)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._progress_color = qt.QtGui.QColor(fallback.surface)
        self._progress_track_color = qt.QtGui.QColor(fallback.surface)
        self._progress_track_color.setAlpha(70)
        self._progress: float | None = None

    def set_progress(self, fraction: float | None) -> None:
        """0..1 while jobs run, None when nothing does."""
        if fraction != self._progress:
            self._progress = fraction
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._progress is None:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        track = qt.QtCore.QRectF(6, self.height() - self.BAR_HEIGHT - 3, self.width() - 12, self.BAR_HEIGHT)
        painter.setBrush(self._progress_track_color)
        painter.drawRoundedRect(track, self.BAR_HEIGHT / 2, self.BAR_HEIGHT / 2)
        done = qt.QtCore.QRectF(track)
        done.setWidth(track.width() * min(max(self._progress, 0.0), 1.0))
        painter.setBrush(self._progress_color)
        painter.drawRoundedRect(done, self.BAR_HEIGHT / 2, self.BAR_HEIGHT / 2)
        painter.end()


class MediaPage(qt.QtWidgets.QWidget):
    """The Media tool: quick work with video and image sequences through
    ffmpeg (core/media), without knowing ffmpeg.

    Top to bottom:
    - FfmpegBar — is ffmpeg there; if not, download it or point at a copy;
    - SourceCard — what is being worked on. Drop videos, a folder of frames
      or frames of sequences anywhere on the page (or choose them); they are
      read on a worker thread. SEVERAL can be dropped at once: all videos,
      or all image sequences;
    - the actions: an ActionStrip — icon buttons — of the actions that fit
      the sources (their panels are option_panels.PANELS). Most make one
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

    # --- recent sources, paste, set up again ----------------------------------------------------

    def _recent(self) -> list:
        """The recent sources that are still there, newest first."""
        entries = self._settings.get("recent", []) or []
        return [list(entry) for entry in entries if isinstance(entry, list) and entry and Path(entry[0]).exists()]

    def _remember_recent(self, paths: list) -> None:
        entries = [entry for entry in self._recent() if entry != paths]
        self._settings["recent"] = [paths] + entries[:self.RECENT_KEPT - 1]
        self._card.set_recent(self._settings["recent"])

    def _on_paste(self) -> None:
        """Ctrl+V on the page: files copied in Explorer, or a path copied as text, are opened."""
        data = qt.QtGui.QGuiApplication.clipboard().mimeData()
        paths = [url.toLocalFile() for url in (data.urls() if data is not None and data.hasUrls() else [])
                 if url.isLocalFile()]
        if not paths and data is not None and data.hasText():
            lines = [line.strip().strip('"') for line in data.text().splitlines()]
            paths = [line for line in lines if line and Path(line).exists()]
        if not paths:
            self._say("Nothing to open on the clipboard — copy a video or a folder of frames first.", "error")
            return
        if self._is_sound_drop(paths):
            self._take_sound(paths[0])
            return
        self.open(paths)

    def _set_up_again(self, item) -> None:
        """A job's video and its settings, back on the page — to change something and start again."""
        recipe = item.recipe
        sources = [path for path in recipe.get("sources", []) if Path(path).exists()]
        if not sources:
            self._say("The video it was made from isn’t there any more.", "error")
            return
        self._pending_recipe = recipe
        self.open(sources)

    def _recipe(self, panel, index: int, count: int) -> dict:
        """What makes job `index` of `count`: the action, its settings, its source(s)."""
        paths = [str(source.path) for source in self._sources]
        if not panel.COMBINES and count == len(self._sources):
            paths = [paths[index]]
        return {"action": panel.KEY, "settings": panel.settings(), "sources": paths}

    # --- Explorer's "Send to" -------------------------------------------------------------------

    def _send_to_command(self) -> tuple:
        """(program, arguments, working folder) that start this hub and hand it files."""
        python = Path(sys.executable)
        windowed = python.with_name("pythonw.exe")
        program = windowed if windowed.is_file() else python
        return program, ["-m", "msl_tools.msl.run_hub", "--open"], Resources().fsManager.PARENT_DIR

    def _set_send_to(self, wanted: bool) -> None:
        if not wanted:
            remove_send_to(self.SEND_TO_NAME)
            self._say("“Send to → MSL Media” is gone from Explorer.")
            return
        program, arguments, folder = self._send_to_command()
        icon = Resources().fsManager.icons / "brand" / "hub.ico"
        if create_send_to(self.SEND_TO_NAME, program, arguments, folder, icon):
            self._say("In Explorer: right click a video or a folder of frames → Send to → MSL Media.")
        else:
            self._say("Couldn’t add it to Explorer’s “Send to” menu.", "error")

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
        self._mark_preset()

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
        menu.addSeparator()
        notify = menu.addAction("Tell me when the jobs are done")
        notify.setCheckable(True)
        notify.setChecked(self._notifies())
        notify.setToolTip("A notice from Windows when the last job is over and this window isn’t in front")
        notify.triggered.connect(lambda checked: self._settings.__setitem__("notify", bool(checked)))
        send_to = menu.addAction("Explorer: “Send to → MSL Media”")
        send_to.setCheckable(True)
        send_to.setChecked(has_send_to(self.SEND_TO_NAME))
        send_to.setToolTip("Adds “MSL Media” to the “Send to” menu of Explorer’s right click: files sent there "
                           "open here — in the hub that is open, or a new one")
        send_to.triggered.connect(lambda checked: self._set_send_to(bool(checked)))
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
        self._set_output(panel.output_for(self._sources[0], self._folder() or None, self._queue.outputs()))
        self._output_caption.setToolTip("Save into this folder" if panel.INTO_FOLDER else "Save as")

    def _set_output(self, path: Path) -> None:
        """Where the one result goes: its name into the field, its folder onto the line under it."""
        path = Path(path)
        self._output_dir = path.parent
        self._output.setText(path.name)
        self._output_folder.setText(f"in {path.parent}")

    def _output_path(self) -> Path | None:
        """The path the field stands for (None while it is empty). A name is taken in the
        folder shown under the field; a whole path typed into the field is taken as it is."""
        text = self._output.text().strip()
        if not text:
            return None
        typed = Path(text)
        return typed if typed.is_absolute() else self._output_dir / typed

    def _on_output_typed(self) -> None:
        """A whole path was typed or pasted: its folder moves to the line under the field."""
        text = self._output.text().strip()
        if text and Path(text).is_absolute() and Path(text).name:
            self._set_output(Path(text))

    def _on_browse_output(self) -> None:
        panel = self._panel()
        current = self._output_path() or Path(".")
        if panel is not None and panel.INTO_FOLDER:
            path = qt.QtWidgets.QFileDialog.getExistingDirectory(
                self, "The folder for the frames", str(current if current.is_dir() else current.parent))
        else:
            path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Save the result as", str(current),
                                                                     "All files (*.*)")
        if path:
            self._set_output(Path(path))
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
                output = panel.output_for(source, self._folder() or None, taken)
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
        if self._history_loaded:  # never before the old list was read: it would be overwritten
            self._history.save(self._queue.results())

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

    EMPTY_JOBS_HEIGHT = 92   # the list while it only says what will show up in it

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

    ESTIMATING = [("…", "estimating")]

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

    # --- drops ---------------------------------------------------------------------------------

    @staticmethod
    def _dropped_paths(event) -> list:
        data = event.mimeData()
        return [url.toLocalFile() for url in (data.urls() if data.hasUrls() else []) if url.isLocalFile()]

    def _is_own_drag(self, event) -> bool:
        """The drag started on this page — a finished result being taken out of the jobs list."""
        source = event.source()
        return source is not None and (source is self or self.isAncestorOf(source))

    def _takes_drop_at(self, event) -> bool:
        """Files from outside are taken anywhere on the page. A result
        dragged out of the page's OWN list is only taken on the source card
        (to work on it further): everywhere else it is on its way out, and
        letting go there must simply cancel the drag."""
        return not self._is_own_drag(event) or self._card.geometry().contains(event.position().toPoint())

    def _is_sound_drop(self, paths: list) -> bool:
        """One sound file over one open source: it is that source's sound, not a new source."""
        return len(paths) == 1 and Path(paths[0]).suffix.lower() in AUDIO_SUFFIXES and len(self._sources) == 1

    def _show_drop_target(self, paths: list, takes: bool) -> None:
        """Lights up WHAT WOULD TAKE the drop — and only that: the source card
        for a new source; for a sound file the sound field it lands in (with a
        line saying so — the field may be on another action's panel)."""
        sound = takes and self._is_sound_drop(paths)
        self._card.set_dragging(takes and not sound)
        if sound == self._sound_target_lit:
            return
        self._sound_target_lit = sound
        sequence = bool(self._sources) and self._sources[0].is_sequence
        self._panels["sequence" if sequence else "sound"].set_sound_target(sound)
        if sound:
            self._say("Drop it anywhere here — it becomes the sound of the video." if sequence else
                      "Drop it anywhere here — it is set as the new sound of the video.")
        else:
            self._message_label.hide()

    def dragEnterEvent(self, event) -> None:
        paths = self._dropped_paths(event)
        if not paths:
            event.ignore()
            return
        # Accepted even where a drop won't be taken: only then do the move events follow.
        self._show_drop_target(paths, self._takes_drop_at(event))
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        paths = self._dropped_paths(event)
        takes = bool(paths) and self._takes_drop_at(event)
        self._show_drop_target(paths, takes)
        if takes:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._show_drop_target([], False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._dropped_paths(event)
        self._show_drop_target([], False)
        if not paths or not self._takes_drop_at(event):
            event.ignore()
            return
        event.acceptProposedAction()
        # One sound file dropped on one open source is its new sound, not a new source.
        if self._is_sound_drop(paths):
            self._take_sound(paths[0])
            return
        self.open(paths)

    def _take_sound(self, path: str) -> None:
        """One sound file for the one open source (dropped or pasted): it becomes its sound."""
        name = Path(path).name
        if self._sources[0].is_sequence:
            self._panels["sequence"].set_sound(path)
            self._say(f"{name} will be the sound of the video.")
        else:
            self._panels["sound"].set_sound(path)
            self._actions.set_current("sound")
            self._on_action_picked("sound")
            self._say(f"{name} is set as the new sound — “Replace the sound” puts it under the video.")

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
