# core/scene_paths/ma_paths.py
"""The paths inside a Maya ASCII scene, and swapping a folder at their start for a variable.

Where a .ma keeps paths (seen in real 2024 scenes):
- a reference:          file -r ... -rfn "RigRN" -typ "mayaAscii" "E:/.../Rig.ma";   (twice: -rdi and -r)
- an attribute:         setAttr ".ftn" -type "string" "E:/.../tex.png";   (a texture; any string attribute)
- a reference's history: setAttr ".fn[0]" -type "string" "C:/Users/.../Rig.ma";
- a reference edit, a string INSIDE a string:
                        2 "file5" "fileTextureName" " -type \\"string\\" \\"W:/.../tex.tga\\""

A path is taken where a string starts with a drive ("E:/"), a share ("//server/") or a variable
("$WG_ANIM/"). The file is worked on as BYTES, decoded only for showing: the scene's own encoding
(its "//Codeset:" line) is never changed, and nothing but the folder at a path's start is touched —
the rest of the path keeps its own slashes, the rest of the file every byte.

Binary scenes (.mb) go through Maya instead: mb_paths.py.

Qt-free; reads and writes files, nothing else.
"""
from __future__ import annotations

import bisect
import codecs
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from msl_tools.msl.core.fs.safe_json import write_bytes_atomic
from msl_tools.msl.core.scene_paths.roots import Root, normalized

ASCII_SUFFIX = ".ma"
BINARY_SUFFIX = ".mb"
SCENE_SUFFIXES = (ASCII_SUFFIX, BINARY_SUFFIX)
SKIP_FOLDERS = ("incrementalSave",)   # Maya's own copies of old versions
COLLECT_AT_MOST = 5000

# What a path is used for.
REFERENCE = "reference"
REFERENCE_EDIT = "reference edit"
REFERENCE_HISTORY = "reference history"
TEXTURE = "texture"
ATTRIBUTE = "attribute"
SCRIPT = "script"        # a string inside MEL code (the scene's UI layout, a script node): never changed

# Where a path stands.
CHANGE = "change"        # starts with a root's folder: becomes $ROOT/...
VARIABLE = "variable"    # starts with a variable already
OUTSIDE = "outside"      # absolute, under none of the roots
LEFT = "left"            # under a root, but inside a script: MEL wouldn't expand $NAME there

_START = re.compile(rb'(?<=")(?:[A-Za-z]:(?:/|\\)|(?://|\\{2,})[^\s"\\/]+(?:/|\\)|\$[A-Za-z_][A-Za-z0-9_]*(?:/|\\))')
_SEPARATOR = rb"(?:/|\\+)"
_AFTER_ROOT = rb'(?=/|\\|"|$)'
_NODE = re.compile(rb'^(?:createNode\s+(\S+)\s[^\n]*?-n\s+"([^"]+)"|select\s+-ne\s+:?([^\s;]+);)', re.M)
_SET_ATTR = re.compile(rb'\s*setAttr\s+(?:-\w+\s+\S+\s+)*?"\.?([^"]+)"')
_EDIT = re.compile(rb'\s*\d+\s+"([^"]+)"\s+"([^"]+)"')
_CODESET = re.compile(rb"^//Codeset:\s*(\S+)", re.M)
_NOT_A_FILE = ("<", "#", "%0", "%d")   # <UDIM>, <f>, frame numbers: a pattern, not one file


class ScenePathsError(Exception):
    """Something the user is told as it is (the message is written for them)."""


@dataclass
class PathUse:
    """One path in the scene: where it is, what it is for, and what it becomes."""

    line: int
    kind: str
    node: str
    attribute: str
    path: str                 # as the scene has it, slashes made forward for showing
    start: int                # byte offsets of the path in the file
    end: int
    state: str = OUTSIDE
    root: Root | None = None
    root_end: int = 0         # byte offset where the root's folder ends (state CHANGE)
    variable: str = ""        # state VARIABLE: its name
    exists: bool | None = None   # None = not checked, or a pattern (<UDIM>, ####)
    note: str = ""            # why a path under a root is LEFT (a binary scene's runner says it)
    relink: str = ""          # a missing file found again (finder.py): the WHOLE path becomes this
    found: list = field(default_factory=list)   # the files of that name the finder found, best first
    options: list = field(default_factory=list)  # every (root, root_end) that could stand for it, deepest first

    @property
    def new_path(self) -> str:
        """What the path reads after the write ("" when it doesn't change): a found file's path, or
        the root's $NAME in place of its folder."""
        if self.relink:
            return self.relink
        if self.state != CHANGE or self.root is None:
            return ""
        return self.root.token + self.path[len(self.root.value):]

    @property
    def key(self) -> str:
        """The use in its scene for a runner: "node.attribute", or the reference node."""
        return f"{self.node}.{self.attribute}" if self.node and self.attribute else self.node

    @property
    def where(self) -> str:
        """"file2.ftn" / "Rig_LabradorRN" — the node and attribute, as far as known."""
        if self.node and self.attribute:
            return f"{self.node}.{self.attribute}"
        return self.node or self.attribute


@dataclass
class SceneScan:
    """What one scene holds."""

    path: Path
    size: int = 0
    mtime_ns: int = 0
    codeset: str = "utf-8"
    uses: list[PathUse] = field(default_factory=list)
    error: str = ""
    binary: bool = False      # a .mb, read by a mayapy (mb_paths.py): no byte offsets, written by Maya
    maya: str = ""            # the Maya that read it (binary scenes)

    @property
    def changes(self) -> list[PathUse]:
        """Paths whose folder becomes a variable (a relinked one counts as a relink, not here)."""
        return [use for use in self.uses if use.state == CHANGE and not use.relink]

    @property
    def relinks(self) -> list[PathUse]:
        """Missing files found again: the whole path is written anew."""
        return [use for use in self.uses if use.relink]

    @property
    def writes(self) -> list[PathUse]:
        """Everything a write changes."""
        return [use for use in self.uses if use.relink or use.state == CHANGE]

    @property
    def via_variable(self) -> list[PathUse]:
        return [use for use in self.uses if use.state == VARIABLE]

    @property
    def outside(self) -> list[PathUse]:
        return [use for use in self.uses if use.state == OUTSIDE]

    @property
    def left(self) -> list[PathUse]:
        return [use for use in self.uses if use.state == LEFT]

    @property
    def missing(self) -> list[PathUse]:
        """Files the scene uses that aren't there — not a path inside a script (a UI layout's
        background picture) nor a reference's history entry (its OLD file names): nothing loads those."""
        return [use for use in self.uses if use.exists is False and use.kind not in (SCRIPT, REFERENCE_HISTORY)]


@dataclass
class ApplyResult:
    path: Path
    changed: int
    backup: Path | None


# --- the scenes of a drop ----------------------------------------------------------------------

def collect_scenes(paths, limit: int = COLLECT_AT_MOST) -> tuple[list[Path], bool]:
    """Maya scenes among `paths` — files as they are, folders searched all the way down (Maya's
    incrementalSave copies and hidden folders left out). Returns (scenes in order, cut at `limit`)."""
    found: list[Path] = []
    seen: set[str] = set()

    def take(file: Path) -> bool:
        key = os.path.normcase(str(file))
        if key not in seen:
            seen.add(key)
            found.append(file)
        return len(found) >= limit

    for entry in paths:
        entry = Path(entry)
        if entry.is_file():
            if entry.suffix.lower() in SCENE_SUFFIXES and take(entry):
                return found, True
        elif entry.is_dir():
            for folder, folders, files in os.walk(entry):
                folders[:] = sorted(name for name in folders
                                    if not name.startswith(".") and name not in SKIP_FOLDERS)
                for name in sorted(files):
                    if name.lower().endswith(SCENE_SUFFIXES) and take(Path(folder) / name):
                        return found, True
    return found, False


# --- reading ---------------------------------------------------------------------------------------

def codeset_of(data: bytes) -> str:
    """The encoding the scene says it is written in ("//Codeset: 1252" -> cp1252); UTF-8 if it says none."""
    match = _CODESET.search(data, 0, 4096)
    if not match:
        return "utf-8"
    name = match.group(1).decode("ascii", "replace")
    candidate = f"cp{name}" if name.isdigit() else name
    try:
        return codecs.lookup(candidate).name
    except LookupError:
        return "utf-8"


def _root_pattern(root: Root, codeset: str) -> re.Pattern | None:
    """The root's folder as it can stand in the file: any case, any slash, escaped or not."""
    try:
        value = root.value.encode(codeset)
    except UnicodeEncodeError:
        return None   # the file can't even hold this folder's name
    if value.startswith(b"//"):
        head, parts = rb"(?://|\\{2,})", value[2:].split(b"/")
    else:
        head, parts = b"", value.split(b"/")
    body = _SEPARATOR.join(re.escape(part) for part in parts)
    return re.compile(head + body + _AFTER_ROOT, re.IGNORECASE)


def _path_end(data: bytes, start: int) -> int | None:
    """Where the string holding a path ends (the path's own end), or None for a broken line."""
    quote = data.find(b'"', start)
    line_end = data.find(b"\n", start)
    if quote == -1 or (line_end != -1 and line_end < quote):
        return None
    slashes = 0
    while quote - slashes - 1 >= start and data[quote - slashes - 1] == 0x5C:
        slashes += 1
    return quote - 1 if slashes % 2 else quote   # an odd run = \" : the string inside a string ends


def _shown(raw: bytes, codeset: str) -> str:
    text = raw.decode(codeset, "replace")
    return re.sub(r"\\+", "/", text)


def _exists(path: str, cache: dict) -> bool | None:
    if not path or any(mark in path for mark in _NOT_A_FILE):
        return None
    key = os.path.normcase(path)
    if key not in cache:
        try:
            cache[key] = os.path.exists(path)
        except (OSError, ValueError):
            cache[key] = False
    return cache[key]


def scan(path, roots: list[Root], environment: dict | None = None, check_files: bool = True,
         exists_cache: dict | None = None) -> SceneScan:
    """Reads one scene and lists every absolute path in it, with what it would become.

    roots: deepest first (roots.roots_from() sorts them). environment: values of the variables
    paths already use, to check those files exist (the process's own when None). exists_cache:
    shared between scenes of one run, so a texture used by fifty scenes is looked up once."""
    path = Path(path)
    result = SceneScan(path)
    if path.suffix.lower() == BINARY_SUFFIX:
        result.error = "a binary scene (.mb) — read through Maya: mb_paths.scan_binary()"
        return result
    try:
        stat = path.stat()
        data = path.read_bytes()
    except OSError as error:
        result.error = f"can’t be read: {error.strerror or error}"
        return result
    result.size, result.mtime_ns = stat.st_size, stat.st_mtime_ns
    if not data.startswith(b"//Maya ASCII"):
        result.error = "not a Maya ASCII scene (no “//Maya ASCII” line at its start)"
        return result
    codeset = result.codeset = codeset_of(data)
    patterns = [(root, _root_pattern(root, codeset)) for root in roots]
    patterns = [(root, pattern) for root, pattern in patterns if pattern is not None]
    given = environment
    environment = dict(os.environ) if given is None else {}
    environment.update({root.name: root.value for root in roots})
    environment.update(given or {})   # what the caller gives is what the scene will open with
    cache = {} if exists_cache is None else exists_cache
    nodes = [(match.start(), match) for match in _NODE.finditer(data)]
    node_starts = [start for start, _match in nodes]

    line, counted_to = 1, 0
    for match in _START.finditer(data):
        start = match.start()
        end = _path_end(data, start)
        if end is None or end <= start:
            continue
        line += data.count(b"\n", counted_to, start)
        counted_to = start
        use = PathUse(line=line, kind=ATTRIBUTE, node="", attribute="",
                      path=_shown(data[start:end], codeset), start=start, end=end)
        _describe(use, data, start, nodes, node_starts)
        matches = [(root, found.end()) for root, pattern in patterns
                   for found in [pattern.match(data, start, end + 1)] if found]
        if matches:   # (the root's part reads as long as root.value: one "/" per separator)
            use.root = matches[0][0]
            if use.kind == SCRIPT:
                use.state = LEFT
            else:
                use.state, use.root_end = CHANGE, matches[0][1]
                use.options = matches   # the deepest first; the user may pick another (choose())
        else:
            if data[start] == 0x24:   # "$"
                use.state = VARIABLE
                use.variable = match.group(0)[1:-1].rstrip(b"\\").decode("ascii")
        if check_files:
            use.exists = _exists(_resolved(use, environment), cache)
        result.uses.append(use)
    return result


def _resolved(use: PathUse, environment: dict) -> str:
    if use.state == VARIABLE:
        value = environment.get(use.variable)
        return normalized(value) + use.path[len(use.variable) + 1:] if value else ""
    return use.path


def _describe(use: PathUse, data: bytes, start: int, nodes: list, node_starts: list) -> None:
    """What the path is for: the line it stands on, and the node the line belongs to."""
    line_start = data.rfind(b"\n", 0, start) + 1
    head = data[line_start:min(start, line_start + 400)]
    if data[start - 2:start] == b'\\"':
        edit = _EDIT.match(head)
        if edit:
            use.kind = REFERENCE_EDIT
            use.node, use.attribute = (edit.group(1).decode("utf-8", "replace"),
                                       edit.group(2).decode("utf-8", "replace"))
            return
        use.kind = SCRIPT
    if head.startswith(b"file ") and b" -r" in head:
        use.kind = REFERENCE
        name = re.search(rb'-rfn\s+"([^"]+)"', head)
        use.node = name.group(1).decode("utf-8", "replace") if name else ""
        return
    index = bisect.bisect_right(node_starts, start) - 1
    if index >= 0:
        found = nodes[index][1]
        use.node = (found.group(2) or found.group(3) or b"").decode("utf-8", "replace")
    attribute = _SET_ATTR.match(head)
    if attribute:
        use.attribute = attribute.group(1).decode("utf-8", "replace")
        if use.attribute in ("ftn", "fileTextureName"):
            use.kind = TEXTURE
        elif use.attribute.startswith("fn["):
            use.kind = REFERENCE_HISTORY


# --- writing -----------------------------------------------------------------------------------------

def choose(use: PathUse, name: str | None) -> None:
    """Writes `use` through the root called `name` (one of its options); "" = leave it as it is;
    None = its deepest root, as found. Safe to call again with another choice."""
    if not use.options:
        return
    if name == "":
        use.state, use.note = LEFT, "left as it is — your choice"
        return
    root, root_end = next(((root, end) for root, end in use.options if root.name == name), use.options[0])
    use.root, use.root_end, use.state, use.note = root, root_end, CHANGE, ""


def rewrite(data: bytes, uses: list[PathUse], codeset: str) -> bytes:
    """`data` with the root's folder at the start of each CHANGE use swapped for its $NAME, and each
    relinked use's whole path replaced (forward slashes: nothing to escape, inside a string or not)."""
    pieces, position = [], 0
    for use in sorted((each for each in uses if each.relink or (each.state == CHANGE and each.root is not None)),
                      key=lambda each: each.start):
        if use.start < position or use.start < 0:
            continue
        pieces.append(data[position:use.start])
        if use.relink:
            pieces.append(use.relink.encode(codeset))
            position = use.end
        else:
            pieces.append(use.root.token.encode(codeset))
            position = use.root_end
    pieces.append(data[position:])
    return b"".join(pieces)


def backup_name(path: Path, now: float | None = None) -> Path:
    """scene.ma -> scene.ma.20261014-153012.bak (a .bak: Maya's file dialog doesn't list it)."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    number = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}-{number}.bak")
        number += 1
    return candidate


def apply(result: SceneScan, backup: bool = True) -> ApplyResult:
    """Writes the swaps of `result` into its scene (all at once — a cut write leaves the old file).
    Refuses a scene changed since it was read, and one that is read-only. Raises ScenePathsError."""
    path = result.path
    changes = result.writes
    if result.error or not changes:
        return ApplyResult(path, 0, None)
    if result.binary:
        raise ScenePathsError(f"{path.name} is a binary scene — Maya writes it (mb_paths.apply_binary)")
    try:
        stat = path.stat()
    except OSError as error:
        raise ScenePathsError(f"{path.name}: it is gone ({error.strerror or error})") from error
    if (stat.st_size, stat.st_mtime_ns) != (result.size, result.mtime_ns):
        raise ScenePathsError(f"{path.name} changed since it was read — read it again first")
    if not os.access(path, os.W_OK):
        raise ScenePathsError(f"{path.name} is read-only (checked in? check it out first)")
    try:
        data = path.read_bytes()
        updated = rewrite(data, changes, result.codeset)
        copy = None
        if backup:
            copy = backup_name(path)
            shutil.copy2(path, copy)
        write_bytes_atomic(path, updated)
    except UnicodeEncodeError as error:
        raise ScenePathsError(f"{path.name}: its encoding ({result.codeset}) can’t hold a new path") from error
    except OSError as error:
        raise ScenePathsError(f"{path.name}: couldn’t be written ({error.strerror or error})") from error
    return ApplyResult(path, len(changes), copy)
