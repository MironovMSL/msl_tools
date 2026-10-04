"""Applies a downloaded update to an installed hub — the part that has to
happen while the hub is NOT running.

HubUpdater (hub_updater.py) downloads and checks the new version into
`<root>/.update/staged`, copies THIS file (the new version's own copy) next
to it and starts it, then the hub quits. This process then:

    1. waits for the hub to exit,
    2. brings the staged `msl/` next to the current one, moves the current
       `msl/` and root files into `.update/backup`, and the staged ones into
       place — the install is without an `msl/` only between two folder
       renames,
    3. brings the Python environment up to date if requirements.txt changed,
    4. starts the hub again and watches it for a few seconds,
    5. on ANY failure — including the new hub crashing on start — puts the
       backup back and starts the previous version instead.

`configs/` and `logs/` are never touched. What happened is written to
`.update/result.json` (the hub reads it on its next start) and
`.update/update.log`; the backup stays until the next update.

STANDARD LIBRARY ONLY, no imports from this package: it runs by path from
`.update/`, while the package itself is being replaced.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

MAIN_MODULE = "msl"
HUB_MODULE_SUFFIX = ".msl.run_hub"
EXIT_WAIT_SECONDS = 60       # for the hub to quit
MOVE_RETRY_SECONDS = 15      # a just-closed program's files can stay locked for a moment
HEALTH_SECONDS = 12          # a hub that dies with an error within this time = a bad update
RESULT_NAME = "result.json"
LOG_NAME = "update.log"
INCOMING_NAME = ".msl-incoming"    # the new code, waiting beside msl/ for the swap
RESTORING_NAME = ".msl-restoring"  # the backup's copy, waiting beside msl/ during a rollback
TRASH_PREFIX = "trash-"            # folders in .update/ on their way out


class _Log:
    def __init__(self, path: Path):
        self._path = path

    def __call__(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        try:
            with open(self._path, "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except OSError:
            pass


def wait_for_exit(pid: int, timeout: float) -> bool:
    """True once process `pid` is gone (or never existed)."""
    if pid <= 0:
        return True
    if os.name == "nt":
        import ctypes
        synchronize, wait_timeout = 0x00100000, 0x00000102
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True  # no such process anymore
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) != wait_timeout
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    return False


def _move(source: Path, destination: Path, copy_instead: bool = False) -> None:
    """os.replace with retries (antivirus / indexer / a dying process may
    hold a file for a moment). `copy_instead`: if the folder still can't be
    renamed, copy it - only for a source that may stay where it is."""
    deadline = time.monotonic() + MOVE_RETRY_SECONDS
    while True:
        try:
            os.replace(source, destination)
            return
        except OSError:
            if time.monotonic() >= deadline:
                if not copy_instead:
                    raise
                break
            time.sleep(0.4)
    shutil.copytree(source, destination)


class Swap:
    """How far swap_in() got — restore() undoes exactly that, nothing more.

    `backed_up` turns True only once the CURRENT `msl/` has been moved into
    this run's backup: before that, the installed code was never touched,
    and whatever `backup/` holds (an older backup, a half-deleted one) must
    not be put over it.
    """

    def __init__(self) -> None:
        self.backed_up = False


def _discard(folder: Path, work_dir: Path) -> None:
    """Gets `folder` out of the way at once (a rename — it raises if that
    isn't possible, before anything else was changed), then deletes it as
    far as it can. Leftovers are swept up by the next update."""
    if not folder.exists():
        return
    trash = work_dir / f"{TRASH_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{folder.name}"
    _move(folder, trash)
    shutil.rmtree(trash, ignore_errors=True)


def _discard_quietly(folder: Path, work_dir: Path) -> None:
    try:
        _discard(folder, work_dir)
    except OSError:
        shutil.rmtree(folder, ignore_errors=True)


def sweep_trash(work_dir: Path) -> None:
    """Deletes what earlier runs couldn't (files that were locked then)."""
    for leftover in work_dir.glob(TRASH_PREFIX + "*"):
        shutil.rmtree(leftover, ignore_errors=True)


def swap_in(root: Path, staged: Path, backup: Path, root_files: list[str], log, swap: Swap) -> None:
    """Current code -> `backup`, staged code -> `root`. Raises OSError;
    `swap` tells restore() what to undo.

    The order keeps the time without a `root/msl` to two folder renames:
    the new code is first brought next to the old one (`.msl-incoming`,
    copied if it can't be moved), then the old one goes out and the new
    one in. The previous backup is renamed away, never half-deleted in
    place.
    """
    work_dir = backup.parent
    incoming = root / INCOMING_NAME
    _discard(incoming, work_dir)  # a leftover of an interrupted run
    _move(staged / MAIN_MODULE, incoming, copy_instead=True)

    _discard(backup, work_dir)
    backup.mkdir(parents=True)
    for name in root_files:
        if (root / name).is_file():
            shutil.copy2(root / name, backup / name)
    if (root / MAIN_MODULE).exists():
        _move(root / MAIN_MODULE, backup / MAIN_MODULE)
    swap.backed_up = True
    log("previous version moved to the backup")

    _move(incoming, root / MAIN_MODULE)
    for name in root_files:
        if (staged / name).is_file():
            shutil.copy2(staged / name, root / name)
    log("new version in place")


def restore(root: Path, backup: Path, root_files: list[str], log, swap: Swap) -> bool:
    """Puts the backup back — only what this run took out (see Swap).
    False if even that failed (logged)."""
    work_dir = backup.parent
    _discard_quietly(root / INCOMING_NAME, work_dir)
    if not swap.backed_up:
        log("the installed version was not touched")
        return True
    try:
        if (backup / MAIN_MODULE).is_dir():
            # The copy is made first, beside the code in place; then two renames.
            restoring = root / RESTORING_NAME
            _discard(restoring, work_dir)
            shutil.copytree(backup / MAIN_MODULE, restoring)
            _discard(root / MAIN_MODULE, work_dir)
            # copy_instead: whatever kept the new code from being renamed in may hold this rename too
            _move(restoring, root / MAIN_MODULE, copy_instead=True)
            shutil.rmtree(restoring, ignore_errors=True)
        for name in root_files:
            if (backup / name).is_file():
                shutil.copy2(backup / name, root / name)
        log("previous version restored")
        return True
    except OSError:
        log("COULD NOT RESTORE the previous version:\n" + traceback.format_exc())
        return False


def _file_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.is_file() else b""


def update_environment(root: Path, backup: Path, log) -> bool:
    """Installs the new requirements into the hub's Python environment when
    requirements.txt changed — only if we ARE running in that environment
    (a developer's own Python is left alone)."""
    requirements = root / "requirements.txt"
    if _file_bytes(requirements) == _file_bytes(backup / "requirements.txt"):
        return True
    bootstrap_file = root / MAIN_MODULE / "core" / "installer" / "runtime_bootstrap.py"
    spec = importlib.util.spec_from_file_location("msl_runtime_bootstrap", bootstrap_file)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    try:
        inside = Path(sys.executable).resolve().is_relative_to(bootstrap.venv_dir().resolve())
    except OSError:
        inside = False
    if not inside:
        log("requirements.txt changed, but this isn't the msl_tools environment - packages left as they are")
        return True
    log("requirements.txt changed - updating the packages")
    return bootstrap.ensure(requirements, log=log)


def start_hub(root: Path) -> subprocess.Popen:
    """Starts the installed hub the way its shortcut does."""
    options = {"cwd": str(root.parent), "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    return subprocess.Popen([sys.executable, "-m", root.name + HUB_MODULE_SUFFIX], **options)


def crashed_on_start(process: subprocess.Popen) -> bool:
    """True if the hub exits WITH AN ERROR within HEALTH_SECONDS. Closing it
    normally (exit code 0) is not a crash."""
    try:
        return process.wait(timeout=HEALTH_SECONDS) != 0
    except subprocess.TimeoutExpired:
        return False


def write_result(work_dir: Path, status: str, version: str, previous: str, message: str = "") -> None:
    """status: "updated" | "rolled_back" | "failed" (= rollback failed too)."""
    data = {"status": status, "version": version, "previous_version": previous, "message": message,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    (work_dir / RESULT_NAME).write_text(json.dumps(data, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="the installed package root (contains msl/)")
    parser.add_argument("--wait-pid", type=int, default=0, help="the hub process to wait for")
    parser.add_argument("--version", default="", help="the version being installed")
    parser.add_argument("--previous-version", default="")
    parser.add_argument("--root-files", nargs="*", default=[])
    parser.add_argument("--no-start", action="store_true", help="don't start the hub afterwards (tests)")
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    work_dir = root / ".update"
    staged, backup = work_dir / "staged", work_dir / "backup"
    log = _Log(work_dir / LOG_NAME)
    version, previous, root_files = arguments.version, arguments.previous_version, arguments.root_files
    log(f"--- update {previous or '?'} -> {version or '?'} (helper pid {os.getpid()}) ---")
    swap = Swap()

    def roll_back(reason: str) -> int:
        log(reason)
        restored = restore(root, backup, root_files, log, swap)
        shutil.rmtree(staged, ignore_errors=True)
        write_result(work_dir, "rolled_back" if restored else "failed", version, previous, reason)
        if restored and not arguments.no_start:
            start_hub(root)
        return 1

    if not wait_for_exit(arguments.wait_pid, EXIT_WAIT_SECONDS):
        log("the hub did not quit - nothing was changed")
        write_result(work_dir, "rolled_back", version, previous, "MSL Tools did not close, so nothing was changed.")
        return 1
    if not (staged / MAIN_MODULE / "__init__.py").is_file():
        log("nothing staged - nothing was changed")
        write_result(work_dir, "rolled_back", version, previous, "The downloaded update was not found.")
        if not arguments.no_start:
            start_hub(root)
        return 1

    sweep_trash(work_dir)
    try:
        swap_in(root, staged, backup, root_files, log, swap)
    except OSError:
        return roll_back("Could not replace the files:\n" + traceback.format_exc())
    try:
        if not update_environment(root, backup, log):
            return roll_back("Could not install the packages the new version needs.")
    except Exception:
        return roll_back("Could not update the Python environment:\n" + traceback.format_exc())

    # Written BEFORE the hub starts: the new hub reads it on start.
    write_result(work_dir, "updated", version, previous)
    if not arguments.no_start:
        if crashed_on_start(start_hub(root)):
            return roll_back(f"Version {version} failed to start.")
    shutil.rmtree(staged, ignore_errors=True)
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
