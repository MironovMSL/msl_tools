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
        boosted: Started with boost start.
        msl_version: Version of msl_tools loaded in that Maya.
        connected_at: time.time() when it connected.
    """

    session_id: int
    pid: int = 0
    version: str = ""
    full_version: str = ""
    environment: str = ""
    scene: str = ""
    boosted: bool = False
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
                   boosted=bool(data.get("boosted")),
                   msl_version=str(data.get("msl_version") or ""))
