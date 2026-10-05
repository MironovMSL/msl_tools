# tools/desktop/batch/job_row.py
"""One scene of the Batch queue as a row — its settings live ON the row, as chips."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch.checks import ERROR, OK, WARNING, check, choose_renderer, worst
from msl_tools.msl.core.batch.frames import FramesError, format_frames, parse_frames
from msl_tools.msl.core.batch.job import (ARNOLD, AUTO, CANCELLED, CHECKING, DONE, FAILED, HW2,
                                          MODE_HEADLESS, MODE_WINDOW, REDSHIFT, RENDERER_TITLES, RUNNING, SIZES,
                                          BatchJob)
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel
from msl_tools.msl.ui.widgets.atoms.layouts.flow_layout import FlowLayout

RENDERERS = [AUTO, ARNOLD, HW2, REDSHIFT]
MODES = {MODE_WINDOW: "with Maya", MODE_HEADLESS: "no window"}
SYMBOLS = {ERROR: "✕", WARNING: "!", OK: "✓"}
STARTUP_CAMERAS = ("persp", "top", "front", "side")
DRAG_MIME = "application/x-msl-batch-job"   # a row dragged to another place in the queue


class _Chip(IconPushButton):
    """Private: one setting of a job as a pill — its icon and its value; a click opens what changes it.
    `tone` "error" outlines it in the error color (a setting the check found broken)."""

    def __init__(self, icon: str, tooltip: str):
        super().__init__(UiResources().iconManager.get_icon(icon, sub_folder="actions"), tooltip,
                         icon_size=qt.QtCore.QSize(13, 13))
        self.setObjectName("batchChip")
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)

    def set_value(self, text: str, tone: str = "") -> None:
        self.setText(text)
        if (self.property("tone") or "") != tone:
            self.setProperty("tone", tone)   # batch.qss: QPushButton#batchChip[tone="error"]
            repolish(self)


class JobRow(qt.QtWidgets.QFrame):
    """A job: on / off, a fold arrow, its last frame (once there is one), the scene's name, where it
    stands (a bar + a word); under that its SETTINGS AS CHIPS — frames, renderer, camera, size, how
    Maya runs, the Maya version — a click on one opens a menu (or a field, for the frames) right
    there. Unfolded, the row shows the scene's check, where the frames go and "then a video".
    While it renders the row fills from the left as far as it is.

    The row changes its job directly; `changed(id)` tells the page (it saves, refreshes), `reread(id)`
    asks for the scene to be read again (another Maya).

    A row is dragged by its picture or its name to another place in the queue (DRAG_MIME; the page
    takes the drop).

    Signals:
        picked(str), changed(str), reread(str), menu_requested(str, QPoint),
        split(str, str) — make a job of every camera / layer of this one ("camera" / "layer")
    """

    PICTURE = qt.QtCore.QSize(48, 27)
    STATUS_WIDTH = 150
    BAR = qt.QtCore.QSize(90, 5)

    progressColor = color_property("_progress_color", "update")
    selectedColor = color_property("_selected_color", "update")
    hoverColor = color_property("_hover_color", "update")
    barColor = color_property("_bar_color", "update")
    barTrackColor = color_property("_bar_track_color", "update")

    picked = qt.QtCore.Signal(str)
    changed = qt.QtCore.Signal(str)
    reread = qt.QtCore.Signal(str)
    menu_requested = qt.QtCore.Signal(str, object)
    split = qt.QtCore.Signal(str, str)

    def __init__(self, job: BatchJob, installed=(), environments=(), parent=None):
        super().__init__(parent)
        self._environments = list(environments)
        self._testing = False
        self._press = None
        self.setObjectName("batchJob")
        self.job_id = job.id
        self._job = job
        self._installed = sorted(installed)
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._progress_color = qt.QtGui.QColor(fallback.accent)
        self._progress_color.setAlpha(30)
        self._selected_color = qt.QtGui.QColor(fallback.accent)
        self._selected_color.setAlpha(20)
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._bar_color = qt.QtGui.QColor(fallback.accent)
        self._bar_track_color = qt.QtGui.QColor(fallback.border)
        self._fraction: float | None = None
        self._bar_fraction = 0.0
        self._selected = False
        self._open = False
        self._picture_file = None
        icons = UiResources().iconManager
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

        self._enabled = BaseCheckbox("")
        self._enabled.setToolTip("On: the queue renders it  ·  off: passed by")
        self._enabled.toggled.connect(self._on_enabled)
        self._fold = GlyphButton("›", "Show the check and where the frames go", size=qt.QtCore.QSize(20, 20))
        self._fold.setObjectName("batchAction")
        self._fold.clicked.connect(self.toggle_open)
        self._picture = qt.QtWidgets.QLabel()
        self._picture.setObjectName("batchPicture")
        self._picture.setFixedSize(self.PICTURE)
        self._picture.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._name = ElidedLabel()
        self._name.setObjectName("batchJobName")
        self._bar = qt.QtWidgets.QWidget()       # painted by the row (paintEvent): how far the job is
        self._bar.setFixedSize(self.BAR)
        self._count = qt.QtWidgets.QLabel()
        self._count.setObjectName("batchJobLine")
        self._status = qt.QtWidgets.QLabel()     # elided by hand: a fixed column
        self._status.setObjectName("batchJobStatus")
        self._status.setFixedWidth(self.STATUS_WIDTH)
        self._status.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        self._more = GlyphButton("⋯", "More", size=qt.QtCore.QSize(24, 22))
        self._more.setObjectName("batchAction")
        self._more.set_icon(icons.get_icon("more", sub_folder="actions"))
        self._more.clicked.connect(lambda: self.menu_requested.emit(
            self.job_id, self._more.mapToGlobal(qt.QtCore.QPoint(0, self._more.height()))))

        self._chips = {
            "frames": _Chip("film", "Frames — click to type: 1-120 · 1, 20, 78 · 1-100x5 (every 5th)"),
            "renderer": _Chip("clapper", "Renderer — Auto: what the scene is set up for"),
            "camera": _Chip("camera", "The camera that renders"),
            "size": _Chip("frame_fit", "The scene's resolution, or half / a quarter of it"),
            "mode": _Chip("hud", "With Maya: Maya opens minimized — Arnold renders without watermarks.\n"
                                 "No window: starts faster; Arnold marks the frames without a batch licence."),
            "maya": _Chip("scene", "The Maya that renders it"),
            "environment": _Chip("steps", "A Maya Gate environment: its variables and plug-in paths for the render"),
            "layer": _Chip("image_stack", "The Render Setup layer to render"),
            "format": _Chip("save", "The frames' file format (EXR: no window only)"),
        }
        for key, chip in self._chips.items():
            chip.clicked.connect(lambda _checked=False, key=key: self._on_chip(key))

        top = qt.QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        middle = qt.QtCore.Qt.AlignmentFlag.AlignVCenter
        top.addWidget(self._enabled, 0, middle)
        top.addWidget(self._fold, 0, middle)
        top.addWidget(self._picture, 0, middle)
        top.addWidget(self._name, 1, middle)
        top.addWidget(self._bar, 0, middle)
        top.addWidget(self._count, 0, middle)
        top.addWidget(self._status, 0, middle)
        top.addWidget(self._more, 0, middle)
        chips = qt.QtWidgets.QWidget()
        self._chip_flow = FlowLayout(chips, spacing=5)
        self._chip_flow.setContentsMargins(0, 0, 0, 0)
        for chip in self._chips.values():
            self._chip_flow.addWidget(chip)

        # unfolded: the check, the folder, "then a video"
        self._details = qt.QtWidgets.QFrame()
        self._details.setObjectName("batchDetails")
        self._issues = qt.QtWidgets.QVBoxLayout()
        self._issues.setSpacing(2)
        self._folder = ElidedLabel(elide=qt.QtCore.Qt.TextElideMode.ElideLeft)  # the end of a path matters
        self._folder.setObjectName("batchJobLine")
        self._folder_button = GlyphButton("…", "Pick the folder the frames go to", size=qt.QtCore.QSize(22, 20))
        self._folder_button.setObjectName("batchAction")
        self._folder_button.set_icon(icons.get_icon("browse", sub_folder="actions"))
        self._folder_button.clicked.connect(self._on_pick_folder)
        self._video = BaseCheckbox("Then make a video of the frames")
        self._video.toggled.connect(self._on_video)
        self._search = ElidedLabel(elide=qt.QtCore.Qt.TextElideMode.ElideLeft)
        self._search.setObjectName("batchJobLine")
        self._search_button = GlyphButton("…", "Pick a folder where missing textures and caches may be",
                                          size=qt.QtCore.QSize(22, 20))
        self._search_button.setObjectName("batchAction")
        self._search_button.set_icon(icons.get_icon("browse", sub_folder="actions"))
        self._search_button.clicked.connect(self._on_pick_search)
        self._search_clear = GlyphButton("✕", "Look nowhere else", size=qt.QtCore.QSize(22, 20))
        self._search_clear.setObjectName("batchAction")
        self._search_clear.set_icon(icons.get_icon("clear", sub_folder="actions"))
        self._search_clear.clicked.connect(lambda: self._set_search(""))
        folder_line = qt.QtWidgets.QHBoxLayout()
        folder_line.setSpacing(6)
        folder_caption = qt.QtWidgets.QLabel("Frames go to")
        folder_caption.setObjectName("batchCaption")
        folder_line.addWidget(folder_caption)
        folder_line.addWidget(self._folder, 1)
        folder_line.addWidget(self._folder_button)
        details = qt.QtWidgets.QVBoxLayout(self._details)
        details.setContentsMargins(10, 6, 10, 8)
        details.setSpacing(5)
        details.addLayout(self._issues)
        details.addLayout(folder_line)
        search_line = qt.QtWidgets.QHBoxLayout()
        search_line.setSpacing(6)
        search_caption = qt.QtWidgets.QLabel("Missing files")
        search_caption.setObjectName("batchCaption")
        search_line.addWidget(search_caption)
        search_line.addWidget(self._search, 1)
        search_line.addWidget(self._search_clear)
        search_line.addWidget(self._search_button)
        details.addLayout(search_line)
        details.addWidget(self._video)
        self._details.hide()
        self.set_open(False)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 8, 7)
        layout.setSpacing(5)
        layout.addLayout(top)
        indent = qt.QtWidgets.QHBoxLayout()
        indent.setContentsMargins(18 + 8 + 20 + 8, 0, 0, 0)   # under the picture, past the checkbox and the arrow
        indent.addWidget(chips, 1)
        layout.addLayout(indent)
        details_indent = qt.QtWidgets.QHBoxLayout()
        details_indent.setContentsMargins(18 + 8 + 20 + 8, 0, 0, 0)
        details_indent.addWidget(self._details, 1)
        layout.addLayout(details_indent)
        self.update_job(job)

    # --- what is shown ------------------------------------------------------------------------

    def set_installed(self, years) -> None:
        self._installed = sorted(years)

    def set_testing(self, testing: bool) -> None:
        """A test frame of this job is being made (shown in the status)."""
        if testing != self._testing:
            self._testing = testing
            self.update_job(self._job)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def is_open(self) -> bool:
        return self._open

    def toggle_open(self) -> None:
        self.set_open(not self._open)

    def set_open(self, open_: bool) -> None:
        self._open = bool(open_)
        self._details.setVisible(self._open)
        self._fold.set_glyph("⌄" if self._open else "›")
        icon = "chevron_down" if self._open else "chevron_right"
        self._fold.set_icon(UiResources().iconManager.get_icon(icon, sub_folder="actions"))

    def update_job(self, job: BatchJob) -> None:
        self._job = job
        self._enabled.blockSignals(True)
        self._enabled.set_checked_immediate(job.enabled)
        self._enabled.blockSignals(False)
        self._name.setText(job.name)
        self._name.setToolTip(job.scene)
        issues = check(job)
        broken = {issue.text for issue in issues if issue.level == ERROR}
        try:
            frames = job.frame_list()
        except FramesError:
            frames = []
        frames_tone = "error" if job.frames.strip() and not frames else ""
        self._chips["frames"].set_value(job.frames_text() + (f"  ({len(frames)})" if len(frames) > 1 else ""),
                                        frames_tone)
        renderer = choose_renderer(job) if job.probe else job.renderer
        missing_renderer = any("isn’t installed" in text for text in broken)
        self._chips["renderer"].set_value(
            RENDERER_TITLES.get(renderer, renderer) + (" — not installed" if missing_renderer else "")
            + (" · auto" if job.renderer == AUTO and not missing_renderer else ""), "error" if missing_renderer else "")
        camera_gone = any(text.startswith("The camera") for text in broken)
        self._chips["camera"].set_value(job.camera_name() or "camera ?", "error" if camera_gone else "")
        if job.probe:
            width, height = job.resolution()
            self._chips["size"].set_value(f"{width}×{height}" + ("" if job.size == "100%" else f" · {job.size}"))
        else:
            self._chips["size"].set_value(job.size)
        self._chips["mode"].set_value(MODES.get(job.mode, job.mode))
        self._chips["mode"].setVisible(renderer in (ARNOLD, AUTO))
        self._chips["maya"].set_value(f"Maya {job.maya}" if job.maya else
                                      f"Maya {job.probe.get('maya', '')}".strip() if job.probe else "Maya auto")
        self._chips["environment"].set_value(job.environment or "no environment")
        self._chips["environment"].setVisible(bool(job.environment) or len(self._environments) > 0)
        layers = job.probe.get("render_layers") or []
        layer_broken = any("render layer" in text for text in broken)
        self._chips["layer"].set_value(job.layer or "layer as saved", "error" if layer_broken else "")
        self._chips["layer"].setVisible(bool(layers) or bool(job.layer))
        format_broken = any(text.startswith("EXR") for text in broken)
        self._chips["format"].set_value(job.image_format.upper(), "error" if format_broken else "")
        tone, text = self._status_of(job, len(frames), issues)
        if self._testing:
            tone, text = "running", "making a test frame…"
        metrics = self._status.fontMetrics()
        self._status.setText(metrics.elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight, self.STATUS_WIDTH))
        self._status.setToolTip(text if text == job.message else (text + chr(10) + job.message).strip())
        if self._status.property("tone") != tone:
            self._status.setProperty("tone", tone)  # batch.qss: QLabel#batchJobStatus[tone=...]
            repolish(self._status)
        count = len(frames)
        done = len(job.done) if job.state in (RUNNING, DONE) else len(job.existing_frames()) if job.probe else 0
        self._bar_fraction = min(done / count, 1.0) if count else 0.0
        self._count.setText(f"{min(done, count)}/{count}" if count else "")
        self._bar.setVisible(bool(count))
        fraction = self._bar_fraction if job.state == RUNNING else None
        if fraction != self._fraction:
            self._fraction = fraction
        self.update()
        picture = job.last_file or job.thumbnail
        if picture != self._picture_file:
            self._show_picture(picture)
        self._fill_details(job, issues)

    @staticmethod
    def _status_of(job: BatchJob, count: int, issues: list) -> tuple:
        if not job.enabled:
            return "", "off"
        if job.state == CHECKING:
            return "running", "reading the scene…"
        if job.state == RUNNING:
            return "running", job.message or "rendering"
        if job.state == DONE:
            return "done", "done  ·  " + job.message
        if job.state == FAILED:
            return "error", job.message or "failed"
        if job.state == CANCELLED:
            return "", "cancelled"
        if not job.probe:
            return "", "waiting to be read"
        tone = worst(issues)
        if tone == ERROR:
            errors = sum(1 for issue in issues if issue.level == ERROR)
            return "error", f"{errors} problem{'s' if errors != 1 else ''} — won’t render"
        if tone == WARNING:
            warnings = sum(1 for issue in issues if issue.level == WARNING)
            return "warning", f"ready  ·  {warnings} to look at"
        return "done", "ready"

    def _fill_details(self, job: BatchJob, issues: list) -> None:
        while self._issues.count():
            widget = self._issues.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        if not job.probe:
            self._issue("", "The scene is read in Maya before it renders." if job.state != CHECKING else
                        "Reading the scene in Maya…")
        for issue in issues:
            label = self._issue(issue.level, f"{SYMBOLS[issue.level]}  {issue.text}")
            if issue.detail:
                label.setToolTip(issue.detail)
        self._folder.setText(str(job.output_folder()))
        self._folder.setToolTip(str(job.output_folder()))
        self._search.setText(job.search_folder or "not looked for elsewhere — pick a folder to search")
        self._search.setToolTip(job.search_folder or "Missing textures and Alembic caches are looked for BY FILE "
                                                     "NAME in this folder (3 levels down) — for the render only")
        self._search_clear.setVisible(bool(job.search_folder))
        self._video.blockSignals(True)
        self._video.set_checked_immediate(job.make_video)
        self._video.blockSignals(False)
        editable = job.state not in (RUNNING, CHECKING)
        for widget in list(self._chips.values()) + [self._folder_button, self._video, self._search_button,
                                                    self._search_clear]:
            widget.setEnabled(editable)

    def _issue(self, level: str, text: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("batchIssue")
        label.setWordWrap(True)
        label.setProperty("level", level)
        repolish(label)
        self._issues.addWidget(label)
        return label

    def _show_picture(self, file: str) -> None:
        self._picture_file = file
        pixmap = qt.QtGui.QPixmap(file) if file and Path(file).is_file() else qt.QtGui.QPixmap()
        if pixmap.isNull():
            self._picture.setPixmap(qt.QtGui.QPixmap())
            self._picture.setText(".ma" if self._job.scene.lower().endswith(".ma") else ".mb")
            return
        ratio = self.devicePixelRatioF()
        scaled = pixmap.scaled(self.PICTURE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               qt.QtCore.Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self._picture.setPixmap(scaled)

    # --- changing the job's settings ---------------------------------------------------------------

    def _menu(self) -> qt.QtWidgets.QMenu:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._chip_menu = menu  # for tests; the menu deletes itself on close
        return menu

    def _choices(self, chip: _Chip, choices: list, current, apply, extra=()) -> None:
        """A menu under `chip`: (title, value) choices, the current one ticked; `extra`: (title, callback)
        actions under a line."""
        menu = self._menu()
        for title, value in choices:
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.triggered.connect(lambda _checked=False, value=value: apply(value))
        if extra:
            menu.addSeparator()
            for title, callback in extra:
                menu.addAction(title).triggered.connect(callback)
        menu.popup(chip.mapToGlobal(qt.QtCore.QPoint(0, chip.height() + 2)))

    def _on_chip(self, key: str) -> None:
        job, chip = self._job, self._chips[key]
        self.picked.emit(self.job_id)
        if key == "frames":
            self._edit_frames(chip)
        elif key == "renderer":
            scene = choose_renderer(BatchJob(scene=job.scene, probe=job.probe)) if job.probe else ""
            choices = [(f"Auto — as the scene ({RENDERER_TITLES[scene]})" if scene else "Auto — as the scene", AUTO)]
            choices += [(RENDERER_TITLES[name] + (" (Hardware 2.0 — like the viewport, no licence)" if name == HW2
                                                  else ""), name) for name in (ARNOLD, HW2, REDSHIFT)]
            self._choices(chip, choices, job.renderer, lambda value: self._set("renderer", value))
        elif key == "camera":
            cameras = [camera["name"] for camera in job.probe.get("cameras") or []]
            own = [name for name in cameras if name not in STARTUP_CAMERAS]
            choices = [("Auto — the scene's renderable one", "")] + [(name, name) for name in own] + \
                      [(name, name) for name in cameras if name in STARTUP_CAMERAS]
            extra = [(f"Render each of its {len(own)} cameras — a job each",
                      lambda: self.split.emit(self.job_id, "camera"))] if len(own) > 1 else []
            self._choices(chip, choices, job.camera, lambda value: self._set("camera", value), extra)
        elif key == "size":
            self._choices(chip, [(f"{size} of the scene's", size) for size in SIZES], job.size,
                          lambda value: self._set("size", value))
        elif key == "mode":
            self._choices(chip, [("With Maya — clean Arnold frames, Maya opens minimized", MODE_WINDOW),
                                 ("No window — faster start, Arnold watermarks without a batch licence",
                                  MODE_HEADLESS)], job.mode, lambda value: self._set("mode", value))
        elif key == "environment":
            choices = [("No environment — Maya as installed", "")] + [(name, name) for name in self._environments]
            self._choices(chip, choices, job.environment, lambda value: self._set("environment", value))
        elif key == "layer":
            layers = job.probe.get("render_layers") or []
            choices = [("As saved — the layer the scene was saved on", "")] + [(name, name) for name in layers]
            extra = [(f"Render each of its {len(layers)} layers — a job each",
                      lambda: self.split.emit(self.job_id, "layer"))] if len(layers) > 1 else []
            self._choices(chip, choices, job.layer, lambda value: self._set("layer", value), extra)
        elif key == "format":
            self._choices(chip, [("PNG — 8 bits, for watching and a video", "png"),
                                 ("JPG — small", "jpg"),
                                 ("EXR — float, for compositing (no window only)", "exr")],
                          job.image_format, lambda value: self._set("image_format", value))
        elif key == "maya":
            choices = [("Auto — the version the scene was saved with", "")] + \
                      [(f"Maya {year}", year) for year in self._installed]
            self._choices(chip, choices, job.maya, self._set_maya)

    def _edit_frames(self, chip: _Chip) -> None:
        """A field right under the chip: Enter takes it, Esc / a click elsewhere leaves it."""
        menu = self._menu()
        field = qt.QtWidgets.QLineEdit(self._job.frames)
        playback = self._job.probe.get("playback")
        field.setPlaceholderText(f"the scene's {format_frames(range(int(playback[0]), int(playback[1]) + 1))}"
                                 if playback else "1-120")
        field.setMinimumWidth(220)
        note = qt.QtWidgets.QLabel("1-120  ·  1, 20, 78  ·  1-100x5  ·  empty = the scene's")
        note.setObjectName("batchHint")
        holder = qt.QtWidgets.QWidget()
        box = qt.QtWidgets.QVBoxLayout(holder)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)
        box.addWidget(field)
        box.addWidget(note)
        action = qt.QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)

        def take() -> None:
            text = field.text().strip()
            if text:
                try:
                    parse_frames(text)
                except FramesError as error:
                    note.setText(str(error))
                    note.setProperty("state", "error")
                    repolish(note)
                    return
            self._set("frames", text)
            menu.close()

        field.returnPressed.connect(take)
        menu.popup(chip.mapToGlobal(qt.QtCore.QPoint(0, chip.height() + 2)))
        field.setFocus()
        field.selectAll()

    def _set(self, key: str, value) -> None:
        if getattr(self._job, key) == value:
            return
        setattr(self._job, key, value)
        self.update_job(self._job)
        self.changed.emit(self.job_id)

    def _set_maya(self, year: str) -> None:
        if year != self._job.maya:
            self._job.maya = year
            self.reread.emit(self.job_id)  # another Maya may read the scene differently (plug-ins, renderers)

    def _on_enabled(self, checked: bool) -> None:
        self._set("enabled", bool(checked))

    def _on_video(self, checked: bool) -> None:
        self._set("make_video", bool(checked))

    def _on_pick_search(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Where missing files may be",
                                                               self._job.search_folder or str(Path(self._job.scene).parent))
        if folder:
            self._set_search(str(Path(folder)))

    def _set_search(self, folder: str) -> None:
        if folder != self._job.search_folder:
            self._job.search_folder = folder
            self.reread.emit(self.job_id)  # the check looks again, with that folder

    def _on_pick_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder for the frames",
                                                               str(self._job.output_folder()))
        if folder:
            self._set("folder", str(Path(folder)))

    # --- the row itself ------------------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.picked.emit(self.job_id)
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press is not None and (event.position().toPoint() - self._press).manhattanLength() \
                >= qt.QtWidgets.QApplication.startDragDistance():
            self._press = None
            data = qt.QtCore.QMimeData()
            data.setData(DRAG_MIME, self.job_id.encode())
            drag = qt.QtGui.QDrag(self)
            drag.setMimeData(data)
            drag.setPixmap(self.grab().scaledToWidth(min(self.width(), 360),
                                                     qt.QtCore.Qt.TransformationMode.SmoothTransformation))
            drag.setHotSpot(qt.QtCore.QPoint(20, 12))
            drag.exec(qt.QtCore.Qt.DropAction.MoveAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_open()

    def contextMenuEvent(self, event) -> None:
        self.picked.emit(self.job_id)
        self.menu_requested.emit(self.job_id, event.globalPos())

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        if self._selected:
            painter.fillRect(self.rect(), self._selected_color)
        elif self.underMouse():
            painter.fillRect(self.rect(), self._hover_color)
        if self._fraction is not None:
            painter.fillRect(qt.QtCore.QRectF(0, 0, self.width() * self._fraction, self.height()), self._progress_color)
        if self._bar.isVisible():
            rect = qt.QtCore.QRectF(self._bar.geometry())
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._bar_track_color)
            painter.drawRoundedRect(rect, 2.5, 2.5)
            if self._bar_fraction > 0:
                painter.setBrush(self._bar_color)
                painter.drawRoundedRect(qt.QtCore.QRectF(rect.x(), rect.y(), rect.width() * self._bar_fraction,
                                                         rect.height()), 2.5, 2.5)
        painter.end()
        super().paintEvent(event)
