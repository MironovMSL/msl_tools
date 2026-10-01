# ui/widgets/windows/whats_new_dialog.py
import threading
from typing import Callable, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.release_notes import ReleaseNote
from msl_tools.msl.core.version.version import Version
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class _ReleaseBlock(qt.QtWidgets.QWidget):
    """Private: one release — date, version pill, then its notes cut into
    sections (a small caps heading over a Markdown block each)."""

    def __init__(self, note: ReleaseNote, state: str, parent=None):
        super().__init__(parent)
        date_label = qt.QtWidgets.QLabel(note.date_text or note.tag)
        date_label.setObjectName("releaseDate")

        version_label = qt.QtWidgets.QLabel(note.version + {"current": "  ·  installed", "new": "  ·  new"}.get(state, ""))
        version_label.setObjectName("releaseVersion")
        version_label.setProperty("state", state)  # widgets.qss: pill color

        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(date_label)
        header.addStretch()
        header.addWidget(version_label)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(header)

        if note.title and note.title not in (note.tag, note.version):
            title_label = qt.QtWidgets.QLabel(note.title)
            title_label.setObjectName("releaseTitle")
            title_label.setWordWrap(True)
            layout.addWidget(title_label)

        sections = note.sections()
        if not sections:
            empty = qt.QtWidgets.QLabel("No notes for this release.")
            empty.setObjectName("releaseTitle")
            layout.addWidget(empty)
        for heading, text in sections:
            if heading:
                heading_label = qt.QtWidgets.QLabel(heading.upper())
                heading_label.setObjectName("releaseSection")
                font = heading_label.font()
                font.setLetterSpacing(qt.QtGui.QFont.SpacingType.AbsoluteSpacing, 0.6)
                heading_label.setFont(font)
                layout.addSpacing(6)
                layout.addWidget(heading_label)
            body_label = qt.QtWidgets.QLabel()
            body_label.setObjectName("releaseBody")
            body_label.setTextFormat(qt.QtCore.Qt.TextFormat.MarkdownText)
            body_label.setText(text)
            body_label.setWordWrap(True)
            body_label.setOpenExternalLinks(True)
            body_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
            layout.addWidget(body_label)


class WhatsNewDialog(FramelessDialog):
    """"What's new": the application's release notes, one block per published
    release, newest first — what changed with each VERSION, not every commit.

    The notes are whatever each release's description says on GitHub
    (core/version/release_notes.py); a description written with Markdown
    headings ("### New", "### Fixed") shows as labelled sections. The
    installed version's block is marked "installed", newer ones "new".

    Storage- and network-agnostic: the caller passes `fetch_releases`, a
    callable returning the releases (or None on failure). It runs on a
    background thread — it is a network request — while the dialog shows
    "Loading…"; a failure shows a message with Retry.

    Colors / fonts: ui/theme/widgets.qss (QLabel#releaseDate, #releaseVersion
    [state], #releaseSection, #releaseBody, #whatsNewStatus).

    Usage:
        WhatsNewDialog.show_for(window, fetch_releases=version_manager.get_releases,
                                current_version="0.1.0", releases_url="https://github.com/.../releases")
    """

    WIDTH = 520
    HEIGHT = 560

    _loaded = qt.QtCore.Signal(object)  # list[ReleaseNote] | None, from the fetch thread

    def __init__(self, fetch_releases: Callable[[], Sequence[ReleaseNote] | None],
                 current_version: str = "", releases_url: str = "",
                 title: str = "What’s new", parent=None):
        """
        Args:
            fetch_releases: Returns the releases, newest first, or None when
                they couldn't be loaded. Called on a background thread.
            current_version: The installed version ("1.2.3"), to mark its block.
            releases_url: The releases page, for the "All releases on GitHub"
                link ("" = no link).
            title: Window title.
            parent: Widget the dialog belongs to.
        """
        super().__init__(title=title, width=self.WIDTH, height=self.HEIGHT,
                         show_minimize_button=False, show_maximize_button=False,
                         show_theme_toggle=False, parent=parent)
        self._fetch_releases = fetch_releases
        self._current_version = current_version
        self._releases_url = releases_url
        self._build()
        self._loaded.connect(self._on_loaded)

    def _build(self) -> None:
        self._status_label = qt.QtWidgets.QLabel()
        self._status_label.setObjectName("whatsNewStatus")
        self._status_label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._retry_button = qt.QtWidgets.QPushButton("Retry")
        self._retry_button.clicked.connect(self._load)

        self._status_page = qt.QtWidgets.QWidget()
        status_layout = qt.QtWidgets.QVBoxLayout(self._status_page)
        status_layout.addStretch()
        status_layout.addWidget(self._status_label)
        status_layout.addSpacing(8)
        status_layout.addWidget(self._retry_button, 0, qt.QtCore.Qt.AlignmentFlag.AlignHCenter)
        status_layout.addStretch()

        self._list = qt.QtWidgets.QWidget()
        self._list_layout = qt.QtWidgets.QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(4, 4, 8, 4)
        self._list_layout.setSpacing(14)
        self._scroll = StableScrollArea()
        self._scroll.setWidget(self._list)

        self._pages = qt.QtWidgets.QStackedWidget()
        self._pages.addWidget(self._status_page)
        self._pages.addWidget(self._scroll)
        self.add_widget(self._pages)

        if self._releases_url:
            link = qt.QtWidgets.QPushButton("All releases on GitHub")
            link.setFlat(True)
            link.setObjectName("whatsNewLink")
            link.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            link.clicked.connect(lambda: ProcessLauncher.open_url_in_browser(self._releases_url))
            footer = qt.QtWidgets.QHBoxLayout()
            footer.setContentsMargins(0, 6, 0, 0)
            footer.addStretch()
            footer.addWidget(link)
            footer_widget = qt.QtWidgets.QWidget()
            footer_widget.setLayout(footer)
            self.add_widget(footer_widget)

        self.content_surface.content_layout().setContentsMargins(14, 12, 8, 10)

    # --- loading -----------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._list_layout.count() == 0:  # first show: nothing fetched yet (no I/O in the constructor)
            self._load()

    def _load(self) -> None:
        self._show_status("Loading…", retry=False)
        fetch = self._fetch_releases

        def run() -> None:
            try:
                releases = fetch()
            except Exception:
                releases = None
            try:
                self._loaded.emit(releases)  # queued to the GUI thread
            except RuntimeError:
                pass  # the dialog was closed and deleted meanwhile

        # A daemon thread, not a QThread: the dialog can be closed mid-request.
        threading.Thread(target=run, daemon=True).start()

    def _on_loaded(self, releases) -> None:
        if releases is None:
            self._show_status("Couldn’t load the release notes.\nCheck your internet connection.", retry=True)
        elif not releases:
            self._show_status("No releases published yet.", retry=False)
        else:
            self.set_releases(releases)

    def _show_status(self, text: str, retry: bool) -> None:
        self._status_label.setText(text)
        self._retry_button.setVisible(retry)
        self._pages.setCurrentWidget(self._status_page)

    # --- content ------------------------------------------------------------------

    def set_releases(self, releases: Sequence[ReleaseNote]) -> None:
        """Shows `releases` (newest first), replacing what was there."""
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

        for index, note in enumerate(releases):
            if index:
                divider = qt.QtWidgets.QWidget()
                divider.setObjectName("releaseDivider")
                divider.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
                divider.setFixedHeight(1)
                self._list_layout.addWidget(divider)
            self._list_layout.addWidget(_ReleaseBlock(note, self._state_of(note)))
        self._list_layout.addStretch()
        self._pages.setCurrentWidget(self._scroll)

    def _state_of(self, note: ReleaseNote) -> str:
        """"current" for the installed version, "new" for newer ones, else ""."""
        try:
            comparison = Version.compare(note.version, self._current_version)
        except ValueError:
            return ""
        if comparison == Version.EQUAL:
            return "current"
        return "new" if comparison == Version.BIGGER else ""

    @classmethod
    def show_for(cls, parent, fetch_releases, current_version: str = "", releases_url: str = "") -> None:
        """Opens the dialog modally over `parent`'s window, which is blurred
        behind it if it's a frameless window (like ConfirmDialog.ask())."""
        dialog = cls(fetch_releases, current_version, releases_url, parent=parent)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.core.resources import Resources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        playground = ThemedWidgetPlaygroundDialog()
        button = qt.QtWidgets.QPushButton("What’s new…")
        button.clicked.connect(lambda: WhatsNewDialog.show_for(
            playground, Resources().versionManager.get_releases, "0.0.1",
            "https://github.com/MironovMSL/msl_tools/releases"))
        playground.add_case("WhatsNewDialog", button)
        playground.show()
