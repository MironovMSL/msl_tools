# tools/desktop/media/page_drops.py
"""How files reach the Media page: drops, paste, recent sources, "Send to"."""
import sys
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment.send_to import create_send_to, remove_send_to
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.desktop.media.source import AUDIO_SUFFIXES


class _DropsMixin:
    """How files reach MediaPage: drops, paste, the recent sources, set up again, Explorer's
    "Send to" (methods of MediaPage, moved as they were)."""

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
