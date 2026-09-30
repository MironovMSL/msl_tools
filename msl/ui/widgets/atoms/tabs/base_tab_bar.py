# ui/widgets/atoms/tabs/base_tab_bar.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property


class BaseTabBar(qt.QtWidgets.QTabBar):
    """Underline tab bar whose accent indicator SLIDES to the new tab (and
    stretches to its width) instead of jumping — QSS can't animate, so the
    indicator is painted here, on top of the QSS-styled tabs.

    The indicator sits under the tab's text (INDICATOR_INSET in from the
    tab's edges, matching the QSS side padding), is INDICATOR_HEIGHT tall
    with rounded ends, and takes its color from the `indicatorColor` Qt
    property (ui/theme/widgets.qss). The tabs keep base.qss's transparent
    2px bottom border as its room; widgets.qss turns off the static QSS
    underline for BaseTabBar.

    Use through BaseTabWidget, or `tab_widget.setTabBar(BaseTabBar())`
    before adding tabs.
    """

    INDICATOR_HEIGHT = 2
    INDICATOR_INSET = 10
    ANIMATION_MS = 220

    indicatorColor = color_property("_indicator_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._indicator_color = qt.QtGui.QColor(ThemeRegistry.fallback().accent)  # until QSS applies
        self._indicator = qt.QtCore.QRectF()
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_indicator_moved)
        self.currentChanged.connect(self._slide_to)

    def _target(self, index: int) -> qt.QtCore.QRectF:
        if index < 0:
            return qt.QtCore.QRectF()
        tab = qt.QtCore.QRectF(self.tabRect(index))  # QRectF.bottom() = y + height (not QRect's y + height - 1)
        return qt.QtCore.QRectF(tab.left() + self.INDICATOR_INSET, tab.bottom() - self.INDICATOR_HEIGHT,
                                max(tab.width() - 2 * self.INDICATOR_INSET, 0.0), self.INDICATOR_HEIGHT)

    def _slide_to(self, index: int) -> None:
        target = self._target(index)
        if self._indicator.isEmpty() or not self.isVisible():
            self._snap()  # first tab / not on screen yet: nothing to slide from
            return
        self._animation.stop()
        self._animation.setStartValue(qt.QtCore.QRectF(self._indicator))
        self._animation.setEndValue(target)
        self._animation.start()

    def _snap(self) -> None:
        self._animation.stop()
        self._indicator = self._target(self.currentIndex())
        self.update()

    def _on_indicator_moved(self, rect) -> None:
        self._indicator = qt.QtCore.QRectF(rect)
        self.update()

    # Tab geometry changes (resize, font / theme, tabs added): follow it — mid-slide
    # by retargeting, otherwise by jumping straight there.
    def _follow_layout(self) -> None:
        if self._animation.state() == qt.QtCore.QAbstractAnimation.State.Running:
            self._animation.setEndValue(self._target(self.currentIndex()))
        else:
            self._snap()

    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        self._follow_layout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._follow_layout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._snap()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._indicator.isEmpty():
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._indicator_color)
        radius = self.INDICATOR_HEIGHT / 2
        painter.drawRoundedRect(self._indicator, radius, radius)
        painter.end()


class BaseTabWidget(qt.QtWidgets.QTabWidget):
    """QTabWidget with a BaseTabBar (sliding indicator), in document mode
    (no frame around the pages) — the look base.qss styles tabs for."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(BaseTabBar(self))  # before any addTab()
        self.setDocumentMode(True)


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        tabs = BaseTabWidget()
        for title in ("Variables", "userSetup", "A much longer tab"):
            tabs.addTab(qt.QtWidgets.QLabel(f"{title} page"), title)
        tabs.setFixedHeight(120)
        dialog.add_case("BaseTabWidget (click the tabs)", tabs)
        dialog.show()
