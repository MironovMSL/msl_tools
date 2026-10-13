# ui/widgets/atoms/buttons/icon_tile_button.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.icon_manager import tint_icon
from msl_tools.msl.ui.theme.qss import color_property, repolish


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

    BADGE_TOP = 2   # the badge's top, from the tile's

    iconColor = color_property("_icon_color", "_retint")

    def __init__(self, icon: "qt.QtGui.QIcon | None", text: str,
                 icon_size: int = 20, parent=None):
        super().__init__(parent)
        self._source_icon = icon if icon is not None and not icon.isNull() else None
        self._badge: qt.QtWidgets.QLabel | None = None
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

    def set_badge(self, text: str, tone: str = "") -> None:
        """A small pill on the icon's top-right corner - a count, or "!" - "" removes it.
        `tone` "attention" paints it in the alert color; else the "all is well" one
        (widgets.qss: `IconTileButton QLabel#tileBadge`)."""
        if not text:
            if self._badge is not None:
                self._badge.hide()
            return
        if self._badge is None:
            self._badge = qt.QtWidgets.QLabel(self)  # a child from the start: it never shows as a window
            self._badge.setObjectName("tileBadge")
            self._badge.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
            self._badge.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if self._badge.property("tone") != tone:
            self._badge.setProperty("tone", tone)
            repolish(self._badge)
        self._badge.setText(text)
        self._badge.adjustSize()
        self._place_badge()
        self._badge.show()
        self._badge.raise_()

    def _place_badge(self) -> None:
        if self._badge is not None:   # the icon stands in the tile's middle, BADGE_TOP under its top edge
            self._badge.move(self.width() // 2 + self.iconSize().width() // 2 - 5, self.BADGE_TOP)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_badge()


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
