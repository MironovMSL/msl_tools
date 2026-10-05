# core/media/names.py
"""Names of results made from a TEMPLATE with tokens — "{name}_{date}_v{n}" —
the way the Playblast tool names its files.

    {name}    the source's name (a sequence: its frames' prefix)
    {action}  what was done, as the action's tag says it ("small", "trim"; "" for none)
    {date}    today: 2026-10-05
    {time}    the time: 1542
    {n}       a number, 001, 002, ... — one past the highest of that name already in the folder

An empty template means the classic name: "<name>_<action>" (`DEFAULT`). A
template without {n} gets "_2", "_3", ... when its name is taken, as before.
Nothing here touches the disk but listing the folder for {n}.
"""
import re
import time
from pathlib import Path

TOKENS = {
    "name": "the source’s name",
    "action": "what was done: small, trim, loop…",
    "date": "today: 2026-10-05",
    "time": "the time: 1542",
    "n": "a number, one past the highest in the folder: 001, 002…",
}
DEFAULT = "{name}_{action}"
PRESETS = {"Name + action": DEFAULT, "With the date": "{name}_{action}_{date}",
           "Versions": "{name}_{action}_v{n}", "Dated versions": "{name}_{date}_v{n}"}
PADDING = 3
_TOKEN = re.compile(r"\{(\w+)\}")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def unknown_tokens(template: str) -> list[str]:
    """Tokens of `template` that aren't in TOKENS (a typo would otherwise stay in every name)."""
    return [name for name in _TOKEN.findall(template or "") if name not in TOKENS]


def expand(template: str, name: str, action: str = "", moment: float | None = None, number: int | None = None) -> str:
    """The template with its tokens filled in. {n} stays as it is while `number` is None.
    Separators left over by an empty token ("shot__v001", "shot_") are tidied away."""
    moment = time.localtime(time.time() if moment is None else moment)
    values = {"name": name, "action": action.strip("._- "), "date": time.strftime("%Y-%m-%d", moment),
              "time": time.strftime("%H%M", moment)}
    if number is not None:
        values["n"] = f"{number:0{PADDING}d}"
    text = _TOKEN.sub(lambda match: values.get(match.group(1), match.group(0)), template or DEFAULT)
    text = re.sub(r"([._-])[._-]+", r"\1", text).strip("._- ")
    return _UNSAFE.sub("_", text) or name


def result_path(template: str, home: Path, name: str, action: str, suffix: str, taken=(),
                moment: float | None = None) -> Path:
    """Where a result named by `template` goes in `home`: never a file that is there, nor one of
    `taken` (results of jobs still to run)."""
    home = Path(home)
    taken = {Path(path) for path in taken}
    template = template or DEFAULT
    if "{n}" not in template:
        stem = expand(template, name, action, moment)
        candidate, counter = home / f"{stem}{suffix}", 2
        while candidate.exists() or candidate in taken:
            candidate = home / f"{stem}_{counter}{suffix}"
            counter += 1
        return candidate
    marker = ""  # a private-use character: no token, no separator, not "unsafe"
    pattern = re.escape(expand(template.replace("{n}", marker), name, action, moment)).replace(re.escape(marker),
                                                                                                r"(\d+)")
    found = re.compile(f"^{pattern}{re.escape(suffix)}$", re.IGNORECASE)
    names = [entry.name for entry in home.iterdir()] if home.is_dir() else []
    names += [path.name for path in taken if path.parent == home]
    highest = max((int(match.group(1)) for match in map(found.match, names) if match), default=0)
    return home / f"{expand(template, name, action, moment, highest + 1)}{suffix}"
