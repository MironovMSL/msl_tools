# core/link/session.py
"""What the hub knows about one connected Maya — Qt-free."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


@dataclass
class MayaSession:
    """One running Maya connected to the hub.

    Attributes:
        session_id: The hub's own number for this connection (unique while the hub runs).
        pid: Maya's process id.
        version: Maya's year ("2025").
        full_version: Maya's full version as it reports it ("2025.3.1"; may be "").
        environment: The Maya Gate environment it was started in ("" = not from Maya Gate).
        scene: Path of the open scene ("" = untitled).
        modified: The open scene has unsaved changes.
        autosave: Maya's own autosave is switched on.
        autosave_folder: Where that Maya writes its autosave files ("" = unknown).
        startup_seconds: From the click in Maya Gate until Maya was ready (0 = not measured).
        busy_since: time.time() when it stopped answering (0 while it answers).
        boosted: Started with boost start.
        skipped: Plug-ins boost start left out at startup (they may have been loaded since).
        console: This Maya accepts code from the hub's console (a Dev environment).
        msl_version: Version of msl_tools loaded in that Maya.
        connected_at: time.time() when it connected.
    """

    session_id: int
    pid: int = 0
    version: str = ""
    full_version: str = ""
    environment: str = ""
    scene: str = ""
    modified: bool = False
    autosave: bool = False
    autosave_folder: str = ""
    startup_seconds: float = 0.0
    busy_since: float = 0.0
    boosted: bool = False
    skipped: list[str] = field(default_factory=list)
    console: bool = False
    busy: bool = False   # not answering pings right now (its main thread is working)
    msl_version: str = ""
    connected_at: float = field(default_factory=time.time)

    @property
    def scene_name(self) -> str:
        """File name of the open scene, "untitled" when it has none."""
        return os.path.basename(self.scene) if self.scene else "untitled"

    def connected_for(self, now: float | None = None) -> str:
        """How long it has been connected: "just now", "12 min", "3 h 05 min"."""
        seconds = max((now if now is not None else time.time()) - self.connected_at, 0)
        minutes = int(seconds // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes} min"
        return f"{minutes // 60} h {minutes % 60:02d} min"

    @classmethod
    def from_hello(cls, session_id: int, data: dict) -> "MayaSession":
        """A session from a hello message's data (unknown keys ignored, missing ones defaulted)."""
        return cls(session_id=session_id,
                   pid=int(data.get("pid") or 0),
                   version=str(data.get("version") or ""),
                   full_version=str(data.get("full_version") or ""),
                   environment=str(data.get("environment") or ""),
                   scene=str(data.get("scene") or ""),
                   modified=bool(data.get("modified")),
                   autosave=bool(data.get("autosave")),
                   autosave_folder=str(data.get("autosave_folder") or ""),
                   startup_seconds=_number(data.get("startup_seconds")),
                   boosted=bool(data.get("boosted")),
                   skipped=[str(name) for name in data.get("skipped") or [] if name],
                   console=bool(data.get("console")),
                   msl_version=str(data.get("msl_version") or ""))


def _number(value) -> float:
    try:
        return max(float(value or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0
