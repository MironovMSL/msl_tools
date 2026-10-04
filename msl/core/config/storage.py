import threading
from abc import ABC, abstractmethod
from typing import Any

from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic

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
    Thread-safe JSON storage with atomic writes (core/fs/safe_json.py).

    read() returns {} for a missing file and for a broken one — which is
    moved aside as ``config.broken-<stamp>.json`` first, never overwritten.
    A file that exists but can't be read right now raises JsonUnavailable:
    the caller must not save over it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def read(self, path: str) -> dict[str, Any]:
        with self._lock:
            return read_json_object(path)

    def write(self, path: str, data: dict[str, Any]) -> None:
        with self._lock:
            try:
                write_json_atomic(path, data, indent=4)
            except OSError as e:
                raise RuntimeError(f"Failed to write config safely to {path}: {e}") from e


__all__ = ["ConfigStorage", "JsonStorage", "JsonUnavailable"]
