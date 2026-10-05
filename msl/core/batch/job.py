# core/batch/job.py
"""One scene to render (BatchJob) and the queue of them on disk (BatchStore)."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from msl_tools.msl.core.batch.frames import FramesError, format_frames, parse_frames
from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic

# where a job stands
WAITING, CHECKING, RUNNING, DONE, FAILED, CANCELLED = "waiting", "checking", "running", "done", "failed", "cancelled"
# how Maya runs it
MODE_WINDOW, MODE_HEADLESS = "window", "headless"
# what renders it ("auto" = what the scene says, core/batch/checks.py:choose_renderer)
AUTO, ARNOLD, REDSHIFT, HW2 = "auto", "arnold", "redshift", "hw2"
RENDERER_TITLES = {AUTO: "Auto", ARNOLD: "Arnold", REDSHIFT: "Redshift", HW2: "Viewport"}
SIZES = {"100%": 1.0, "50%": 0.5, "25%": 0.25}


@dataclass
class BatchJob:
    """A scene to render and how.

    Attributes (the settings — empty / 0 = take it from the scene):
        scene: The .ma / .mb file. It is never saved by a render.
        enabled: Off = the queue passes it by.
        maya: The Maya version ("2024"; "" = the scene's own if installed, else the newest).
        renderer: AUTO / ARNOLD / REDSHIFT / HW2 (Hardware 2.0: a picture like the viewport's).
        camera: The camera to render ("" = the scene's renderable one, else the first non-default).
        frames: "1-120, 200" ("" = the scene's playback range).
        size: A key of SIZES — the scene's resolution scaled.
        mode: MODE_WINDOW (a windowed Maya, minimized: Arnold's interactive licence, no watermark)
            or MODE_HEADLESS (no window: faster to start; Arnold watermarks without a batch licence).
        folder: Where the frames go ("" = <scene folder>/renders/<scene name>).
        make_video: When it is done, the frames become a video next to them (ffmpeg, as in Media).
    And what happened:
        id, state, message, probe (what the scene check found — the runner's report), done (frames
        rendered), seconds (Maya's time per frame, the average), last_file, started / finished.
    """

    scene: str
    enabled: bool = True
    maya: str = ""
    renderer: str = AUTO
    camera: str = ""
    frames: str = ""
    size: str = "100%"
    mode: str = MODE_WINDOW
    folder: str = ""
    make_video: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    state: str = WAITING
    message: str = ""
    probe: dict = field(default_factory=dict)
    done: list = field(default_factory=list)
    seconds: float = 0.0
    last_file: str = ""
    started: float = 0.0
    finished: float = 0.0
    video: str = ""

    @property
    def name(self) -> str:
        return Path(self.scene).stem

    def output_folder(self) -> Path:
        if self.folder:
            return Path(self.folder)
        scene = Path(self.scene)
        return scene.parent / "renders" / scene.stem

    def camera_name(self) -> str:
        """The camera that renders: the one set, else the scene's renderable one, else its first own one."""
        if self.camera:
            return self.camera
        cameras = self.probe.get("cameras") or []
        for camera in cameras:
            if camera.get("renderable") and not camera.get("startup"):
                return camera["name"]
        for camera in cameras:
            if not camera.get("startup"):
                return camera["name"]
        return "persp" if cameras else ""

    def prefix(self) -> str:
        """The frames' file names: <scene>_<camera>.####.png."""
        camera = self.camera_name().split(":")[-1]
        return f"{self.name}_{camera}" if camera else self.name

    def frame_list(self) -> list[int]:
        """The frames to render; raises FramesError (with a message) when the text is wrong."""
        if self.frames.strip():
            return parse_frames(self.frames)
        playback = self.probe.get("playback")
        if playback:
            return list(range(int(round(playback[0])), int(round(playback[1])) + 1))
        raise FramesError("Say which frames — the scene hasn't been read yet.")

    def frames_text(self) -> str:
        """What the frames are, for a row: the text typed, or the scene's range."""
        if self.frames.strip():
            return self.frames.strip()
        try:
            return format_frames(self.frame_list())
        except FramesError:
            return "scene range"

    def resolution(self) -> tuple[int, int]:
        """(width, height) of the frames — the scene's, scaled by `size`, even numbers."""
        width, height = (self.probe.get("resolution") or [1920, 1080])[:2]
        scale = SIZES.get(self.size, 1.0)
        return max(int(width * scale) // 2 * 2, 2), max(int(height * scale) // 2 * 2, 2)

    def frame_file(self, frame: int) -> Path:
        return self.output_folder() / f"{self.prefix()}.{int(frame):04d}.png"

    def existing_frames(self) -> list[int]:
        """Frames of the list whose file is already there (a render picks up where it stopped)."""
        try:
            frames = self.frame_list()
        except FramesError:
            return []
        return [frame for frame in frames if self.frame_file(frame).is_file()]

    def reset(self) -> None:
        """Back to waiting (what was rendered stays on disk and is skipped)."""
        self.state, self.message, self.started, self.finished = WAITING, "", 0.0, 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BatchJob":
        known = {name for name in cls.__dataclass_fields__}
        job = cls(**{key: value for key, value in data.items() if key in known})
        if job.state in (RUNNING, CHECKING):
            job.state, job.message = WAITING, "interrupted — goes on where it stopped"
        return job


class BatchStore:
    """The queue in `<folder>/queue.json` (core/fs/safe_json.py: a broken file is moved aside, a
    locked one is never written over)."""

    FILE = "queue.json"

    def __init__(self, folder):
        self.path = Path(folder) / self.FILE
        self._locked = False

    def load(self) -> list[BatchJob]:
        try:
            data = read_json_object(self.path)
        except JsonUnavailable:
            self._locked = True
            return []
        jobs = []
        for entry in data.get("jobs", []):
            if isinstance(entry, dict) and entry.get("scene"):
                try:
                    jobs.append(BatchJob.from_dict(entry))
                except TypeError:
                    continue
        return jobs

    def save(self, jobs: list[BatchJob]) -> bool:
        if self._locked:
            return False
        try:
            write_json_atomic(self.path, {"saved": time.time(), "jobs": [job.to_dict() for job in jobs]})
        except OSError:
            return False
        return True
