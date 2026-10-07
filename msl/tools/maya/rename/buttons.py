# tools/maya/rename/buttons.py
"""The rename tool's own small buttons: one that shows which sides the selection stands on, one
that shows what kind of object is selected, and the quick text buttons (AA, _1 ...)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
from msl_tools.msl.tools.maya.rename import rules
from msl_tools.msl.ui.theme.qss import color_property


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
