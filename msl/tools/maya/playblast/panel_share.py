# tools/maya/playblast/panel_share.py
"""What a finished playblast goes on to: the hub's Media tool, a comparison
with the previous version, a light copy for a chat (the RECENT tiles' menu)."""
from pathlib import Path

from msl_tools.msl.tools.maya.playblast import naming
from msl_tools.msl.tools.maya.playblast.ending import RunEnding
from msl_tools.msl.tools.maya.playblast.recent import ACTION_COMPARE, ACTION_LIGHT, ACTION_MEDIA


class _ShareMixin:
    """PlayblastPanel's RECENT actions and the end of their side jobs (a mixin: the state it
    uses is made in PlayblastPanel.__init__; the jobs themselves run in RunEnding)."""

    def _on_recent_action(self, action: str, path: str) -> None:
        if action == ACTION_MEDIA:
            self._send_to_media(Path(path))
            return
        if self._tools is None:
            self._say("ffmpeg wasn’t found — open Media in the MSL Tools hub to download it.", "error")
            return
        if action == ACTION_LIGHT:
            RunEnding.instance().make_light_copy(path, self._tools, copy=self._copy.isChecked())
            self._say("Making a light copy…")
        elif action == ACTION_COMPARE:
            previous = self._previous_result(Path(path))
            if previous is None:
                self._say("No earlier playblast of this one to compare with.", "error")
                return
            RunEnding.instance().compare_with(path, previous, self._tools)
            self._say(f"Comparing with {previous.name}…")

    def _send_to_media(self, path: Path) -> None:
        """Opens `path` in the hub's Media — through the link of a Maya started from MSL Tools."""
        from msl_tools.msl.tools.maya import hub_link
        link = hub_link.current()
        sent = link is not None and hasattr(link, "open_in_media") and link.open_in_media([str(path)])
        if sent:
            self._say(f"Sent to MSL Tools Media · {path.name}", "done")
        else:
            self._say("MSL Tools can’t be reached: this Maya wasn’t started from it, or the hub is closed.",
                      "error")

    def _previous_result(self, path: Path) -> Path | None:
        """The playblast before `path`: one version down in its folder ("_v003" -> "_v002"), else the
        previous video of this scene in the history."""
        previous = naming.previous_version(path)
        if previous is not None:
            return previous
        history = self._history()  # oldest first
        mine = next((entry for entry in history if entry.get("path") == str(path)), None)
        if mine is None:
            return None
        older = [Path(entry["path"]) for entry in history
                 if entry.get("path") and entry["path"] != str(path) and entry.get("time", 0) < mine.get("time", 0)
                 and self._is_this_scene(entry, mine.get("scene", ""), mine.get("scene_path", ""))]
        videos = [candidate for candidate in older if candidate.is_file() and candidate.suffix.lower() == path.suffix.lower()]
        return videos[-1] if videos else None

    def _on_side_done(self, result: dict) -> None:
        """A light copy / a comparison is ready (or failed): said on the status line — unless a
        capture owns it now."""
        if not self._busy:
            self._say(result.get("message", ""), "done" if result.get("state") == "done" else "error")
