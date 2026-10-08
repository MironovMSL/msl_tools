# tools/maya/rename/buttons.py
"""The rename tool's own small buttons: one that shows which sides the selection stands on, one
that shows what kind of object is selected, and the quick text buttons (AA, _1 ...)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.ui.theme.qss import color_property
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton


_ICON_CACHE: dict = {}


def maya_type_icon(kind: str) -> "qt.QtGui.QIcon":
    """Maya's own icon of a node type — the Outliner's (":/out_mesh.png"; every built-in type of
    the suffix list has one, measured in Maya 2025). A type without its own icon borrows the one
    of the nearest type it derives from (a plug-in's locator -> the locator's). Outside Maya, or
    for a type Maya doesn't know: a null icon."""
    if not kind:
        return qt.QtGui.QIcon()
    if kind in _ICON_CACHE:
        return _ICON_CACHE[kind]
    candidates = [kind]
    try:
        from maya import cmds
        inherited = cmds.nodeType(kind, inherited=True, isTypeName=True) or []
        candidates += [each for each in reversed(inherited) if each != kind]
    except (ImportError, RuntimeError):
        pass
    icon = qt.QtGui.QIcon()
    for name in candidates:
        for path in (f":/out_{name}.png", f":/{name}.svg", f":/{name}.png"):
            if qt.QtCore.QFile.exists(path):
                icon = qt.QtGui.QIcon(path)
                break
        if not icon.isNull():
            break
    _ICON_CACHE[kind] = icon
    return icon


class HoverButton(qt.QtWidgets.QPushButton):
    """A button that says when the pointer is over it: the tool shows what a click WOULD do in
    the "before -> after" list while hovered.

    Signals:
        hovered(bool) — the pointer came in (True) / left (False).
        menu_requested() — a right click (settings of what the button does).
    """

    hovered = qt.QtCore.Signal(bool)
    menu_requested = qt.QtCore.Signal()

    def __init__(self, text: str = "", tooltip: str = "", parent=None):
        super().__init__(text, parent)
        self.setToolTip(tooltip)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton:
            self.menu_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class QuickButton(IconPushButton):
    """A quick button of the rename tool: a one-color icon tinted from QSS (rename.qss:
    qproperty-iconColor), its name in the tooltip — and, like HoverButton, it says when the
    pointer is over it, so the list can show what a click would do. Without its icon file it
    shows `text`."""

    hovered = qt.QtCore.Signal(bool)

    def __init__(self, icon, text: str, tooltip: str, parent=None, icon_size: int = 15):
        super().__init__(icon, tooltip, icon_size=qt.QtCore.QSize(icon_size, icon_size), fallback_text=text,
                         parent=parent)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.hovered.emit(False)


class GroupButton(QuickButton):
    """One button for a GROUP of quick actions: it shows the one used last and a click repeats it
    (hovered, the list shows what it would do — `hovered`); the corner triangle, a right click or
    holding the button down opens the whole group (`menu_requested`). Colors from rename.qss:
    qproperty-iconColor by the `tone` property, the triangle in the same color."""

    menu_requested = qt.QtCore.Signal()
    run_requested = qt.QtCore.Signal()

    CORNER = 10      # px of the right edge that open the group
    HOLD_MS = 380    # held this long = the group opens

    def __init__(self, tone: str, parent=None, icon_size: int = 17):
        super().__init__(None, "", "", parent, icon_size=icon_size)
        self.setObjectName("renameGroup")
        self.setProperty("tone", tone)
        self._held = False
        self._hold = qt.QtCore.QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(self.HOLD_MS)
        self._hold.timeout.connect(self._on_hold)
        self.clicked.connect(self._on_clicked)

    def _on_hold(self) -> None:
        self._held = True
        self.setDown(False)
        self.menu_requested.emit()

    def _on_clicked(self) -> None:
        if self._held:
            self._held = False
            return
        self.run_requested.emit()

    def mousePressEvent(self, event) -> None:
        self._held = False
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton or \
                (event.button() == qt.QtCore.Qt.MouseButton.LeftButton and
                 event.position().x() >= self.width() - self.CORNER):
            event.accept()
            self.menu_requested.emit()
            return
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._hold.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._hold.stop()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._icon_color)
        right, bottom = self.width() - 2.5, self.height() - 2.5
        painter.drawPolygon(qt.QtGui.QPolygonF([qt.QtCore.QPointF(right, bottom - 4), qt.QtCore.QPointF(right, bottom),
                                                qt.QtCore.QPointF(right - 4, bottom)]))


class StripButton(QuickButton):
    """A button of the strip beside the list (find / fix / lock): a one-color icon whose COLOR says
    what it does — the dynamic property `tone` picks it in rename.qss (qproperty-iconColor) —, a
    small count in its corner (`set_badge`; 0 = none; qproperty badgeColor / badgeTextColor) and a
    right click (`menu_requested`) for what it can be set to."""

    menu_requested = qt.QtCore.Signal()

    badgeColor = color_property("_badge_color")
    badgeTextColor = color_property("_badge_text_color")
    underColor = color_property("_under_color", "_retint")  # the second layer's color (set_under_icon)

    def set_under_icon(self, icon) -> None:
        """A second one-color shape UNDER the icon, in underColor (Skin joints: a grey mesh behind
        violet joints); the icon is drawn over it."""
        self._under_icon = icon if icon is not None and not icon.isNull() else None
        self._retint()

    def _retint(self) -> None:
        super()._retint()
        under, source = getattr(self, "_under_icon", None), getattr(self, "_source_icon", None)
        if under is None or source is None:
            return
        from msl_tools.msl.ui.icon_manager import tint_icon
        side, ratio = self.iconSize().width(), self.devicePixelRatioF()
        top = tint_icon(source, side, ratio, self._icon_color)
        image = tint_icon(under, side, ratio, getattr(self, "_under_color", self._icon_color)).toImage()
        painter = qt.QtGui.QPainter(image)
        painter.setCompositionMode(qt.QtGui.QPainter.CompositionMode.CompositionMode_DestinationOut)
        painter.drawPixmap(0, 0, top)   # the icon's own pixels are its alone (no mixed edges)
        painter.setCompositionMode(qt.QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, top)
        painter.end()
        pixmap = qt.QtGui.QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        self.setIcon(qt.QtGui.QIcon(pixmap))

    def __init__(self, icon, text: str, tooltip: str, tone: str, parent=None):
        super().__init__(icon, text, tooltip, parent)
        self.setObjectName("renameStrip")
        self.setProperty("tone", tone)
        self.setIconSize(qt.QtCore.QSize(16, 16))
        self._badge = 0
        fallback = ThemeRegistry.fallback()
        self._badge_color = qt.QtGui.QColor(fallback.accent)
        self._badge_text_color = qt.QtGui.QColor("white")
        self._under_color = qt.QtGui.QColor(fallback.text_secondary)

    def set_badge(self, count: int) -> None:
        count = max(0, int(count or 0))
        if count != self._badge:
            self._badge = count
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.RightButton:
            self.menu_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._badge:
            return
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        text = str(self._badge) if self._badge < 100 else "99+"
        font = painter.font()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        width = max(11, painter.fontMetrics().horizontalAdvance(text) + 5)
        rect = qt.QtCore.QRectF(self.width() - width, 0, width, 11)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._badge_color)
        painter.drawRoundedRect(rect, 5.5, 5.5)
        painter.setPen(self._badge_text_color)
        painter.drawText(rect, qt.QtCore.Qt.AlignmentFlag.AlignCenter, text)


class ToggleIconButton(QuickButton):
    """An on / off choice as a small icon button that SHOWS its state: on = the accent fill and an
    accent icon (rename.qss: `[on="true"]` — qproperty-iconColor can't come from :checked, so the
    widget mirrors it into the dynamic property `on`). The tooltip says the state in its first
    line: `title` + " — on" / " — off"."""

    def __init__(self, icon, title: str, tooltip: str, parent=None):
        super().__init__(icon, title, tooltip, parent)
        self._title, self._tooltip = title, tooltip
        self.setCheckable(True)
        self.toggled.connect(self._follow)
        self._follow()

    def _follow(self, *_args) -> None:
        from msl_tools.msl.ui.theme.qss import repolish
        on = self.isChecked()
        self.setToolTip(f"{self._title} — {'ON' if on else 'off'}\n{self._tooltip}")
        if bool(self.property("on")) != on:
            self.setProperty("on", on)
            repolish(self)


class SideButton(HoverButton):
    """lf / mid / rt prefix from where each object stands. Shows which sides the selection is on
    as dots — left, middle, right — in Maya's colors for sides (rename.qss: qproperty leftColor /
    centerColor / rightColor / emptyColor)."""

    leftColor = color_property("_left_color")
    centerColor = color_property("_center_color")
    rightColor = color_property("_right_color")
    emptyColor = color_property("_empty_color")

    def __init__(self, parent=None):
        super().__init__("", "Side prefix: lf_ / rt_ / mid_ from where each object stands\n"
                             "Right click: the axis and the prefixes", parent)
        fallback = ThemeRegistry.fallback()
        self._left_color = qt.QtGui.QColor(fallback.accent)
        self._center_color = qt.QtGui.QColor(fallback.warning)
        self._right_color = qt.QtGui.QColor(fallback.error)
        self._empty_color = qt.QtGui.QColor(fallback.border)
        self._sides: set = set()
        self.setObjectName("renameSide")
        self.setFixedSize(34, 22)

    def set_sides(self, sides) -> None:
        sides = set(sides)
        if sides != self._sides:
            self._sides = sides
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        radius = 3.0
        middle_y = self.height() / 2
        # as the character faces the viewer: its right on the left of the button
        order = ((rules.RIGHT, self._right_color), (rules.CENTER, self._center_color), (rules.LEFT, self._left_color))
        for index, (side, color) in enumerate(order):
            x = self.width() / 2 + (index - 1) * 9
            painter.setBrush(color if side in self._sides else self._empty_color)
            painter.drawEllipse(qt.QtCore.QPointF(x, middle_y), radius, radius)
        painter.end()


class KindButton(HoverButton):
    """A suffix from what each object is (mesh -> geo, joint -> jnt). Shows Maya's own icon of
    the first selected object's kind (Maya's resources: ":/mesh.svg" ...); outside Maya, or for a
    kind without one, the word "type"."""

    def __init__(self, parent=None):
        super().__init__("type", "Suffix by kind: _geo for a mesh, _jnt for a joint, _grp for a group…\n"
                                 "Right click: which suffix each kind gets", parent)
        self.setObjectName("renameKind")
        self.setFixedSize(34, 22)
        self._kind = None
        self.setIconSize(qt.QtCore.QSize(16, 16))

    def set_kind(self, kind: str) -> None:
        if kind == self._kind:
            return
        self._kind = kind
        icon = maya_type_icon(kind)
        self.setIcon(icon)
        self.setText("" if not icon.isNull() else "type")
        self.setToolTip(self.toolTip().split("\n\n")[0] + (f"\n\nSelected: {kind}" if kind else ""))
