import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

# =========================================================
# STORAGE LAYER (ABSTRACT & THREAD-SAFE)
# =========================================================

class ConfigStorage(ABC):
    """
    Abstract storage interface.
    """

    @abstractmethod
    def read(self, path: str) -> dict[str, Any]:
        """Read data from the given path and return it as a dictionary."""
        pass

    @abstractmethod
    def write(self, path: str, data: dict[str, Any]) -> None:
        """Write the dictionary data to the given path."""
        pass


class JsonStorage(ConfigStorage):
    """
    Thread-safe JSON storage implementation with atomic writes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def read(self, path: str) -> dict[str, Any]:
        p = Path(path)

        if not p.exists():
            return {}

        with self._lock:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}

    def write(self, path: str, data: dict[str, Any]) -> None:
        p = Path(path)

        with self._lock:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = p.with_suffix(".tmp")

                tmp_path.write_text(
                    json.dumps(data, indent=4, ensure_ascii=False),
                    encoding="utf-8"
                )

                tmp_path.replace(p)
            except OSError as e:
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
                raise RuntimeError(f"Failed to write config safely to {path}: {e}")
