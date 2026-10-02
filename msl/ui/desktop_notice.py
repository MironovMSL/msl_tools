# ui/desktop_notice.py
import msl_tools.msl.ui.qt_bindings as qt


class DesktopNotice(qt.QtCore.QObject):
    """A notice from the operating system — the toast in the corner of the
    screen — for telling the user that long work is over while they look at
    something else.

        notice = DesktopNotice(icon, parent=window)
        notice.clicked.connect(...)            # the user clicked the toast
        notice.show("MSL Tools · Media", "shot_small.mp4 is ready")

    The system only shows messages of a tray icon, so one is put into the
    tray for as long as the notice is up (TRAY_MS), then taken away again.
    Nothing is created until the first show().

    Signals:
        clicked() — the notice was clicked.
    """

    SHOWN_MS = 8000
    TRAY_MS = 12000

    clicked = qt.QtCore.Signal()

    def __init__(self, icon: qt.QtGui.QIcon | None = None, parent=None):
        super().__init__(parent)
        self._icon = icon if icon is not None else qt.QtGui.QIcon()
        self._tray: qt.QtWidgets.QSystemTrayIcon | None = None
        self._hide_timer = qt.QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self.TRAY_MS)
        self._hide_timer.timeout.connect(self._hide)

    @staticmethod
    def available() -> bool:
        tray = qt.QtWidgets.QSystemTrayIcon
        return tray.isSystemTrayAvailable() and tray.supportsMessages()

    def show(self, title: str, text: str) -> bool:
        """Shows the notice. False where the system can't show one."""
        if not self.available():
            return False
        if self._tray is None:
            self._tray = qt.QtWidgets.QSystemTrayIcon(self._icon, self)
            self._tray.setToolTip(title)
            self._tray.messageClicked.connect(self.clicked)
            self._tray.activated.connect(lambda _reason: self.clicked.emit())
        self._tray.show()
        self._tray.showMessage(title, text, self._icon, self.SHOWN_MS)
        self._hide_timer.start()
        return True

    def _hide(self) -> None:
        if self._tray is not None:
            self._tray.hide()
