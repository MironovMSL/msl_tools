import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.windows.frameless_mixin import FramelessWindowMixin


class FramelessMainWindow(FramelessWindowMixin, qt.QtWidgets.QMainWindow):
    """Frameless QMainWindow with a custom title bar, drag/resize, and
    minimize/maximize/restore.

    The custom header hosts the title plus optional nav buttons and any widgets
    added via `add_header_widget()` (theme switcher, search, etc.). Below the
    header sits a nested QMainWindow used purely as an internal "body" — this is
    what lets setMenuBar()/addToolBar()/setStatusBar()/setCentralWidget() keep
    working exactly like on a normal QMainWindow, without reimplementing that
    layout machinery ourselves.

    Contains no DCC-specific logic — parenting to Maya (or any host) is done by
    the caller when instantiating.
    """

    def __init__(self, *, title: str = "", width: int = 960, height: int = 640,
                 show_close_button: bool = True, show_minimize_button: bool = True,
                 show_maximize_button: bool = True, parent=None):
        super().__init__(parent)
        self._init_frameless_state()
        self.resize(width, height)
        self._build_base_ui(title, show_close_button, show_minimize_button, show_maximize_button)

    def _build_base_ui(self, title: str, show_close_button: bool,
                        show_minimize_button: bool, show_maximize_button: bool) -> None:
        shell = qt.QtWidgets.QWidget()
        shell_layout = qt.QtWidgets.QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self._build_frameless_chrome(
            shell_layout, title,
            show_close_button=show_close_button,
            show_minimize_button=show_minimize_button,
            show_maximize_button=show_maximize_button,
        )

        self._body = qt.QtWidgets.QMainWindow()
        self._body.setWindowFlags(qt.QtCore.Qt.WindowType.Widget)
        shell_layout.addWidget(self._body)

        # Bypass our own setCentralWidget() override below — this sets the outer
        # shell (header + body) as the real QMainWindow central widget, once.
        qt.QtWidgets.QMainWindow.setCentralWidget(self, shell)

    # --- Delegate the standard QMainWindow API to the inner body, so callers
    # can use setMenuBar/addToolBar/setStatusBar/setCentralWidget as usual ---

    def setMenuBar(self, menu_bar: qt.QtWidgets.QMenuBar) -> None:
        self._body.setMenuBar(menu_bar)

    def menuBar(self) -> qt.QtWidgets.QMenuBar:
        return self._body.menuBar()

    def addToolBar(self, *args, **kwargs):
        return self._body.addToolBar(*args, **kwargs)

    def setStatusBar(self, status_bar: qt.QtWidgets.QStatusBar) -> None:
        self._body.setStatusBar(status_bar)

    def statusBar(self) -> qt.QtWidgets.QStatusBar:
        return self._body.statusBar()

    def setCentralWidget(self, widget: qt.QtWidgets.QWidget) -> None:
        self._body.setCentralWidget(widget)

    def centralWidget(self) -> qt.QtWidgets.QWidget:
        return self._body.centralWidget()


if __name__ == '__main__':
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        window = FramelessMainWindow(title="FramelessMainWindow")

        menu_bar = qt.QtWidgets.QMenuBar()
        menu_bar.addMenu("File")
        menu_bar.addMenu("Edit")
        window.setMenuBar(menu_bar)

        window.setCentralWidget(qt.QtWidgets.QPushButton("body content"))
        window.setStatusBar(qt.QtWidgets.QStatusBar())
        window.show()