"""Release notes as published on GitHub Releases — parsing only, no I/O.

A release's notes are whatever was typed into the release's description on
GitHub (Markdown). `split_sections()` cuts that text at its headings, so a UI
can show "New / Improved / Fixed" blocks: write the description like

    ### New
    - Desktop hub with a tool sidebar
    ### Fixed
    - Open folder button

Text before the first heading (or a description with no headings at all)
comes back as one section with no title.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime

from msl_tools.msl.core.version.version import Version

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
# A release name's leading version ("v0.1.0 — Desktop hub", "0.1.0: ...") and the separator after it.
_TITLE_VERSION = re.compile(r"^\s*v?\d+(?:\.\d+){1,2}\S*\s*[\u2014\u2013:|-]*\s*", re.IGNORECASE)
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


@dataclass(frozen=True)
class ReleaseNote:
    """One published release.

    Attributes:
        version: "1.2.3" (the tag without its "v").
        tag: The tag as published ("v1.2.3").
        title: The release's name on GitHub ("" if it has none).
        published: ISO timestamp from GitHub ("2026-07-08T13:48:44Z"), or "".
        body: The description (Markdown), newlines normalized to "\\n".
        url: The release's page on GitHub.
        prerelease: Marked as a pre-release on GitHub.
    """

    version: str
    tag: str
    title: str
    published: str
    body: str
    url: str
    prerelease: bool = False

    @property
    def date_text(self) -> str:
        """`published` as "July 8, 2026" ("" when missing or unparseable)."""
        try:
            moment = datetime.strptime(self.published[:10], "%Y-%m-%d")
        except ValueError:
            return ""
        return f"{_MONTHS[moment.month - 1]} {moment.day}, {moment.year}"

    @property
    def display_title(self) -> str:
        """`title` without a leading version number — "v0.1.0 — Desktop hub"
        reads "Desktop hub"; a name that is only the version reads ""
        (the version is shown separately anyway)."""
        return _TITLE_VERSION.sub("", self.title).strip()

    def sections(self) -> list[tuple[str, str]]:
        """The body cut at its headings: [(heading or "", markdown), ...]."""
        return split_sections(self.body)


def parse_releases(content: str) -> list[ReleaseNote]:
    """Releases from the GitHub API's JSON (GET .../releases), newest first.
    Drafts and entries without a usable version tag are skipped.

    Raises:
        ValueError: `content` is not the expected JSON list.
    """
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Release list is not valid JSON: {error}") from error
    if not isinstance(data, list):
        raise ValueError("Release list is not a JSON array.")

    notes = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        tag = entry.get("tag_name") or ""
        try:
            version = Version.parse(tag)
        except ValueError:
            continue
        notes.append(ReleaseNote(
            version=version,
            tag=tag,
            title=(entry.get("name") or "").strip(),
            published=entry.get("published_at") or "",
            body=(entry.get("body") or "").replace("\r\n", "\n").replace("\r", "\n").strip(),
            url=entry.get("html_url") or "",
            prerelease=bool(entry.get("prerelease")),
        ))
    notes.sort(key=lambda note: Version.parse(note.version, as_tuple=True), reverse=True)
    return notes


def split_sections(body: str) -> list[tuple[str, str]]:
    """Cuts Markdown `body` at its headings: [(heading or "", text), ...].
    Sections with no text are dropped; a body without headings is one
    untitled section."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.split("\n"):
        match = _HEADING.match(line)
        if match:
            sections.append((match.group(1), []))
        else:
            sections[-1][1].append(line)
    result = [(heading, "\n".join(lines).strip()) for heading, lines in sections]
    return [(heading, text) for heading, text in result if text]


def split_blocks(text: str) -> list[tuple[str, str]]:
    """Cuts a section's Markdown into blocks for a UI to lay out:
    [("bullet" | "paragraph", text), ...]. A list item or paragraph that
    continues on the next line(s) is joined into one block; blank lines end
    a block. Inline Markdown (**bold**, `code`, links) is left in the text."""
    blocks: list[list[str]] = []   # [kind, text]
    open_block = False
    for line in text.split("\n"):
        if not line.strip():
            open_block = False
            continue
        bullet = _BULLET.match(line)
        if bullet:
            blocks.append(["bullet", bullet.group(1).strip()])
            open_block = True
        elif open_block:
            blocks[-1][1] += " " + line.strip()
        else:
            blocks.append(["paragraph", line.strip()])
            open_block = True
    return [(kind, content) for kind, content in blocks]
