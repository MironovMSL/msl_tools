# tools/desktop/batch/job_row.py
"""One scene of the Batch queue as a row."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.batch.checks import ERROR, WARNING, check, choose_renderer, worst
from msl_tools.msl.core.batch.frames import FramesError
from msl_tools.msl.core.batch.job import (CANCELLED, CHECKING, DONE, FAILED, MODE_WINDOW, RENDERER_TITLES,
                                          RUNNING, BatchJob)
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.labels.elided_label import ElidedLabel


class JobRow(qt.QtWidgets.QFrame):
    """A job: on / off, a picture (its last frame once there is one), the scene's name, camera ·
    frames · size, the renderer and how Maya runs it, where it stands. A click picks it (its check and
    settings show under the list); while it renders the row fills from the left as far as it is.

    Signals:
        picked(str), toggled(str, bool), menu_requested(str, QPoint) — for the job's id.
    """

    PICTURE = qt.QtCore.QSize(64, 36)
    STATUS_WIDTH = 170

    progressColor = color_property("_progress_color", "update")
    selectedColor = color_property("_selected_color", "update")
    hoverColor = color_property("_hover_color", "update")

    picked = qt.QtCore.Signal(str)
    toggled = qt.QtCore.Signal(str, bool)
    menu_requested = qt.QtCore.Signal(str, object)

    def __init__(self, job: BatchJob, parent=None):
        super().__init__(parent)
        self.setObjectName("batchJob")
        self.job_id = job.id
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._progress_color = qt.QtGui.QColor(fallback.accent)
        self._progress_color.setAlpha(40)
        self._selected_color = qt.QtGui.QColor(fallback.accent)
        self._selected_color.setAlpha(22)
        self._hover_color = qt.QtGui.QColor(0, 0, 0, 0)
        self._fraction: float | None = None
        self._selected = False
        self._picture_file = ""
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._enabled = BaseCheckbox("")
        self._enabled.setToolTip("On: the queue renders it  ·  off: passed by")
        self._enabled.toggled.connect(lambda checked: self.toggled.emit(self.job_id, bool(checked)))
        self._picture = qt.QtWidgets.QLabel()
        self._picture.setObjectName("batchPicture")
        self._picture.setFixedSize(self.PICTURE)
        self._picture.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._name = ElidedLabel()
        self._name.setObjectName("batchJobName")
        self._line = ElidedLabel()
        self._line.setObjectName("batchJobLine")
        self._renderer = qt.QtWidgets.QLabel()
        self._renderer.setObjectName("batchPill")
        self._mode = qt.QtWidgets.QLabel()
        self._mode.setObjectName("batchPill")
        self._status = qt.QtWidgets.QLabel()   # elided by hand (_set_status): a fixed column
        self._status.setObjectName("batchJobStatus")
        self._status.setFixedWidth(self.STATUS_WIDTH)
        self._more = GlyphButton("⋯", "More", size=qt.QtCore.QSize(24, 22))
        self._more.setObjectName("batchAction")
        self._more.set_icon(UiResources().iconManager.get_icon("more", sub_folder="actions"))
        self._more.clicked.connect(lambda: self.menu_requested.emit(
            self.job_id, self._more.mapToGlobal(qt.QtCore.QPoint(0, self._more.height()))))
        text = qt.QtWidgets.QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        text.addWidget(self._name)
        text.addWidget(self._line)
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(10)
        layout.addWidget(self._enabled)
        layout.addWidget(self._picture)
        layout.addLayout(text, 1)
        middle = qt.QtCore.Qt.AlignmentFlag.AlignVCenter
        layout.addWidget(self._renderer, 0, middle)
        layout.addWidget(self._mode, 0, middle)
        layout.addWidget(self._status, 0, middle)
        layout.addWidget(self._more, 0, middle)
        self.update_job(job)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def update_job(self, job: BatchJob) -> None:
        self._enabled.blockSignals(True)
        self._enabled.set_checked_immediate(job.enabled)
        self._enabled.blockSignals(False)
        self._name.setText(job.name)
        self._name.setToolTip(job.scene)
        try:
            count = len(job.frame_list())
        except FramesError:
            count = 0
        width, height = job.resolution() if job.probe else (0, 0)
        parts = [job.camera_name() or "camera ?", job.frames_text() + (f"  ({count})" if count > 1 else "")]
        if width:
            parts.append(f"{width}×{height}")
        self._line.setText("  ·  ".join(parts))
        renderer = choose_renderer(job) if job.probe else job.renderer
        self._renderer.setText(RENDERER_TITLES.get(renderer, renderer) + (" · auto" if job.renderer == "auto" else ""))
        self._mode.setText("with Maya" if job.mode == MODE_WINDOW and renderer == "arnold" else "no window")
        self._mode.setToolTip("Maya opens minimized and closes when done — Arnold renders without watermarks"
                              if job.mode == MODE_WINDOW else "Maya without a window — starts faster")
        tone, text = self._status_of(job, count)
        metrics = self._status.fontMetrics()
        self._status.setText(metrics.elidedText(text, qt.QtCore.Qt.TextElideMode.ElideRight, self.STATUS_WIDTH))
        self._status.setToolTip(text if text == job.message else (text + chr(10) + job.message).strip())
        if self._status.property("tone") != tone:
            self._status.setProperty("tone", tone)  # batch.qss: QLabel#batchJobStatus[tone=...]
            repolish(self._status)
        fraction = min(len(job.done) / count, 1.0) if job.state == RUNNING and count else None
        if fraction != self._fraction:
            self._fraction = fraction
            self.update()
        if job.last_file != self._picture_file:
            self._show_picture(job.last_file)

    @staticmethod
    def _status_of(job: BatchJob, count: int) -> tuple:
        if not job.enabled:
            return "", "off"
        if job.state == CHECKING:
            return "running", "reading the scene…"
        if job.state == RUNNING:
            return "running", f"{len(job.done)} / {count}  ·  {job.message}"
        if job.state == DONE:
            return "done", "done  ·  " + job.message
        if job.state == FAILED:
            return "error", job.message or "failed"
        if job.state == CANCELLED:
            return "", "cancelled"
        if not job.probe:
            return "", "waiting to be read"
        issues = check(job)
        tone = worst(issues)
        if tone == ERROR:
            errors = sum(1 for issue in issues if issue.level == ERROR)
            return "error", f"{errors} problem{'s' if errors != 1 else ''} — won’t render"
        if tone == WARNING:
            warnings = sum(1 for issue in issues if issue.level == WARNING)
            return "warning", f"ready  ·  {warnings} to look at"
        there = len(job.existing_frames())
        return "", "ready" + (f"  ·  {there} already there" if there else "")

    def _show_picture(self, file: str) -> None:
        self._picture_file = file
        pixmap = qt.QtGui.QPixmap(file) if file and Path(file).is_file() else qt.QtGui.QPixmap()
        if pixmap.isNull():
            self._picture.setPixmap(qt.QtGui.QPixmap())
            self._picture.setText("scene")
            return
        ratio = self.devicePixelRatioF()
        scaled = pixmap.scaled(self.PICTURE * ratio, qt.QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               qt.QtCore.Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(ratio)
        self._picture.setPixmap(scaled)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.picked.emit(self.job_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        self.picked.emit(self.job_id)
        self.menu_requested.emit(self.job_id, event.globalPos())

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        if self._selected:
            painter.fillRect(self.rect(), self._selected_color)
        elif self.underMouse():
            painter.fillRect(self.rect(), self._hover_color)
        if self._fraction is not None:
            painter.fillRect(qt.QtCore.QRectF(0, 0, self.width() * self._fraction, self.height()), self._progress_color)
        painter.end()
        super().paintEvent(event)
