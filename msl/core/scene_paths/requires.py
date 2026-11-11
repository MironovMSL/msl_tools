# core/scene_paths/requires.py
"""The `requires` lines of a Maya ASCII scene: which plug-ins it asks for, and which of them nothing in
the file uses — those can go, so the scene (and every shot referencing it) stops asking for them.

A scene saved where a plug-in was loaded keeps `requires "<plug-in>" "<version>";` near its top, and
Maya tries to load it on every open ("Plug-in, "evoattrib", was not found on MAYA_PLUG_IN_PATH" -
measured: five such cost ~0.5 s of a 2.4 s open; they are noise, not data). Since Maya 2016 a line
names the plug-in's node types the scene holds (`-nodeType "aiOptions"`): a line whose types none of
the file's `createNode` uses, or that names no type at all, is UNUSED. A line that names data types
(`-dataType`) is never offered - what uses a data type can't be told from the text.

Offered for removal by default: an unused line whose plug-in no installed Maya has (`known_plugins`).
An unused line of a plug-in Maya has (stereoCamera...) is harmless, and is only removed when picked.
`maya` itself is never touched. Qt-free; `known_plugins` lists folders, the rest works on bytes.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_STATEMENT = re.compile(rb"^requires\b[^;]*;[^\S\n]*(?:\r?\n)?", re.MULTILINE)
_TOKEN = re.compile(rb'"(?:[^"\\]|\\.)*"|[^\s;]+')
_CREATE = re.compile(rb"^createNode\s+([A-Za-z_][\w]*)", re.MULTILINE)
PLUGIN_SUFFIXES = (".mll", ".py", ".pyc", ".nll.dll", ".bundle", ".so")


@dataclass
class Requirement:
    """One `requires` line."""

    plugin: str
    version: str = ""
    node_types: list = field(default_factory=list)
    data_types: list = field(default_factory=list)
    used: bool = False          # a node type it names is created in the file
    known: bool = False         # an installed Maya has this plug-in
    remove: bool = False        # the line goes at the next write (the default: unused and not known)

    @property
    def removable(self) -> bool:
        return not self.used and not self.data_types

    def why(self) -> str:
        """What the line is, in a few words, for the list."""
        if self.used:
            return f"used: {', '.join(self.node_types[:3])}" + ("…" if len(self.node_types) > 3 else "")
        if self.data_types:
            return "names data types — kept"
        return "nothing uses it" + ("" if self.known else " · not on this computer")


def _text(token: bytes) -> str:
    if token.startswith(b'"') and token.endswith(b'"') and len(token) >= 2:
        token = token[1:-1]
    return token.decode("latin-1")


def _parse(statement: bytes) -> Requirement | None:
    tokens = _TOKEN.findall(statement)[1:]      # without "requires"
    node_types, data_types, positional = [], [], []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in (b"-nodeType", b"-nt", b"-dataType", b"-dt") and index + 1 < len(tokens):
            (node_types if token in (b"-nodeType", b"-nt") else data_types).append(_text(tokens[index + 1]))
            index += 2
            continue
        if not token.startswith(b"-"):
            positional.append(_text(token))
        index += 1
    if not positional or positional[0].lower() == "maya":
        return None
    return Requirement(positional[0], positional[1] if len(positional) > 1 else "", node_types, data_types)


def _head(data: bytes) -> bytes:
    """The part of the file before its first node: where Maya writes `requires`."""
    cut = data.find(b"\ncreateNode")
    return data if cut < 0 else data[:cut + 1]


def read(data: bytes, known: set | None = None) -> list[Requirement]:
    """The scene's requirements (not `maya`), each with used / known / the default `remove`."""
    created = {match.group(1).decode("latin-1") for match in _CREATE.finditer(data)}
    found = []
    for match in _STATEMENT.finditer(_head(data)):
        requirement = _parse(match.group(0))
        if requirement is None:
            continue
        requirement.used = any(kind in created for kind in requirement.node_types)
        requirement.known = known is not None and requirement.plugin.lower() in known
        requirement.remove = requirement.removable and known is not None and not requirement.known
        found.append(requirement)
    return found


def strip(data: bytes, plugins) -> tuple[bytes, int]:
    """The file without the `requires` lines of `plugins` (names, any case) - and how many went.
    Only removable lines go: one whose node types the file creates stays whatever is asked."""
    wanted = {name.lower() for name in plugins}
    created = {match.group(1).decode("latin-1") for match in _CREATE.finditer(data)}
    head = _head(data)
    pieces, position, removed = [], 0, 0
    for match in _STATEMENT.finditer(head):
        requirement = _parse(match.group(0))
        if requirement is None or requirement.plugin.lower() not in wanted:
            continue
        if requirement.data_types or any(kind in created for kind in requirement.node_types):
            continue
        pieces.append(data[position:match.start()])
        position = match.end()
        removed += 1
    pieces.append(data[position:])
    return b"".join(pieces), removed


# --- which plug-ins this machine's Mayas have -----------------------------------------------------------

def _plugin_names(folder: Path, depth: int = 0) -> set:
    names = set()
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return names
    for entry in entries:
        lower = entry.name.lower()
        if entry.is_file():
            for suffix in PLUGIN_SUFFIXES:
                if lower.endswith(suffix):
                    names.add(lower[:-len(suffix)])
        elif depth < 1 and entry.is_dir():
            names |= _plugin_names(Path(entry.path), depth + 1)
    return names


def _module_folders(mod_dirs) -> list:
    """The plug-ins folders of the modules (.mod files) in `mod_dirs`."""
    folders = []
    for mod_dir in mod_dirs:
        try:
            mods = [entry.path for entry in os.scandir(mod_dir) if entry.name.lower().endswith(".mod")]
        except OSError:
            continue
        for mod in mods:
            try:
                lines = Path(mod).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            root = None
            for line in lines:
                line = line.strip()
                if line.startswith(("+", "-")) and not line.startswith("--"):
                    # "+ [KEY:VALUE ...] name version path" - the path may hold spaces
                    rest = line[1:].strip()
                    while re.match(r"[A-Za-z]{2,}:\S*\s", rest):
                        rest = rest.split(None, 1)[1]
                    parts = rest.split(None, 2)
                    if len(parts) == 3:
                        root = Path(parts[2].strip())
                        if not root.is_absolute():
                            root = Path(mod).parent / root
                        folders.append(root / "plug-ins")
                elif root is not None and line.lower().startswith("plug-ins:"):
                    value = line.split(":", 1)[1].strip()
                    if value and value.lower() != "null":
                        folders.append(Path(value) if os.path.isabs(value) else root / value)
                elif line.upper().startswith("MAYA_PLUG_IN_PATH") and "=" in line:
                    value = line.split("=", 1)[1].strip()
                    if value:
                        folders.append(Path(value) if os.path.isabs(value) or root is None else root / value)
    return folders


def known_plugins(installs: dict, documents: Path | None = None, shared: Path | None = None) -> set:
    """Lower-case names of the plug-ins the installed Mayas have: their bin/plug-ins and the modules
    Maya finds by default (its own modules folder, Autodesk's shared one, Documents/maya/modules).
    `installs`: {"2024": Path(".../Maya2024")}, as MayaPaths.get_available_installs() gives it."""
    documents = documents or Path.home() / "Documents" / "maya"
    names = set()
    shared = shared or (Path(os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files"))
                        / "Autodesk Shared" / "Modules" / "maya")
    for year, install in (installs or {}).items():
        install = Path(install)
        names |= _plugin_names(install / "bin" / "plug-ins")
        mod_dirs = [install / "modules", shared / str(year), shared, documents / "modules", documents / str(year) / "modules"]
        for folder in _module_folders(mod_dirs):
            names |= _plugin_names(folder)
    return names
