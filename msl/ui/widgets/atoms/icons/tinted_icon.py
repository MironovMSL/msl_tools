# ui/widgets/atoms/icons/tinted_icon.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property


class TintedIcon(qt.QtWidgets.QWidget):
    """A small one-color icon that is only looked at — not a button.

    The icon is used as a SHAPE and painted in the `iconColor` Qt property,
    which the window stylesheet sets (ui/theme/widgets.qss:
    `TintedIcon { qproperty-iconColor: var(--text-secondary); }`), so it
    follows theme switches like every other icon. Disabled = dimmed.

    For clickable icons use GlyphButton (borderless) or IconPushButton
    (framed) instead. With no icon (asset missing) it paints nothing but
    keeps its size, so a column of them stays aligned.
    """

    DISABLED_OPACITY = 0.4

    iconColor = color_property("_icon_color")

    def __init__(self, icon: "qt.QtGui.QIcon | None" = None, size: int = 14, parent=None):
        super().__init__(parent)
        self._icon = icon if icon is not None and not icon.isNull() else None
        self._icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_secondary)  # until QSS applies
        self.setFixedSize(size, size)

    def set_icon(self, icon: "qt.QtGui.QIcon | None") -> None:
        self._icon = icon if icon is not None and not icon.isNull() else None
        self.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == qt.QtCore.QEvent.Type.EnabledChange:
            self.update()

    def paintEvent(self, event) -> None:
        if self._icon is None:
            return
        painter = qt.QtGui.QPainter(self)
        if not self.isEnabled():
            painter.setOpacity(self.DISABLED_OPACITY)
        painter.drawPixmap(0, 0, tint_icon(self._icon, self.width(), self.devicePixelRatioF(), self._icon_color))
        painter.end()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        for name in ("plugin", "bifrost", "arnold", "xgen", "mash", "usd", "bullet", "redshift", "flow", "lookdevx"):
            dialog.add_case(f"plugins/{name}", TintedIcon(UiResources().iconManager.get_icon(name, sub_folder="plugins"), 20))
        dialog.show()
