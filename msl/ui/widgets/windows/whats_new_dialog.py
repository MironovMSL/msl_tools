# ui/widgets/windows/whats_new_dialog.py
import html
import re
import threading
from typing import Callable, Sequence

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.version.release_notes import ReleaseNote, split_blocks
from msl_tools.msl.core.version.version import Version
from msl_tools.msl.ui.process_launcher.process_launcher import ProcessLauncher
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.widgets.atoms.progress import BaseProgressBar, ProgressState
from msl_tools.msl.ui.widgets.atoms.surfaces import StableScrollArea
from msl_tools.msl.ui.widgets.windows.confirm_dialog import ConfirmDialog
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


# Inline Markdown -> Qt rich text. Code spans get a real monospace face: Qt's own
# Markdown rendering falls back to a cramped system fixed font.
_CODE_FONT = "'Cascadia Mono', 'JetBrains Mono', 'Consolas', monospace"
_INLINE_RULES = (
    (re.compile(r"`([^`]+)`"), rf'<span style="font-family: {_CODE_FONT};">\1</span>'),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)"), r'<a href="\2">\1</a>'),
    (re.compile(r"\*\*(.+?)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"<i>\1</i>"),
)


def _inline_html(text: str) -> str:
    """Escapes `text` and renders its inline Markdown (`code`, [links](url),
    **bold**, *italic*) as Qt rich text."""
    result = html.escape(text, quote=False)
    for pattern, replacement in _INLINE_RULES:
        result = pattern.sub(replacement, result)
    return result


class _ReleaseBlock(qt.QtWidgets.QWidget):
    """Private: one release — date, a version pill (click: the release's page
    on GitHub), its name, then the notes cut into sections: a small caps
    heading over bullet rows / paragraphs laid out here (not by Qt's Markdown
    lists, whose indent and bullets can't be styled). With `installable`, a
    quiet "Install this version" button sits left of the pill
    (install_requested)."""

    BULLET_WIDTH = 14
    BULLET = "\u2022"

    install_requested = qt.QtCore.Signal(object)  # this block's ReleaseNote

    def __init__(self, note: ReleaseNote, state: str, installable: bool = False, parent=None):
        super().__init__(parent)
        self.install_button: qt.QtWidgets.QPushButton | None = None
        date_label = qt.QtWidgets.QLabel(note.date_text or note.tag)
        date_label.setObjectName("releaseDate")

        suffix = {"current": "  \u00b7  installed", "new": "  \u00b7  new"}.get(state, "")
        version_button = qt.QtWidgets.QPushButton(note.version + suffix)
        version_button.setObjectName("releaseVersion")
        version_button.setProperty("state", state)  # widgets.qss: pill color
        version_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        if note.url:
            version_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            version_button.setToolTip("Open this release on GitHub")
            version_button.clicked.connect(lambda: ProcessLauncher.open_url_in_browser(note.url))

        header = qt.QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(date_label)
        header.addStretch()
        if installable:
            self.install_button = qt.QtWidgets.QPushButton("Install this version")
            self.install_button.setObjectName("releaseInstall")
            self.install_button.setFlat(True)
            self.install_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            self.install_button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            self.install_button.clicked.connect(lambda: self.install_requested.emit(note))
            header.addWidget(self.install_button)
        header.addWidget(version_button)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addLayout(header)

        if note.display_title:
            title_label = qt.QtWidgets.QLabel(note.display_title)
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
                layout.addSpacing(7)
                layout.addWidget(heading_label)
                layout.addSpacing(1)
            for kind, content in split_blocks(text):
                layout.addLayout(self._block_row(kind, content))

    def _block_row(self, kind: str, content: str) -> qt.QtWidgets.QLayout:
        text_label = qt.QtWidgets.QLabel(_inline_html(content))
        text_label.setObjectName("releaseBody")
        text_label.setTextFormat(qt.QtCore.Qt.TextFormat.RichText)
        text_label.setWordWrap(True)
        text_label.setOpenExternalLinks(True)
        text_label.setTextInteractionFlags(qt.QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)

        row = qt.QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        if kind == "bullet":
            bullet_label = qt.QtWidgets.QLabel(self.BULLET)
            bullet_label.setObjectName("releaseBullet")
            bullet_label.setFixedWidth(self.BULLET_WIDTH)
            row.addWidget(bullet_label, 0, qt.QtCore.Qt.AlignmentFlag.AlignTop)
        row.addWidget(text_label, 1)
        return row


class WhatsNewDialog(FramelessDialog):
    """"What's new": the application's release notes, one block per published
    release, newest first — what changed with each VERSION, not every commit.

    The notes are whatever each release's description says on GitHub
    (core/version/release_notes.py); a description written with Markdown
    headings ("### New", "### Fixed") shows as labelled sections. The
    installed version's block is marked "installed", newer ones "new" — and
    when there are newer ones, a banner on top says which version is
    available, with a button: "Update now" when the caller can install it
    (`update_handler`), else "Get it on GitHub" (the release's page).
    With `can_install`, every OTHER release it accepts gets an "Install this
    version" button too — also older ones, to go back while a fix is on its
    way (asked first: ConfirmDialog).

    Storage- and network-agnostic: the caller passes `fetch_releases`, a
    callable returning the releases (or None on failure). It runs on a
    background thread — it is a network request — while the dialog shows
    "Loading…"; a failure shows a message with Retry.

    Updating is the caller's too: `update_handler(note, progress)` downloads
    and prepares release `note` (blocking — it runs on a background thread
    while the banner shows a progress bar; an exception's text is shown as
    the reason it failed, with the button back as "Try again"). When it
    returns, the dialog closes with `update_prepared` set to that release —
    the caller then restarts the application into it.

    Colors / fonts: ui/theme/widgets.qss (QLabel#releaseDate, QPushButton
    #releaseVersion[state], #releaseSection, #releaseBody, #releaseBullet,
    QFrame#updateBanner[state], #updateDetail[state], #whatsNewStatus,
    QPushButton#releaseInstall).

    Usage:
        prepared = WhatsNewDialog.show_for(window, fetch_releases=version_manager.get_releases,
                                           current_version="0.1.0",
                                           releases_url="https://github.com/.../releases",
                                           update_handler=prepare)  # -> ReleaseNote | None
    """

    WIDTH = 520
    HEIGHT = 560

    _loaded = qt.QtCore.Signal(object)               # list[ReleaseNote] | None, from the fetch thread
    _update_progress = qt.QtCore.Signal(str, float, float)  # stage, done, total — from the update thread
    _update_finished = qt.QtCore.Signal(str)         # "" = prepared, else why it failed

    def __init__(self, fetch_releases: Callable[[], Sequence[ReleaseNote] | None],
                 current_version: str = "", releases_url: str = "",
                 title: str = "What’s new", update_handler: Callable | None = None,
                 update_blocked_reason: str = "", notice: str = "",
                 can_install: Callable[[ReleaseNote], bool] | None = None, parent=None):
        """
        Args:
            fetch_releases: Returns the releases, newest first, or None when
                they couldn't be loaded. Called on a background thread.
            current_version: The installed version ("1.2.3"), to mark its block.
            releases_url: The releases page, for the "All releases on GitHub"
                link ("" = no link).
            title: Window title.
            update_handler: update_handler(note, progress) prepares release
                `note` for installing; progress(stage, done, total) with
                stage "download" (bytes, total 0 = unknown) or "check".
                None = this application can't update itself.
            update_blocked_reason: Why it can't, shown under the banner's
                text ("" = say nothing). Ignored when a handler is given.
            notice: What just happened, for the banner: "Updated to 0.2.0"
                (alone, in the success tone) or, when a newer version exists,
                "Back on version 0.1.1" in front of the offer to update.
            can_install: can_install(note) -> may this release be installed
                by `update_handler`? Those that may (other than the
                installed one) get an "Install this version" button.
                None = only the newest release, through the banner.
            parent: Widget the dialog belongs to.
        """
        super().__init__(title=title, width=self.WIDTH, height=self.HEIGHT,
                         show_minimize_button=False, show_maximize_button=False,
                         show_theme_toggle=False, parent=parent)
        self._fetch_releases = fetch_releases
        self._current_version = current_version
        self._releases_url = releases_url
        self._update_handler = update_handler
        self._update_blocked_reason = "" if update_handler else update_blocked_reason
        self._notice = notice
        self._can_install = can_install if update_handler else None
        self._latest: ReleaseNote | None = None
        self._target: ReleaseNote | None = None  # the release being installed / that failed to
        self._install_buttons: list[qt.QtWidgets.QPushButton] = []
        self._updating = False
        self.update_prepared: ReleaseNote | None = None  # set when the handler finished: restart into it
        self._build()
        self._loaded.connect(self._on_loaded)
        self._update_progress.connect(self._on_update_progress)
        self._update_finished.connect(self._on_update_finished)

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

        # "A newer version is out": shown above the list when one is.
        self._update_label = qt.QtWidgets.QLabel()
        self._update_label.setObjectName("updateText")
        self._update_label.setWordWrap(True)
        self._update_button = qt.QtWidgets.QPushButton(self.UPDATE_TEXT if self._update_handler else self.OPEN_TEXT)
        self._update_button.setProperty("primary", True)
        self._update_button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._update_button.clicked.connect(self._on_update_clicked)
        self._update_url = ""
        # Under the text: why updating isn't possible here / download progress / why it failed.
        self._update_detail = qt.QtWidgets.QLabel(self._update_blocked_reason)
        self._update_detail.setObjectName("updateDetail")
        self._update_detail.setWordWrap(True)
        if not self._update_blocked_reason:
            self._update_detail.hide()  # not setVisible(True): parentless here, it would flash as a window
        self._update_progress_bar = BaseProgressBar()
        self._update_progress_bar.hide()

        self._update_banner = qt.QtWidgets.QFrame()
        self._update_banner.setObjectName("updateBanner")
        text_layout = qt.QtWidgets.QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self._update_label)
        text_layout.addWidget(self._update_detail)
        top_layout = qt.QtWidgets.QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addLayout(text_layout, 1)
        top_layout.addWidget(self._update_button)
        banner_layout = qt.QtWidgets.QVBoxLayout(self._update_banner)
        banner_layout.setContentsMargins(12, 8, 8, 8)
        banner_layout.setSpacing(6)
        banner_layout.addLayout(top_layout)
        banner_layout.addWidget(self._update_progress_bar)
        self._update_banner.hide()

        list_page = qt.QtWidgets.QWidget()
        list_page_layout = qt.QtWidgets.QVBoxLayout(list_page)
        list_page_layout.setContentsMargins(0, 0, 0, 0)
        list_page_layout.setSpacing(8)
        list_page_layout.addWidget(self._update_banner)
        list_page_layout.addWidget(self._scroll, 1)
        self._list_page = list_page

        self._pages = qt.QtWidgets.QStackedWidget()
        self._pages.addWidget(self._status_page)
        self._pages.addWidget(self._list_page)
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
        self._install_buttons = []
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
            state = self._state_of(note)
            installable = state != "current" and self._can_install is not None and bool(self._can_install(note))
            block = _ReleaseBlock(note, state, installable)
            block.install_requested.connect(self._on_install_requested)
            if block.install_button is not None:
                self._install_buttons.append(block.install_button)
            self._list_layout.addWidget(block)
        self._list_layout.addStretch()

        newer = [note for note in releases if self._state_of(note) == "new"]
        if newer:
            self._latest = latest = newer[0]  # releases come newest first
            have = f" \u2014 you have {self._current_version}" if self._current_version else ""
            if self._notice:  # "Back on version X": say so first, the newer one after it
                self._update_label.setText(f"<b>{html.escape(self._notice)}.</b> "
                                           f"Version {latest.version} is the newest.")
            else:
                self._update_label.setText(f"<b>Version {latest.version} is available</b>{have}.")
            self._update_url = latest.url or self._releases_url
            self._update_button.setVisible(bool(self._update_handler or self._update_url))
            self._set_banner_state("")
        elif self._notice:
            self._update_label.setText(f"<b>{html.escape(self._notice)}</b>")
            self._update_button.hide()
            self._update_detail.hide()
            self._set_banner_state("success")
        self._update_banner.setVisible(bool(newer or self._notice))
        self._pages.setCurrentWidget(self._list_page)

    def _set_banner_state(self, state: str) -> None:
        if self._update_banner.property("state") != state:
            self._update_banner.setProperty("state", state)  # widgets.qss: QFrame#updateBanner[state]
            repolish(self._update_banner)

    # --- updating -----------------------------------------------------------------

    UPDATE_TEXT = "Update now"
    OPEN_TEXT = "Get it on GitHub"
    RETRY_TEXT = "Try again"

    def _on_update_clicked(self) -> None:
        """The banner's button: the newest release — or, after a failure, the same release again."""
        target = self._target or self._latest
        if self._update_handler is None or target is None:
            if self._update_url:
                ProcessLauncher.open_url_in_browser(self._update_url)
            return
        self._start_install(target)

    def _on_install_requested(self, note: ReleaseNote) -> None:
        """A release's own "Install this version". Going back to an older one is asked first."""
        if self._updating:
            return
        if self._state_of(note) != "new":
            choice = ConfirmDialog.ask(
                self, "Install an older version", f"Go back to version {note.version}?",
                details="MSL Tools will restart. Your settings are kept. "
                        "You can return to the newest version from here at any time.",
                choices=[("install", f"Go back to {note.version}"), ("cancel", "Cancel")], kind="warning")
            if choice != "install":
                return
        self._start_install(note)

    def _start_install(self, note: ReleaseNote) -> None:
        if self._updating:
            return
        self._updating = True
        self._target = note
        for button in self._install_buttons:
            button.setEnabled(False)
        self._set_banner_state("")
        self._update_label.setText(f"<b>Installing version {note.version}\u2026</b>")
        self._update_banner.show()
        self._update_button.show()
        self._update_button.setEnabled(False)
        self._update_button.setText("Installing\u2026")
        self._set_detail("Connecting\u2026")
        self._update_progress_bar.set_state(ProgressState.NORMAL)
        self._update_progress_bar.set_indeterminate(True)
        self._update_progress_bar.show()
        handler = self._update_handler

        def report(stage: str, done: int = 0, total: int = 0) -> None:
            try:
                self._update_progress.emit(stage, float(done), float(total))
            except RuntimeError:
                pass  # the dialog was closed and deleted meanwhile

        def run() -> None:
            try:
                handler(note, report)
                message = ""
            except Exception as error:
                message = str(error) or "The update could not be prepared."
            try:
                self._update_finished.emit(message)  # queued to the GUI thread
            except RuntimeError:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _on_update_progress(self, stage: str, done: float, total: float) -> None:
        megabyte = 1024 * 1024
        if stage == "download" and total > 0:
            if self._update_progress_bar.maximum() == 0:
                self._update_progress_bar.set_indeterminate(False)
            self._update_progress_bar.set_progress(int(done / total * 100))
            self._set_detail(f"Downloading\u2026 {done / megabyte:.1f} of {total / megabyte:.1f} MB")
        elif stage == "download":
            self._set_detail(f"Downloading\u2026 {done / megabyte:.1f} MB")
        else:
            self._set_detail("Checking the download\u2026")

    def _on_update_finished(self, error_message: str) -> None:
        self._updating = False
        self._update_progress_bar.set_indeterminate(False)
        if error_message:
            version = self._target.version if self._target is not None else ""
            self._update_label.setText(f"<b>Version {version} was not installed.</b>")
            self._update_progress_bar.hide()
            self._update_button.setEnabled(True)
            self._update_button.setText(self.RETRY_TEXT)
            self._set_detail(error_message, "error")
            for button in self._install_buttons:
                button.setEnabled(True)
            return
        self._update_progress_bar.set_progress(self._update_progress_bar.maximum())
        self._set_detail("Restarting MSL Tools\u2026")
        if self.isVisible():  # closed meanwhile = the user walked away: nothing restarts behind their back
            self.update_prepared = self._target
            self.accept()

    def _set_detail(self, text: str, state: str = "") -> None:
        self._update_detail.setText(text)
        self._update_detail.setVisible(bool(text))
        if self._update_detail.property("state") != state:
            self._update_detail.setProperty("state", state)  # widgets.qss: QLabel#updateDetail[state]
            repolish(self._update_detail)

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
    def show_for(cls, parent, fetch_releases, current_version: str = "", releases_url: str = "",
                 update_handler: Callable | None = None, update_blocked_reason: str = "",
                 notice: str = "", can_install: Callable[[ReleaseNote], bool] | None = None) -> ReleaseNote | None:
        """Opens the dialog modally over `parent`'s window, which is blurred
        behind it if it's a frameless window (like ConfirmDialog.ask()).

        Returns:
            The release `update_handler` prepared (restart into it), else None.
        """
        dialog = cls(fetch_releases, current_version, releases_url, update_handler=update_handler,
                     update_blocked_reason=update_blocked_reason, notice=notice, can_install=can_install,
                     parent=parent)
        window = parent.window() if parent is not None else None
        blur = getattr(window, "set_blurred", None)
        if blur is not None:
            blur(True)
        try:
            dialog.exec()
        finally:
            if blur is not None:
                blur(False)
        return dialog.update_prepared


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
