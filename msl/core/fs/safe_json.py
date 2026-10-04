"""
Reading and writing the small JSON files that hold the user's data
(configs, histories, snippets) so that a failure never costs that data.

Two rules:
- A write never leaves a half-written file: the text goes into a temporary
  file next to the target (a unique name — two writers never share it), is
  flushed to the disk, then replaces the target in one step.
- A file that can't be USED is never written over. One that is broken
  (not JSON, or not a JSON object) is moved aside as
  ``<name>.broken-<stamp><suffix>`` before the caller starts afresh, so a
  typo in a hand edit or a write cut off by a power loss leaves the old
  data where it can be recovered. One that can't be READ at the moment
  (locked by an antivirus scan, a sync client) raises JsonUnavailable —
  the caller must not save over it.

Qt-free, stdlib only.
"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# A freshly written file is often held for a moment by an antivirus scan
# ("Access is denied" / "being used by another process").
RETRY_SECONDS = 2.0
RETRY_STEP    = 0.1


class JsonUnavailable(OSError):
    """The file exists but can't be used right now; it must not be written over."""


def _retrying(action: Callable[[], Any]) -> Any:
    """Runs ``action``, trying again for RETRY_SECONDS while Windows says the file is in use."""
    deadline = time.monotonic() + RETRY_SECONDS
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(RETRY_STEP)


def quarantine(path: str | Path) -> Path | None:
    """
    Moves a broken file aside as ``<name>.broken-<stamp><suffix>`` and
    returns where it went (None if it couldn't be moved).
    """
    path = Path(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.broken-{stamp}{path.suffix}")
    counter = 1
    while target.exists():
        counter += 1
        target = path.with_name(f"{path.stem}.broken-{stamp}-{counter}{path.suffix}")
    try:
        _retrying(lambda: os.replace(path, target))
    except OSError as error:
        logger.warning("Could not move the broken file %s aside: %s", path, error)
        return None
    return target


def read_json_object(path: str | Path) -> dict[str, Any]:
    """
    Returns the JSON object stored in ``path``; {} when there is no file.

    A file that isn't a JSON object is moved aside (quarantine()) and reads
    as {}. A file that can't be read — or is broken and can't be moved
    aside — raises JsonUnavailable.
    """
    path = Path(path)
    try:
        raw = _retrying(path.read_bytes)
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise JsonUnavailable(f"Can't read {path}: {error}") from error

    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as error:
        data, reason = None, str(error)
    else:
        reason = f"a JSON {type(data).__name__}, not an object"
    if isinstance(data, dict):
        return data

    moved = quarantine(path)
    if moved is None:  # still in its place: writing now would destroy it
        raise JsonUnavailable(f"{path} is broken ({reason}) and could not be moved aside")
    logger.warning("%s was broken (%s); kept as %s, starting afresh.", path, reason, moved.name)
    return {}


def write_json_atomic(path: str | Path, data: Any, indent: int | None = 4) -> None:
    """Writes ``data`` as JSON into ``path`` all at once (see the module's docstring). Raises OSError."""
    write_text_atomic(path, json.dumps(data, indent=indent, ensure_ascii=False))


def write_text_atomic(path: str | Path, text: str) -> None:
    """Writes ``text`` (UTF-8) into ``path`` all at once — the same way as
    write_json_atomic(), for the user's text files (scripts). Raises OSError."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _retrying(lambda: os.replace(temporary, path))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
