# tools/desktop/media/ffmpeg_bar.py
import threading

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import FfmpegInstaller, FfmpegLocator, FfmpegTools, MediaError
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import make_rounded_popup, repolish
from msl_tools.msl.ui.widgets.atoms.progress.base_progress_bar import BaseProgressBar
from msl_tools.msl.ui.workers.result_worker import run_in_background


def link_button(text: str, tooltip: str = "") -> qt.QtWidgets.QPushButton:
    """A quiet accent text button (media.qss: QPushButton#mediaLink)."""
    button = qt.QtWidgets.QPushButton(text)
    button.setObjectName("mediaLink")
    button.setFlat(True)
    button.setToolTip(tooltip)
    button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
    return button


class FfmpegBar(qt.QtWidgets.QFrame):
    """The Media tool's line about ffmpeg, the program that does the work:

        looking   "Looking for ffmpeg…"
        ready     the bar itself is hidden; status_button() — a quiet
                  "ffmpeg 8.0" link the page puts into its header — is
                  shown instead (its menu: use another copy, download the
                  managed one, show its folder)
        missing   a notice with "Download ffmpeg (101 MB)" and "I already have it…"
        working   the download's progress, with Cancel

    Where ffmpeg is looked for: the path in `settings["ffmpeg_path"]`, the
    managed copy, PATH (core/media/ffmpeg.py). locate() and the download run
    on worker threads; nothing is looked up in the constructor.

    Signals:
        tools_changed(object) — the FfmpegTools now in use, or None.
    """

    LOOKING, READY, MISSING, WORKING = "looking", "ready", "missing", "working"

    tools_changed = qt.QtCore.Signal(object)
    _download_progressed = qt.QtCore.Signal(str, float, float)  # from the download thread

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("mediaFfmpeg")
        self._settings = settings
        self._tools: FfmpegTools | None = None
        self._workers: list = []
        self._cancel = threading.Event()
        self._installer = FfmpegInstaller()

        self._label = qt.QtWidgets.QLabel()
        self._label.setObjectName("mediaFfmpegText")
        self._label.setWordWrap(True)
        self._progress = BaseProgressBar()
        self._progress.setFixedWidth(160)
        megabytes = self._installer.download_size() / 1024 ** 2
        self._download_button = qt.QtWidgets.QPushButton(
            f"Download ffmpeg ({megabytes:.0f} MB)" if megabytes else "Download ffmpeg")
        self._download_button.setProperty("primary", True)
        self._download_button.setToolTip(f"Downloads ffmpeg {self._installer.version} once and keeps it with "
                                         f"MSL Tools — nothing else on this computer changes")
        self._have_button = qt.QtWidgets.QPushButton("I already have it…")
        self._have_button.setToolTip("Point at the folder ffmpeg is in (the one with ffmpeg.exe and ffprobe.exe)")
        self._cancel_button = qt.QtWidgets.QPushButton("Cancel")
        self._status_button = link_button("", "ffmpeg — the program that does the work. Click for more")

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._progress)
        layout.addWidget(self._download_button)
        layout.addWidget(self._have_button)
        layout.addWidget(self._cancel_button)

        self._download_button.clicked.connect(self.download)
        self._have_button.clicked.connect(self.choose_folder)
        self._cancel_button.clicked.connect(self._cancel.set)
        self._status_button.clicked.connect(self._on_menu)
        self._download_progressed.connect(self._on_download_progress)
        self._set_state(self.LOOKING)

    def tools(self) -> FfmpegTools | None:
        return self._tools

    def status_button(self) -> qt.QtWidgets.QPushButton:
        """The "ffmpeg 8.0" link, visible while ffmpeg is there — for the page's header."""
        return self._status_button

    # --- finding ffmpeg ----------------------------------------------------------------

    def locate(self) -> None:
        """Looks for ffmpeg (on a worker thread); tools_changed follows."""
        self._set_state(self.LOOKING)
        configured = str(self._settings.get("ffmpeg_path", "") or "")
        self._run(lambda: FfmpegLocator(configured=configured).find(), self._on_located)

    def _on_located(self, tools) -> None:
        self._tools = tools
        self._set_state(self.READY if tools is not None else self.MISSING)
        self.tools_changed.emit(tools)

    def choose_folder(self) -> None:
        """Asks for the folder of a copy the user already has."""
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder ffmpeg is in")
        if folder:
            self.use_folder(folder)

    def use_folder(self, folder: str) -> None:
        self._set_state(self.LOOKING)

        def done(tools) -> None:
            if tools is None:
                self._on_located(self._tools)
                self._label.setText(f"No ffmpeg in “{folder}” — the folder needs ffmpeg.exe and ffprobe.exe "
                                    f"(usually its “bin” folder).")
                self._label.show()
                return
            self._settings["ffmpeg_path"] = folder
            self._on_located(tools)

        self._run(lambda: FfmpegLocator.inspect(folder, FfmpegLocator.SETTINGS), done)

    # --- downloading it ------------------------------------------------------------------

    def download(self) -> None:
        """Downloads the managed copy; the bar shows the progress."""
        self._cancel.clear()
        self._set_state(self.WORKING)
        self._label.setText(f"Downloading ffmpeg {self._installer.version}…")
        self._progress.set_indeterminate(True)

        def work():
            return self._installer.install(
                progress=lambda stage, done, total: self._download_progressed.emit(stage, float(done), float(total)),
                should_cancel=self._cancel.is_set)

        def done(tools) -> None:
            self._progress.set_indeterminate(False)
            self._settings["ffmpeg_path"] = ""  # the managed copy is found by itself
            self._on_located(tools)

        def failed(error) -> None:
            self._progress.set_indeterminate(False)
            self._on_located(self._tools)
            if not self._cancel.is_set():
                self._label.setText(str(error) if isinstance(error, MediaError) else f"ffmpeg wasn’t installed: {error}")
                self._label.show()

        self._run(work, done, failed)

    def _on_download_progress(self, stage: str, done: float, total: float) -> None:
        if stage == "download":
            megabytes = 1024 ** 2
            self._label.setText(f"Downloading ffmpeg {self._installer.version}… {done / megabytes:.0f}"
                                + (f" of {total / megabytes:.0f} MB" if total else " MB"))
            if total:
                self._progress.set_indeterminate(False)
                self._progress.set_progress(int(done / total * 100))
        else:
            self._label.setText("Unpacking ffmpeg…")
            self._progress.set_indeterminate(True)

    # --- the menu of a found ffmpeg --------------------------------------------------------

    def _on_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if self._tools is not None:
            where = menu.addAction(str(self._tools.ffmpeg.parent))
            where.setEnabled(False)
            menu.addAction("Show its folder").triggered.connect(
                lambda: ProcessLauncher.open_file_explorer(self._tools.ffmpeg))
            menu.addSeparator()
        menu.addAction("Use another copy…").triggered.connect(self.choose_folder)
        if not self._installer.is_downloaded():  # files only: installed() would run ffmpeg on the UI thread
            megabytes = self._installer.download_size() / 1024 ** 2
            menu.addAction(f"Download ffmpeg {self._installer.version} ({megabytes:.0f} MB)").triggered.connect(self.download)
        self._menu = menu  # for tests; the menu deletes itself on close
        menu.popup(self._status_button.mapToGlobal(qt.QtCore.QPoint(0, self._status_button.height())))

    # --- looks ------------------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._state = state
        self.setProperty("state", state)  # media.qss: QFrame#mediaFfmpeg[state=...]
        repolish(self)
        ready, missing, working = state == self.READY, state == self.MISSING, state == self.WORKING
        # With ffmpeg there, the bar has nothing to say: only the header's link stays.
        if ready:
            self.hide()
        elif self.parent() is not None:  # never show() a widget that has no parent yet
            self.show()
        self._label.setVisible(not ready)
        self._progress.setVisible(working)
        self._download_button.setVisible(missing)
        self._have_button.setVisible(missing)
        self._cancel_button.setVisible(working)
        self._status_button.setVisible(ready)
        if state == self.LOOKING:
            self._label.setText("Looking for ffmpeg…")
        elif missing:
            self._label.setText("Media works through ffmpeg, a free program that isn’t on this computer yet "
                                "(or wasn’t found).")
        elif ready:
            source = {FfmpegLocator.MANAGED: "kept with MSL Tools", FfmpegLocator.PATH: "found on this computer",
                      FfmpegLocator.SETTINGS: "the copy you pointed at"}.get(self._tools.source, "")
            self._status_button.setText(f"ffmpeg {self._tools.short_version}")
            self._status_button.setToolTip(f"ffmpeg {self._tools.version}" + chr(10) + f"{self._tools.ffmpeg}"
                                           + (chr(10) + source if source else "") + chr(10) + "Click for more")

    def state(self) -> str:
        return self._state

    def _run(self, target, on_done, on_failed=None) -> None:
        run_in_background(target, on_done, on_failed or (lambda error: on_done(None)), keep=self._workers, parent=self)
