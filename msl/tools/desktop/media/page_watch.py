# tools/desktop/media/page_watch.py
"""The Media page's watched render folder: image sequences that finish appearing in it become
videos by themselves, with To video's settings as they are on screen."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import MediaError
from msl_tools.msl.core.media.watch import FolderWatch
from msl_tools.msl.tools.desktop.media.ffmpeg_bar import link_button
from msl_tools.msl.tools.desktop.media.source import load_source
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.ui.workers.result_worker import run_in_background


class _WatchMixin:
    """MediaPage's folder watch (methods of MediaPage; `_build_watch_bar()` makes the widgets).

    Every WATCH_EVERY_MS the folder is looked at on a worker (core/media/watch.py FolderWatch);
    a sequence that grew and then stayed quiet is read (load_source) and handed to the "sequence"
    panel — To video — whose settings, presets and the page's name template decide the video.
    It goes into the queue like a job started by hand. A sequence that grows again (a re-render)
    replaces the video the watch made of it.

    The watch is not remembered across restarts (a forgotten watch would quietly fill a disk);
    the last folder is (`settings.watch_folder`), for the menu.
    """

    WATCH_EVERY_MS = 3000
    WATCH_ACTION = "sequence"

    def _build_watch_bar(self) -> None:
        self._watch: FolderWatch | None = None
        self._watch_busy = False
        self._watch_made = 0
        self._watch_outputs: dict = {}      # sequence key -> the video the watch made of it
        self._watch_workers: list = []
        self._watch_bar = qt.QtWidgets.QFrame()
        self._watch_bar.setObjectName("mediaWatch")
        icon = TintedIcon(UiResources().iconManager.get_icon("folder_watch", sub_folder="actions"), 16)
        icon.setObjectName("mediaCardIcon")
        self._watch_text = qt.QtWidgets.QLabel()
        self._watch_text.setObjectName("mediaWatchText")
        self._watch_text.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._watch_stop = link_button("Stop", "Stop watching the folder (the videos made stay)")
        bar = qt.QtWidgets.QHBoxLayout(self._watch_bar)
        bar.setContentsMargins(12, 6, 10, 6)
        bar.setSpacing(8)
        bar.addWidget(icon)
        bar.addWidget(self._watch_text, 1)
        bar.addWidget(self._watch_stop)
        self._watch_bar.hide()
        self._watch_timer = qt.QtCore.QTimer(self)
        self._watch_timer.setInterval(self.WATCH_EVERY_MS)
        self._watch_timer.timeout.connect(self._watch_scan)
        self._watch_stop.clicked.connect(self.stop_watching)

    def _on_choose_watch_folder(self) -> None:
        start = str(self._settings.get("watch_folder", "") or "")
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder renders are written to", start)
        if folder:
            self.watch_folder(folder)

    def watch_folder(self, folder) -> None:
        """Starts watching `folder` (and its sub-folders one level down). What is in it now is the
        starting point: only frames that appear from now on make videos."""
        folder = Path(folder)
        if not folder.is_dir():
            self._say(f"There is no folder {folder}", "error")
            return
        self._watch = FolderWatch(folder)
        self._watch_made, self._watch_outputs = 0, {}
        self._settings["watch_folder"] = str(folder)
        self._watch_bar.show()
        self._refresh_watch_text()
        self._watch_scan()  # takes stock of what is there
        self._watch_timer.start()

    def stop_watching(self) -> None:
        self._watch_timer.stop()
        self._watch = None
        self._watch_bar.hide()

    def watching(self):
        """The folder being watched (None = none)."""
        return self._watch.folder if self._watch is not None else None

    def _refresh_watch_text(self, waiting: int = 0) -> None:
        if self._watch is None:
            return
        made = f"  ·  {self._watch_made} made" if self._watch_made else ""
        coming = f"  ·  {waiting} being written" if waiting else ""
        self._watch_text.setText(f"Watching {self._watch.folder.name}{coming}{made}")
        self._watch_text.setToolTip(f"{self._watch.folder}" + chr(10)
                                    + "New image sequences become videos with To video’s settings once their frames "
                                      "stop coming (sub-folders one level down too).")

    def _watch_scan(self) -> None:
        watch = self._watch
        if watch is None or self._watch_busy:
            return
        self._watch_busy = True

        def done(ready) -> None:
            self._watch_busy = False
            if watch is not self._watch:
                return  # stopped, or another folder, meanwhile
            self._refresh_watch_text(watch.waiting() - len(ready))
            for sequence in ready:
                watch.mark_made(sequence)   # one video per change, even if reading it fails
                self._watch_load(sequence)

        def failed(_error) -> None:
            self._watch_busy = False

        run_in_background(watch.scan, done, failed, keep=self._watch_workers, parent=self)

    def _watch_load(self, sequence) -> None:
        tools = self._ffmpeg.tools()
        if tools is None:
            self._say(f"{sequence.prefix or sequence.folder.name}: no video — ffmpeg isn’t available.", "error")
            return

        def done(source) -> None:
            if self._watch is not None:
                self._watch_queue(source)

        def failed(error) -> None:
            self._say(f"{sequence.folder.name}: {error}", "error")

        run_in_background(lambda: load_source(tools, sequence.folder, chosen=sequence), done, failed,
                          keep=self._watch_workers, parent=self)

    def _watch_queue(self, source) -> None:
        panel = self._panels.get(self.WATCH_ACTION)
        if panel is None:
            return
        sequence = source.sequence
        key = (str(sequence.folder), sequence.prefix, sequence.suffix)
        earlier = self._watch_outputs.get(key)
        if earlier is not None and earlier not in self._queue.outputs():
            output = earlier  # a re-render replaces the video the watch made of it
        else:  # the first one — or the earlier video is still being made: one of its own
            output = panel.output_for(source, self._folder() or None, self._queue.outputs(), self._name_template())
        try:
            jobs = [panel.job(source, output, use_sound=False)]
        except MediaError as error:
            self._say(f"{sequence.folder.name}: {error}", "error")
            return
        for job in jobs:
            self._queue.add(job, self._source_size(source),
                            recipe={"action": panel.KEY, "settings": panel.settings(), "sources": [str(source.path)]})
        self._watch_outputs[key] = output
        self._watch_made += 1
        self._refresh_watch_text()
        self._say(f"New frames in {sequence.folder.name}: {output.name} is on its way.")
