# core/batch/frames.py
"""Frames written the way people write them: "1-120", "1, 20, 78, 300", "1 20 78", "1-100x5"
(every 5th), "1..10", "10-1" (backwards is taken as 1-10). Whole frames only."""
import re

MAX_FRAMES = 100_000
_PART = re.compile(r"(-?\d+)\s*(?:(?:\.\.|-)\s*(-?\d+)(?:\s*x\s*(\d+))?)?", re.IGNORECASE)


class FramesError(ValueError):
    """The text isn't a frame list; the message says what is wrong, for the user."""


def parse_frames(text: str) -> list[int]:
    """The frame numbers `text` stands for, in the order written, each once."""
    text = (text or "").strip()
    if not text:
        raise FramesError("Say which frames: 1-120, or 1, 20, 78.")
    frames, seen, position = [], set(), 0
    for match in _PART.finditer(text):
        between = text[position:match.start()]
        if between.strip(" ,;\t"):
            raise FramesError(f"“{between.strip()}” isn't a frame or a range (1-120, 1-100x5).")
        position = match.end()
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) is not None else first
        step = int(match.group(3) or 1)
        if step < 1:
            raise FramesError(f"“{match.group(0)}”: the step must be 1 or more.")
        if last < first:
            first, last = last, first
        if (last - first) // step + len(frames) > MAX_FRAMES:
            raise FramesError(f"More than {MAX_FRAMES} frames.")
        for frame in range(first, last + 1, step):
            if frame not in seen:
                seen.add(frame)
                frames.append(frame)
    rest = text[position:]
    if rest.strip(" ,;\t") or not frames:
        raise FramesError(f"“{rest.strip() or text}” isn't a frame or a range (1-120, 1-100x5).")
    return frames


def format_frames(frames) -> str:
    """The shortest way to write `frames` back: "1-10, 20, 30-34"."""
    frames = sorted(set(int(frame) for frame in frames))
    parts, start = [], None
    for index, frame in enumerate(frames):
        if start is None:
            start = frame
        following = frames[index + 1] if index + 1 < len(frames) else None
        if following != frame + 1:
            parts.append(str(start) if start == frame else f"{start}-{frame}")
            start = None
    return ", ".join(parts)
