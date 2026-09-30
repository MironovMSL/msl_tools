# ui/widgets/atoms/buttons/icon_tile_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property


class IconTileButton(qt.QtWidgets.QToolButton):
    """A tile with a one-color icon on top and a short label under it — the
    app-launcher sidebar entry (Zoom Workplace style), where the icon is the
    main thing and the label names it.

    A QToolButton (ToolButtonTextUnderIcon), since QPushButton can only put
    the icon beside the text. Checkable-friendly: put tiles in a
    QButtonGroup for one-of-many navigation.

    The icon is used as a SHAPE and tinted with the `iconColor` Qt property,
    set by the window stylesheet (`qproperty-iconColor: var(--token);`), so
    it follows theme switches and hot reload. Label font, padding and state
    colors come from QSS too. Without an icon (None / missing asset) the
    icon's space stays empty, so a column of tiles keeps one height and
    every label sits on the same line.
    """

    iconColor = color_property("_icon_color", "_retint")

    def __init__(self, icon: "qt.QtGui.QIcon | None", text: str,
                 icon_size: int = 20, parent=None):
        super().__init__(parent)
        self._source_icon = icon if icon is not None and not icon.isNull() else None
        self._icon_color = qt.QtGui.QColor(ThemeRegistry.fallback().text_primary)  # until QSS applies
        self.setText(text)
        self.setToolTip(text)  # a narrow tile may clip a long label
        self.setIconSize(qt.QtCore.QSize(icon_size, icon_size))
        self.setToolButtonStyle(qt.QtCore.Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        # QToolButton is Fixed by default; a tile fills its column.
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Fixed)
        self._retint()

    def set_source_icon(self, icon: "qt.QtGui.QIcon | None") -> None:
        """Replaces the icon shape (tinted with the current iconColor)."""
        self._source_icon = icon if icon is not None and not icon.isNull() else None
        self._retint()

    def _retint(self) -> None:
        # Also reached from the iconColor setter, which QSS may call during polish.
        source = getattr(self, "_source_icon", None)
        side = self.iconSize().width()
        if source is None:
            blank = qt.QtGui.QPixmap(side, side)  # keeps the icon row's height
            blank.fill(qt.QtCore.Qt.GlobalColor.transparent)
            self.setIcon(qt.QtGui.QIcon(blank))
            return
        self.setIcon(qt.QtGui.QIcon(tint_icon(source, side, self.devicePixelRatioF(), self._icon_color)))


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        icon = UiResources().iconManager.get_icon("maya", sub_folder="apps")
        tile = IconTileButton(icon, "Maya Gate")
        tile.setFixedWidth(68)
        dialog.add_case("IconTileButton (maya)", tile)
        dialog.show()
