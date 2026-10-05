# tools/desktop/batch/job_details.py
"""Under the Batch queue: the picked job's check (what the scene read says) and its settings."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch.checks import check, choose_renderer
from msl_tools.msl.core.batch.frames import FramesError, format_frames
from msl_tools.msl.core.batch.job import (ARNOLD, AUTO, HW2, MODE_HEADLESS, MODE_WINDOW, REDSHIFT, RENDERER_TITLES,
                                          RUNNING, SIZES, BatchJob)
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl

MODES = {"With Maya": MODE_WINDOW, "No window": MODE_HEADLESS}
RENDERERS = [AUTO, ARNOLD, HW2, REDSHIFT]
SYMBOLS = {"error": "✕", "warning": "!", "ok": "✓"}


def card(title: str, icon: str) -> tuple:
    """(a card frame, the layout for its body) — the look of the page's cards."""
    frame = qt.QtWidgets.QFrame()
    frame.setObjectName("batchCard")
    heading = qt.QtWidgets.QHBoxLayout()
    heading.setContentsMargins(0, 0, 0, 0)
    heading.setSpacing(8)
    symbol = TintedIcon(UiResources().iconManager.get_icon(icon, sub_folder="actions"), 16)
    symbol.setObjectName("batchCardIcon")
    label = qt.QtWidgets.QLabel(title.upper())
    label.setObjectName("batchCardTitle")
    heading.addWidget(symbol)
    heading.addWidget(label, 1)
    layout = qt.QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(12, 9, 12, 10)
    layout.setSpacing(6)
    layout.addLayout(heading)
    return frame, layout, label


class JobDetails(qt.QtWidgets.QWidget):
    """The picked job's check and settings. A change of a setting goes straight into the job
    (`changed(job_id)` follows; the page saves and refreshes). A different Maya means the scene is
    read again (`reread(job_id)`). Nothing is editable while the job renders.

    Signals:
        changed(str), reread(str)
    """

    changed = qt.QtCore.Signal(str)
    reread = qt.QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._job: BatchJob | None = None
        self._filling = False
        self._installed: list = []

        self._check_card, check_layout, self._check_title = card("Check", "report")
        self._issues = qt.QtWidgets.QVBoxLayout()
        self._issues.setSpacing(3)
        check_layout.addLayout(self._issues)
        check_layout.addStretch(1)

        self._settings_card, settings_layout, self._settings_title = card("Settings", "edit")
        icons = UiResources().iconManager
        self._maya = BaseComboBox(["Auto"], "Auto")
        self._maya.setToolTip("The Maya that renders it — Auto: the version the scene was saved with, if it is "
                              "installed")
        self._renderer = BaseComboBox([RENDERER_TITLES[key] for key in RENDERERS], "Auto")
        self._renderer.setToolTip("Auto: what the scene is set up for.\nViewport: Hardware 2.0 — a picture like the "
                                  "viewport's, fast, no licence.")
        self._camera = BaseComboBox(["Auto"], "Auto")
        self._frames = qt.QtWidgets.QLineEdit()
        self._frames.setToolTip("1-120  ·  1, 20, 78, 300  ·  1-100x5 (every 5th)  ·  empty: the scene's range")
        self._size = SegmentedControl(list(SIZES), "100%")
        self._size.setToolTip("The scene's resolution, or half / a quarter of it — for a quick look")
        self._mode = SegmentedControl(list(MODES), "With Maya")
        self._mode.setToolTip("With Maya: Maya opens minimized, renders, closes — Arnold without watermarks.\n"
                              "No window: starts faster; Arnold marks the frames unless there is a batch licence.")
        self._folder = qt.QtWidgets.QLineEdit()
        self._browse = IconPushButton(icons.get_icon("browse", sub_folder="actions"), "Pick the folder for the frames",
                                      fallback_text="…")
        self._browse.setFixedSize(26, 22)
        self._video = BaseCheckbox("Then make a video of the frames")
        form = qt.QtWidgets.QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        folder_row = qt.QtWidgets.QHBoxLayout()
        folder_row.setSpacing(6)
        folder_row.addWidget(self._folder, 1)
        folder_row.addWidget(self._browse)
        rows = [("Maya", self._maya), ("Renderer", self._renderer), ("Camera", self._camera),
                ("Frames", self._frames), ("Size", self._size), ("Maya runs", self._mode), ("Frames go", folder_row),
                ("", self._video)]
        for index, (caption, control) in enumerate(rows):
            label = qt.QtWidgets.QLabel(caption)
            label.setObjectName("batchCaption")
            form.addWidget(label, index, 0)
            if isinstance(control, qt.QtWidgets.QLayout):
                form.addLayout(control, index, 1)
            elif isinstance(control, SegmentedControl):
                line = qt.QtWidgets.QHBoxLayout()
                line.addWidget(control)
                line.addStretch(1)
                form.addLayout(line, index, 1)
            else:
                form.addWidget(control, index, 1)
        settings_layout.addLayout(form)

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._check_card, 1)
        layout.addWidget(self._settings_card, 1)

        self._maya.currentIndexChanged.connect(self._on_maya)
        self._renderer.currentIndexChanged.connect(lambda _index: self._set("renderer", RENDERERS[self._renderer.currentIndex()]))
        self._camera.currentIndexChanged.connect(
            lambda _index: self._set("camera", "" if self._camera.currentIndex() == 0 else self._camera.currentText()))
        self._frames.editingFinished.connect(lambda: self._set("frames", self._frames.text().strip()))
        self._size.current_changed.connect(lambda size: self._set("size", size))
        self._mode.current_changed.connect(lambda mode: self._set("mode", MODES[mode]))
        self._folder.editingFinished.connect(lambda: self._set("folder", self._folder.text().strip()))
        self._browse.clicked.connect(self._on_browse)
        self._video.toggled.connect(lambda checked: self._set("make_video", bool(checked)))
        self.show_job(None)

    def set_installed(self, years: list) -> None:
        self._installed = sorted(years)

    def job(self) -> BatchJob | None:
        return self._job

    def show_job(self, job: BatchJob | None, auto_maya: str = "") -> None:
        """Shows `job` (None: the hint that a job is to be picked)."""
        self._job = job
        self._filling = True
        try:
            self._fill(job, auto_maya)
        finally:
            self._filling = False

    def _fill(self, job: BatchJob | None, auto_maya: str) -> None:
        while self._issues.count():
            widget = self._issues.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._settings_card.setEnabled(job is not None and job.state != RUNNING)
        if job is None:
            self._check_title.setText("CHECK")
            self._settings_title.setText("SETTINGS")
            self._issue("", "Pick a scene in the list to see its check and settings.")
            return
        self._check_title.setText(f"CHECK  ·  {job.name}")
        self._settings_title.setText(f"SETTINGS  ·  {job.name}")
        if not job.probe:
            self._issue("", "Reading the scene in Maya…" if job.state == "checking" else
                        job.message or "The scene is read before it renders.")
        for issue in check(job):
            label = self._issue(issue.level, f"{SYMBOLS[issue.level]}  {issue.text}")
            if issue.detail:
                label.setToolTip(issue.detail)
        self._maya.clear()
        self._maya.addItems([f"Auto ({auto_maya})" if auto_maya else "Auto"] + self._installed)
        self._maya.setCurrentIndex(self._installed.index(job.maya) + 1 if job.maya in self._installed else 0)
        scene_renderer = choose_renderer(job) if job.probe else ""
        self._renderer.setItemText(0, f"Auto ({RENDERER_TITLES[scene_renderer]})" if scene_renderer else "Auto")
        self._renderer.setCurrentIndex(RENDERERS.index(job.renderer) if job.renderer in RENDERERS else 0)
        cameras = [camera["name"] for camera in job.probe.get("cameras") or []]
        cameras = [name for name in cameras if name not in ("persp", "top", "front", "side")] + \
                  [name for name in cameras if name in ("persp", "top", "front", "side")]
        self._camera.clear()
        auto = job.camera_name() if not job.camera else ""
        self._camera.addItems([f"Auto ({auto})" if auto else "Auto"] + cameras)
        self._camera.setCurrentIndex(cameras.index(job.camera) + 1 if job.camera in cameras else 0)
        self._frames.setText(job.frames)
        playback = job.probe.get("playback")
        self._frames.setPlaceholderText(f"the scene's {format_frames(range(int(playback[0]), int(playback[1]) + 1))}"
                                        if playback else "the scene's range")
        self._size.set_current(job.size, animate=False)
        self._mode.set_current(next(key for key, value in MODES.items() if value == job.mode), animate=False)
        self._mode.setEnabled(scene_renderer in ("", ARNOLD) or job.renderer == ARNOLD)
        self._folder.setText(job.folder)
        self._folder.setPlaceholderText(str(job.output_folder()))
        self._video.set_checked_immediate(job.make_video)

    def _issue(self, level: str, text: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("batchIssue")
        label.setWordWrap(True)
        label.setProperty("level", level)
        repolish(label)
        self._issues.addWidget(label)
        return label

    def _set(self, key: str, value) -> None:
        if self._filling or self._job is None or getattr(self._job, key) == value:
            return
        setattr(self._job, key, value)
        self.changed.emit(self._job.id)

    def _on_maya(self, index: int) -> None:
        if self._filling or self._job is None:
            return
        year = self._installed[index - 1] if index > 0 else ""
        if year != self._job.maya:
            self._job.maya = year
            self.reread.emit(self._job.id)  # another Maya may read the scene differently (plug-ins, renderers)

    def _on_browse(self) -> None:
        if self._job is None:
            return
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder for the frames",
                                                               str(self._job.output_folder()))
        if folder:
            self._folder.setText(str(Path(folder)))
            self._set("folder", str(Path(folder)))

    def frames_error(self) -> str:
        try:
            if self._job is not None:
                self._job.frame_list()
        except FramesError as error:
            return str(error)
        return ""
