# ui/widgets/atoms/buttons/icon_push_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property


class IconPushButton(qt.QtWidgets.QPushButton):
    """A regular framed button (border, hover, pressed — all from the
    base.qss QPushButton rules) showing a one-color icon.

    The icon is used as a SHAPE and tinted with the `iconColor` Qt property,
    set by the window stylesheet (ui/theme/widgets.qss:
    `IconPushButton { qproperty-iconColor: var(--text-primary); }`), so it
    follows theme switches and hot reload like everything else. Use
    GlyphButton instead for borderless, hover-highlighted icon buttons.

    If `icon` is None (asset missing), `fallback_text` is shown instead.
    """

    iconColor = color_property("_icon_color", "_retint")

    def __init__(self, icon: "qt.QtGui.QIcon | None", tooltip: str = "",
                 icon_size: qt.QtCore.QSize | None = None,
                 fallback_text: str = "", parent=None):
        super().__init__(parent)
        self._source_icon = icon if icon is not None and not icon.isNull() else None
        self._icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)  # until QSS applies
        self.setToolTip(tooltip)
        self.setIconSize(icon_size or qt.QtCore.QSize(14, 14))
        if self._source_icon is None:
            self.setText(fallback_text)
        self._retint()

    def set_source_icon(self, icon: "qt.QtGui.QIcon | None") -> None:
        """Replaces the icon shape (tinted with the current iconColor)."""
        self._source_icon = icon if icon is not None and not icon.isNull() else None
        self._retint()

    def _retint(self) -> None:
        # Also reached from the iconColor setter, which QSS may call during polish.
        source = getattr(self, "_source_icon", None)
        if source is None:
            self.setIcon(qt.QtGui.QIcon())
            return
        side = self.iconSize().width()
        self.setIcon(qt.QtGui.QIcon(tint_icon(source, side, self.devicePixelRatioF(), self._icon_color)))


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        icon = UiResources().iconManager.get_icon("browse", sub_folder="actions")
        button = IconPushButton(icon, "Browse for a folder", fallback_text="...")
        button.setFixedSize(26, 21)
        dialog.add_case("IconPushButton (browse)", button)
        dialog.show()
