# core/media/sequence.py
"""Image sequences: which files of a folder are the numbered frames of one
shot, and what is missing — Qt-free, reads only file NAMES."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".tga", ".bmp", ".dpx", ".webp")
_NUMBERED = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


@dataclass(frozen=True)
class ImageSequence:
    """The numbered frames of one shot: `<prefix><number><suffix>` in one folder.

    Attributes:
        folder: Where the frames are.
        prefix: The name before the number ("img_seq." / "Horse_render_01_").
        suffix: The extension, with its dot (".png").
        padding: Digits of the number when every name has the same count
            ("0001" -> 4); 0 = not padded ("1", "2", ... "10").
        frames: The frame numbers that exist, ascending.
    """

    folder: Path
    prefix: str
    suffix: str
    padding: int
    frames: tuple = field(default_factory=tuple)

    @property
    def first(self) -> int:
        return self.frames[0]

    @property
    def last(self) -> int:
        return self.frames[-1]

    @property
    def count(self) -> int:
        return len(self.frames)

    @property
    def missing(self) -> list[int]:
        """Numbers between the first and the last frame that have no file."""
        present = set(self.frames)
        return [number for number in range(self.first, self.last + 1) if number not in present]

    @property
    def pattern(self) -> str:
        """The name as ffmpeg wants it: "img_seq.%04d.png"."""
        number = f"%0{self.padding}d" if self.padding else "%d"
        return self.prefix.replace("%", "%%") + number + self.suffix

    @property
    def pattern_path(self) -> str:
        return str(self.folder / self.pattern)

    def file(self, frame: int) -> Path:
        """The file of frame `frame` (whether it exists or not)."""
        number = str(frame).zfill(self.padding) if self.padding else str(frame)
        return self.folder / f"{self.prefix}{number}{self.suffix}"

    @property
    def name(self) -> str:
        """For people: "img_seq.[0001-0210].png"."""
        first = str(self.first).zfill(self.padding) if self.padding else str(self.first)
        last = str(self.last).zfill(self.padding) if self.padding else str(self.last)
        return f"{self.prefix}[{first}-{last}]{self.suffix}"

    def missing_text(self, limit: int = 6) -> str:
        """"57", "57, 58, 120 and 9 more" — "" when nothing is missing."""
        missing = self.missing
        if not missing:
            return ""
        shown = ", ".join(str(number) for number in missing[:limit])
        return shown + (f" and {len(missing) - limit} more" if len(missing) > limit else "")


def find_sequences(folder: str | Path, min_frames: int = 2) -> list[ImageSequence]:
    """The image sequences in `folder` (not its sub-folders), longest first.
    Files that aren't pictures, and numbered pictures standing alone, are left out."""
    folder = Path(folder)
    try:
        names = [entry.name for entry in os.scandir(folder) if entry.is_file()]
    except OSError:
        return []
    groups: dict[tuple, list[tuple[str, int]]] = {}
    for name in names:
        match = _NUMBERED.match(name)
        if match is None or match.group(3).lower() not in IMAGE_SUFFIXES:
            continue
        prefix, digits, suffix = match.groups()
        groups.setdefault((prefix, suffix), []).append((digits, int(digits)))

    sequences = []
    for (prefix, suffix), members in groups.items():
        widths = {len(digits) for digits, _number in members}
        if len(widths) == 1:
            split = {next(iter(widths)): members}
        elif not any(digits.startswith("0") and len(digits) > 1 for digits, _number in members):
            split = {0: members}  # 1, 2, ... 10, 11: one sequence that isn't padded
        else:
            split = {}  # mixed: "0001" and "10001" are different sequences
            for digits, number in members:
                split.setdefault(len(digits), []).append((digits, number))
        for padding, part in split.items():
            numbers = tuple(sorted({number for _digits, number in part}))
            if len(numbers) >= min_frames:
                sequences.append(ImageSequence(folder, prefix, suffix, padding, numbers))
    return sorted(sequences, key=lambda sequence: (-sequence.count, sequence.name))


def sequence_of(path: str | Path) -> ImageSequence | None:
    """The sequence the picture `path` is a frame of, or None if it stands alone."""
    path = Path(path)
    match = _NUMBERED.match(path.name)
    if match is None:
        return None
    prefix, digits, suffix = match.groups()
    for sequence in find_sequences(path.parent):
        if (sequence.prefix, sequence.suffix) == (prefix, suffix) and int(digits) in sequence.frames \
                and sequence.padding in (0, len(digits)):
            return sequence
    return None
