# tools/maya/controls/attribute_rows.py
"""The ATTRIBUTES card's rows (Qt only — what an attribute IS comes in as plain data, what the user
does goes out as signals): each attribute is a row of WIDGETS, not text —

    grip · mark · name · value · K · lock

the grip drags the row to another place; the mark is the Channel Box's own code (keys / fed by a
connection); the name is renamed by a double click, in place; the value is a widget of the
attribute's kind — a field that is also a slider (its fill shows where the value stands in its
range), a check box, a drop-down of the list's names; K and the lock are clicked like the columns
of a layer editor. A separator is a line with its text."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox

ROW_HEIGHT = 26
VALUE_WIDTH = 132
NUMBER, WHOLE, SWITCH, LIST, SEPARATOR = "Number", "Whole number", "On / off", "List", "Separator"


def _fallback():
    from msl_tools.msl.core.theme.theme_registry import ThemeRegistry
    return ThemeRegistry.fallback()


class _OutsideClick(qt.QtCore.QObject):
    """While a field typed in place is open: a mouse press anywhere but on it gives the edit up
    (`on_outside()`). Most of the tool's buttons never take the keyboard focus, so the field would
    not notice such a click by itself and stayed open. The press itself is not eaten. Installed on
    the application only for as long as the field lives (`stop()`)."""

    def __init__(self, field, on_outside):
        super().__init__(field)
        self._field, self._on_outside = field, on_outside
        qt.QtWidgets.QApplication.instance().installEventFilter(self)

    def stop(self) -> None:
        application = qt.QtWidgets.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == qt.QtCore.QEvent.Type.MouseButtonPress and isinstance(watched, qt.QtWidgets.QWidget):
            field = self._field
            if watched is not field and not field.isAncestorOf(watched):
                self.stop()
                self._on_outside()
        return False


class ValueSlider(qt.QtWidgets.QWidget):
    """A number as a field that is also a slider: drag it sideways (left or middle button), the
    wheel steps it, a double click types a number. With a range its fill shows where the value
    stands; without one a drag goes by steps (Shift: ten times, Ctrl: a tenth).

    Signals:
        drag_started() / dragged(float) / drag_finished(float) — a drag: the in-between values, then
            the one it ended on (not sent when nothing changed)
        value_set(float) — one change that is not a drag: a typed number, the wheel
    """

    drag_started = qt.QtCore.Signal()
    dragged = qt.QtCore.Signal(float)
    drag_finished = qt.QtCore.Signal(float)
    value_set = qt.QtCore.Signal(float)

    fieldColor = color_property("_field", "update")
    borderColor = color_property("_border", "update")
    fillColor = color_property("_fill", "update")
    textColor = color_property("_text", "update")
    quietColor = color_property("_quiet", "update")

    def __init__(self, value: float, minimum=None, maximum=None, whole: bool = False, parent=None):
        super().__init__(parent)
        theme = _fallback()
        self._field = qt.QtGui.QColor(theme.surface)
        self._border = qt.QtGui.QColor(theme.border)
        self._fill = qt.QtGui.QColor(theme.accent)
        self._text = qt.QtGui.QColor(theme.text_primary)
        self._quiet = qt.QtGui.QColor(theme.text_secondary)
        self._value, self._minimum, self._maximum, self._whole = float(value), minimum, maximum, whole
        self._drag = None           # (the x it started at, the value it started with, moved?)
        self._editor = None
        self._read_only = False
        self.setFixedHeight(22)
        self.setCursor(qt.QtCore.Qt.CursorShape.SizeHorCursor)
        self.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        """Shows a value (from the scene): nothing is sent."""
        if self._drag is None and self._editor is None and float(value) != self._value:
            self._value = float(value)
            self.update()

    def set_range(self, minimum, maximum) -> None:
        self._minimum, self._maximum = minimum, maximum
        self.update()

    def set_read_only(self, on: bool) -> None:
        self._read_only = bool(on)
        self.setCursor(qt.QtCore.Qt.CursorShape.ArrowCursor if on else qt.QtCore.Qt.CursorShape.SizeHorCursor)
        self.update()

    def _fitted(self, value: float) -> float:
        if self._minimum is not None:
            value = max(value, self._minimum)
        if self._maximum is not None:
            value = min(value, self._maximum)
        return float(round(value)) if self._whole else round(value, 4)

    def _ranged(self) -> bool:
        return self._minimum is not None and self._maximum is not None and self._maximum > self._minimum

    def _step(self) -> float:
        if self._whole:
            return 1.0
        return (self._maximum - self._minimum) / 100.0 if self._ranged() else 0.1

    def text(self) -> str:
        return f"{int(self._value)}" if self._whole else f"{self._value:.3f}".rstrip("0").rstrip(".")

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(rect, 5, 5)
        painter.fillPath(path, self._field)
        if self._ranged():
            part = (self._value - self._minimum) / (self._maximum - self._minimum)
            fill = qt.QtGui.QColor(self._fill)
            fill.setAlpha(46 if self._read_only else 84)
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(qt.QtCore.QRectF(rect.left(), rect.top(), rect.width() * max(0.0, min(1.0, part)),
                                              rect.height()), fill)
            painter.restore()
        painter.setPen(qt.QtGui.QPen(self._fill if self._drag is not None else self._border, 1))
        painter.drawPath(path)
        painter.setPen(self._quiet if self._read_only else self._text)
        painter.drawText(self.rect().adjusted(6, 0, -6, 0),
                         qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.end()

    # ---- the mouse

    def mousePressEvent(self, event) -> None:
        if self._read_only or event.button() not in (qt.QtCore.Qt.MouseButton.LeftButton,
                                                     qt.QtCore.Qt.MouseButton.MiddleButton):
            super().mousePressEvent(event)
            return
        self._drag = [event.position().x(), self._value, False]
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        start, value, moved = self._drag
        distance = event.position().x() - start
        if not moved:
            if abs(distance) < qt.QtWidgets.QApplication.startDragDistance():
                return
            self._drag[2] = True
            self.drag_started.emit()
        modifiers = qt.QtWidgets.QApplication.keyboardModifiers()
        if self._ranged() and not modifiers:
            new = value + distance / max(1.0, self.width() - 2.0) * (self._maximum - self._minimum)
        else:
            factor = (10.0 if modifiers & qt.QtCore.Qt.KeyboardModifier.ShiftModifier else
                      0.1 if modifiers & qt.QtCore.Qt.KeyboardModifier.ControlModifier else 1.0)
            new = value + distance / 4.0 * self._step() * factor
        new = self._fitted(new)
        if new != self._value:
            self._value = new
            self.update()
            self.dragged.emit(new)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is None:
            return
        _start, value, moved = self._drag
        self._drag = None
        self.update()
        if moved:
            self.drag_finished.emit(self._value)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._read_only and event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._drag = None
            self._type()

    def wheelEvent(self, event) -> None:
        if self._read_only or not self.hasFocus():
            event.ignore()          # the wheel scrolls the panel unless the field was clicked
            return
        big = qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier
        new = self._fitted(self._value + (1 if event.angleDelta().y() > 0 else -1) * self._step() * (10 if big else 1))
        if new != self._value:
            self._value = new
            self.update()
            self.value_set.emit(new)
        event.accept()

    # ---- typing

    def _type(self) -> None:
        editor = self._editor = qt.QtWidgets.QLineEdit(self.text(), self)
        editor.setObjectName("controlsAttrEdit")
        editor.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight)
        editor.setGeometry(self.rect())
        editor.show()
        editor.setFocus()
        editor.selectAll()
        editor.returnPressed.connect(self._typed)       # only Enter takes the number
        editor.installEventFilter(self)
        self._outside = _OutsideClick(editor, self._close_editor)      # a click elsewhere: as it was

    def eventFilter(self, watched, event) -> bool:
        if watched is self._editor and self._editor is not None:
            if event.type() == qt.QtCore.QEvent.Type.KeyPress and event.key() == qt.QtCore.Qt.Key.Key_Escape:
                self._close_editor()
                return True
            if event.type() == qt.QtCore.QEvent.Type.FocusOut:
                # a click into another field: Qt moves the focus BEFORE anyone sees the press — the
                # number is given up here (a field that only lost the focus must not take it)
                qt.QtCore.QTimer.singleShot(0, self._close_editor)
        return super().eventFilter(watched, event)

    def _close_editor(self) -> "str | None":
        editor, self._editor = self._editor, None
        if editor is None:
            return None
        outside, self._outside = getattr(self, "_outside", None), None
        if outside is not None:
            outside.stop()
        text = editor.text()
        editor.blockSignals(True)
        editor.hide()
        editor.deleteLater()
        return text

    def _typed(self) -> None:
        text = self._close_editor()
        if text is None:
            return
        try:
            new = self._fitted(float(text.replace(",", ".")))
        except ValueError:
            return
        if new != self._value:
            self._value = new
            self.update()
            self.value_set.emit(new)


class _Grip(qt.QtWidgets.QWidget):
    """Six dots: the row is dragged by them."""

    def __init__(self, row):
        super().__init__(row)
        self._row = row
        self.setFixedSize(12, ROW_HEIGHT)
        self.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag: the attribute to another place in the Channel Box")
        self._pressed = False

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._row.gripColor)
        for column in (3.5, 8.5):
            for line in (-4, 0, 4):
                painter.drawEllipse(qt.QtCore.QPointF(column, self.height() / 2.0 + line), 1.1, 1.1)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setCursor(qt.QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._pressed:
            self._row.grip_moved.emit(self._row, event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed:
            self._pressed = False
            self.setCursor(qt.QtCore.Qt.CursorShape.OpenHandCursor)
            self._row.grip_released.emit(self._row)


class _Name(qt.QtWidgets.QLabel):
    double_clicked = qt.QtCore.Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()


class AttributeRow(qt.QtWidgets.QWidget):
    """One attribute as a row of widgets. `info` = attributes.describe()'s plain data.

    Signals (the row never changes the scene itself):
        picked(row, modifiers) — a click on the row's own room
        renamed(name, new) — the name (a separator: its text) was typed
        value_set(name, value) / drag_started(name) / dragged(name, value) / drag_finished(name, value)
        key_clicked(name) / lock_clicked(name) — the K mark, the lock
        menu_requested(name, where, global position) — a right click; where: "value", "key" or "row"
        action_requested(name, key, global position) — one of the small buttons that show beside the
            name under the pointer: "key", "default", "rename" (handled by the row itself), "range"
        grip_moved(row, global position) / grip_released(row) — the row is being dragged
    """

    picked = qt.QtCore.Signal(object, object)
    renamed = qt.QtCore.Signal(str, str)
    value_set = qt.QtCore.Signal(str, object)
    drag_started = qt.QtCore.Signal(str)
    dragged = qt.QtCore.Signal(str, object)
    drag_finished = qt.QtCore.Signal(str, object)
    key_clicked = qt.QtCore.Signal(str)
    lock_clicked = qt.QtCore.Signal(str)
    menu_requested = qt.QtCore.Signal(str, str, object)
    action_requested = qt.QtCore.Signal(str, str, object)
    grip_moved = qt.QtCore.Signal(object, object)
    grip_released = qt.QtCore.Signal(object)

    gripColor = color_property("_grip_color", "update")
    hoverColor = color_property("_hover_color", "update")
    selectedColor = color_property("_selected_color", "update")
    keyedColor = color_property("_keyed_color", "update")       # the mark: it has keys
    drivenColor = color_property("_driven_color", "update")     # the mark: a connection feeds it
    mixedColor = color_property("_mixed_color", "update")       # "≠": the selected objects differ here
    lineColor = color_property("_line_color", "update")         # a separator's line

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        theme = _fallback()
        self._grip_color = qt.QtGui.QColor(theme.text_secondary)
        self._hover_color = qt.QtGui.QColor(theme.accent)
        self._selected_color = qt.QtGui.QColor(theme.accent)
        self._keyed_color = qt.QtGui.QColor(theme.error)
        self._driven_color = qt.QtGui.QColor(theme.warning)
        self._mixed_color = qt.QtGui.QColor(theme.warning)
        self._line_color = qt.QtGui.QColor(theme.text_secondary)
        self.info = dict(info)
        self.name = info["name"]
        self._selected = self._hovered = False
        self._name_editor = None
        self.setFixedHeight(ROW_HEIGHT)
        self.setObjectName("controlsAttrRow")
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_Hover, True)
        self.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda position: self.menu_requested.emit(
            self.name, "row", self.mapToGlobal(position)))
        icons = UiResources().iconManager
        self._lock_icons = {True: icons.get_icon("lock", sub_folder="actions"),
                            False: icons.get_icon("unlock", sub_folder="actions")}
        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 4, 0)
        layout.setSpacing(5)
        self._grip = _Grip(self)
        layout.addWidget(self._grip)
        layout.addSpacing(6)                    # the mark is painted here
        self._label = _Name()
        self._label.setObjectName("controlsAttrName")
        self._label.setMinimumWidth(30)
        self._label.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Ignored, qt.QtWidgets.QSizePolicy.Policy.Preferred)
        self._label.double_clicked.connect(self._start_rename)
        layout.addWidget(self._label, 1)
        self.kind = info["kind"]
        self._value = self._key = self._lock = None
        self._quick = self._quick_actions(icons)
        layout.addWidget(self._quick)
        if self.kind != SEPARATOR:
            self._value = self._value_widget(info)
            if self._value is not None:
                self._value.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
                self._value.customContextMenuRequested.connect(lambda position: self.menu_requested.emit(
                    self.name, "value", self._value.mapToGlobal(position)))
                holder = qt.QtWidgets.QWidget()
                holder.setFixedWidth(VALUE_WIDTH)
                inner = qt.QtWidgets.QHBoxLayout(holder)
                inner.setContentsMargins(0, 0, 0, 0)
                if self.kind == SWITCH:
                    inner.addStretch(1)
                inner.addWidget(self._value, 0 if self.kind == SWITCH else 1)
                layout.addWidget(holder)
            else:
                unknown = qt.QtWidgets.QLabel(info["type"])
                unknown.setObjectName("controlsCaption")
                unknown.setFixedWidth(VALUE_WIDTH)
                unknown.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignRight | qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
                layout.addWidget(unknown)
            self._key = qt.QtWidgets.QPushButton()
            self._key.setObjectName("controlsAttrKey")
            self._key.setFixedSize(22, 20)
            self._key.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.NoFocus)
            self._key.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            self._key.clicked.connect(lambda: self.key_clicked.emit(self.name))
            self._key.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            self._key.customContextMenuRequested.connect(lambda position: self.menu_requested.emit(
                self.name, "key", self._key.mapToGlobal(position)))
            layout.addWidget(self._key)
            from msl_tools.msl.tools.maya.rename.buttons import QuickButton
            self._lock = QuickButton(self._lock_icons[False], "L", "", icon_size=13)
            self._lock.setObjectName("controlsAttrLock")
            self._lock.setFixedSize(22, 20)
            self._lock.clicked.connect(lambda: self.lock_clicked.emit(self.name))
            layout.addWidget(self._lock)
        self.update_info(info)

    # ---- small buttons beside the name, only under the pointer: what one does to ONE attribute

    def _quick_actions(self, icons) -> qt.QtWidgets.QWidget:
        from msl_tools.msl.ui.widgets.atoms.buttons.glyph_button import GlyphButton
        holder = qt.QtWidgets.QWidget(self)
        box = qt.QtWidgets.QHBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        separator, number = self.kind == SEPARATOR, self.kind in (NUMBER, WHOLE)
        wanted = [("rename", "edit", "Change its text" if separator else "Rename (a double click on the name too)")]
        if not separator and self.kind:
            wanted = [("key", "keyframe", "Key it at the current frame"),
                      ("default", "restart", "Back to its default")] + wanted
        if number:
            wanted.append(("range", "range", "Its range: min, max, default"))
        self._quick_buttons = {}
        for key, icon, tip in wanted:
            button = GlyphButton("", tip, qt.QtCore.QSize(20, 20))
            button.setObjectName("controlsAttrQuick")
            button.set_icon(icons.get_icon(icon, sub_folder="actions"))
            button.clicked.connect(lambda _checked=False, key=key, button=button: self._on_quick(key, button))
            box.addWidget(button)
            self._quick_buttons[key] = button
        holder.hide()
        return holder

    def _on_quick(self, key: str, button) -> None:
        if key == "rename":
            self._start_rename()
        else:
            self.action_requested.emit(self.name, key, button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    # ---- the value's widget, by the attribute's kind

    def _value_widget(self, info: dict):
        kind = info["kind"]
        if kind in (NUMBER, WHOLE):
            field = ValueSlider(info["value"] or 0.0, info["minimum"], info["maximum"], whole=kind == WHOLE)
            field.setObjectName("controlsAttrValue")
            field.drag_started.connect(lambda: self.drag_started.emit(self.name))
            field.dragged.connect(lambda value: self.dragged.emit(self.name, self._typed(value)))
            field.drag_finished.connect(lambda value: self.drag_finished.emit(self.name, self._typed(value)))
            field.value_set.connect(lambda value: self.value_set.emit(self.name, self._typed(value)))
            return field
        if kind == SWITCH:
            box = BaseCheckbox("")
            box.setChecked(bool(info["value"]))
            box.clicked.connect(lambda checked: self.value_set.emit(self.name, bool(checked)))
            return box
        if kind == LIST:
            names = list(info["names"]) or [""]
            index = int(info["value"] or 0)
            combo = BaseComboBox(names, names[index] if 0 <= index < len(names) else names[0], enable_wheel=False)
            combo.setObjectName("controlsAttrList")
            combo.activated.connect(lambda chosen: self.value_set.emit(self.name, int(chosen)))
            return combo
        return None

    def _typed(self, value: float):
        return int(round(value)) if self.kind == WHOLE else float(value)

    def signature(self) -> tuple:
        return self.signature_of(self.info)

    @staticmethod
    def signature_of(info: dict) -> tuple:
        """What a row's WIDGETS depend on: when it is the same, the row is updated, not built anew."""
        return (info["name"], info["kind"], info["type"], tuple(info["names"]) if info["kind"] == LIST else ())

    def update_info(self, info: dict) -> None:
        """Shows what the attribute is NOW (value, range, marks) — never while it is being edited."""
        self.info = dict(info)
        separator = self.kind == SEPARATOR
        if self._name_editor is None:
            if separator:
                label = (info["names"][0].strip() if info["names"] else "")
                self._label.setText(label)
                self._label.setToolTip("A separator line — double click: its text")
            else:
                self._label.setText(info["name"])
                self._label.setToolTip(f"{info['name']} · {info['kind'] or info['type']}\nDouble click: rename it")
        quiet = bool(info["locked"]) and not separator
        if bool(self._label.property("quiet")) != quiet or bool(self._label.property("separator")) != separator:
            self._label.setProperty("quiet", quiet)
            self._label.setProperty("separator", separator)
            repolish(self._label)
        if separator:
            self.update()
            return
        read_only = bool(info["locked"] or info["driven"])
        value = self._value
        if isinstance(value, ValueSlider):
            value.set_range(info["minimum"], info["maximum"])
            value.set_value(info["value"] or 0.0)
            value.set_read_only(read_only)
            low, high = info["minimum"], info["maximum"]
            span = (f"{low:g} … {high:g}" if low is not None and high is not None else
                    f"from {low:g}" if low is not None else f"up to {high:g}" if high is not None else "no limits")
            value.setToolTip(f"{span} · default {info['default']:g}\nDrag sideways · double click: type a number · "
                             "right click: key it, back to default, its range" +
                             ("\nLocked" if info["locked"] else "\nFed by a connection: read only" if info["driven"] else ""))
        elif isinstance(value, BaseCheckbox):
            if value.isChecked() != bool(info["value"]):
                value.setChecked(bool(info["value"]))
            value.setEnabled(not read_only)
        elif isinstance(value, BaseComboBox):
            index = int(info["value"] or 0)
            if not value.view().isVisible() and value.currentIndex() != index and 0 <= index < value.count():
                value.blockSignals(True)
                value.setCurrentIndex(index)
                value.blockSignals(False)
            value.setEnabled(not read_only)
        if info.get("mixed") and value is not None:
            value.setToolTip((value.toolTip() + "\n" if value.toolTip() else "") +
                             "≠ The selected objects hold DIFFERENT values here — this is the first one's; "
                             "changing it gives them all the same")
        elif isinstance(value, (BaseCheckbox, BaseComboBox)):
            value.setToolTip("")
        state = "key" if info["keyable"] else "shown" if info["shown"] else "hidden"
        self._key.setText({"key": "K", "shown": "·", "hidden": "–"}[state])
        if (self._key.property("state") or "") != state:
            self._key.setProperty("state", state)
            repolish(self._key)
        self._key.setToolTip({"key": "Keyable: in the Channel Box, can be keyed",
                              "shown": "Shown only: in the Channel Box, can't be keyed",
                              "hidden": "Hidden: not in the Channel Box"}[state] +
                             "\nClick: keyable <-> shown only · right click: hide it")
        locked = bool(info["locked"])
        self._lock.set_source_icon(self._lock_icons[locked])
        if bool(self._lock.property("on")) != locked:
            self._lock.setProperty("on", locked)
            repolish(self._lock)
        self._lock.setToolTip(("Locked" if locked else "Not locked") + " — click changes it")
        self.update()

    # ---- the name, typed in place

    def _start_rename(self) -> None:
        if self._name_editor is not None:
            return
        self._quick.hide()               # the field takes the room of the name and of its buttons
        self.layout().activate()
        editor = self._name_editor = qt.QtWidgets.QLineEdit(self._label.text(), self)
        editor.setObjectName("controlsAttrEdit")
        editor.setGeometry(self._label.geometry().adjusted(-3, 2, 0, -2))
        editor.show()
        editor.setFocus()
        editor.selectAll()
        editor.returnPressed.connect(self._end_rename)   # only Enter takes the new name
        editor.installEventFilter(self)
        # a click anywhere else gives the rename up: the name is as it was (Enter takes the new one)
        self._outside = _OutsideClick(editor, self._drop_editor)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._name_editor and self._name_editor is not None:
            if event.type() == qt.QtCore.QEvent.Type.KeyPress and event.key() == qt.QtCore.Qt.Key.Key_Escape:
                self._drop_editor()
                return True
            if event.type() == qt.QtCore.QEvent.Type.FocusOut:
                # (see ValueSlider: the focus leaves before a press elsewhere is seen) — given up
                qt.QtCore.QTimer.singleShot(0, self._drop_editor)
        return super().eventFilter(watched, event)

    def _drop_editor(self) -> "str | None":
        editor, self._name_editor = self._name_editor, None
        if editor is None:
            return None
        outside, self._outside = getattr(self, "_outside", None), None
        if outside is not None:
            outside.stop()
        self.update()
        text = editor.text().strip()
        editor.blockSignals(True)
        editor.hide()
        editor.deleteLater()
        return text

    def _end_rename(self) -> None:
        text = self._drop_editor()
        if text is not None and text != self._label.text() and (text or self.kind == SEPARATOR):
            self.renamed.emit(self.name, text)

    def is_editing(self) -> bool:
        return self._name_editor is not None

    # ---- picked, hovered, the mark, a separator's line

    def set_selected(self, on: bool) -> None:
        if self._selected != bool(on):
            self._selected = bool(on)
            self.update()

    def is_selected(self) -> bool:
        return self._selected

    def event(self, event) -> bool:
        if event.type() in (qt.QtCore.QEvent.Type.HoverEnter, qt.QtCore.QEvent.Type.HoverLeave):
            self._hovered = event.type() == qt.QtCore.QEvent.Type.HoverEnter
            self._quick.setVisible(self._hovered and self._name_editor is None)
            self.update()
        return super().event(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton:
            self.picked.emit(self, qt.QtWidgets.QApplication.keyboardModifiers())
            event.accept()

    def paintEvent(self, _event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = qt.QtCore.QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self._selected or self._hovered:
            tint = qt.QtGui.QColor(self._selected_color if self._selected else self._hover_color)
            tint.setAlpha(58 if self._selected else 22)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(rect, 5, 5)
        info = self.info
        if self.kind == SEPARATOR:
            # a rule across the row, strong enough to be SEEN as a divider (an empty one is only this)
            pen = qt.QtGui.QPen(self._line_color, 1.6)
            pen.setCapStyle(qt.QtCore.Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            middle = self.height() / 2.0 + 0.5
            left, right = self._label.geometry().left(), self.width() - 6
            text = self._label.text().strip()
            if text and self._name_editor is None:
                width = self._label.fontMetrics().horizontalAdvance(self._label.text())
                painter.drawLine(qt.QtCore.QPointF(left + width + 8, middle), qt.QtCore.QPointF(right, middle))
            elif not text:
                painter.drawLine(qt.QtCore.QPointF(left, middle), qt.QtCore.QPointF(right, middle))
        elif info.get("keyed") or info.get("driven"):
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(self._keyed_color if info.get("keyed") else self._driven_color)
            painter.drawRoundedRect(qt.QtCore.QRectF(self._grip.geometry().right() + 4, 6, 3, self.height() - 12), 1.5, 1.5)
        if info.get("mixed") and self.kind != SEPARATOR and self._value is not None:
            # the selected objects don't hold the same value here: "≠" right before the value
            holder = self._value.parentWidget()
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(self._mixed_color)
            painter.drawText(qt.QtCore.QRectF(holder.geometry().left() - 16, 0, 14, self.height()),
                             qt.QtCore.Qt.AlignmentFlag.AlignCenter, "≠")
        painter.end()


class AttributeRows(qt.QtWidgets.QWidget):
    """The rows, one under another; rows are picked (Ctrl / Shift for several) and dragged by their
    grips into another order — a line shows where the held row would land.

    Signals: every row's own, passed on (see AttributeRow), and
        order_changed(list) — the names in their new order (on the next turn of the event loop).
    """

    order_changed = qt.QtCore.Signal(list)
    picked_changed = qt.QtCore.Signal()          # other rows are picked now
    renamed = qt.QtCore.Signal(str, str)
    value_set = qt.QtCore.Signal(str, object)
    drag_started = qt.QtCore.Signal(str)
    dragged = qt.QtCore.Signal(str, object)
    drag_finished = qt.QtCore.Signal(str, object)
    key_clicked = qt.QtCore.Signal(str)
    lock_clicked = qt.QtCore.Signal(str)
    menu_requested = qt.QtCore.Signal(str, str, object)
    action_requested = qt.QtCore.Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("controlsAttrRows")
        self._layout = qt.QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows = []
        self._last_picked = None
        self._drop_index = -1
        self._new_order = []
        self._line = qt.QtWidgets.QFrame(self)       # where a dragged row would land
        self._line.setObjectName("controlsAttrDrop")
        self._line.setFixedHeight(2)
        self._line.hide()

    def rows(self) -> list:
        return list(self._rows)

    def names(self) -> list:
        return [row.name for row in self._rows]

    def picked(self) -> list:
        return [row.name for row in self._rows if row.is_selected()]

    def row(self, name: str) -> "AttributeRow | None":
        return next((row for row in self._rows if row.name == name), None)

    def is_busy(self) -> bool:
        """A name is being typed, or a row is held: the rows must not be built anew now."""
        if self._drop_index >= 0 and not qt.QtWidgets.QApplication.mouseButtons():
            # a row was held and its release never came (a menu, the window lost the mouse): let go,
            # or the list would never show a change again
            self._drop_index = -1
            self._line.hide()
        return self._drop_index >= 0 or any(row.is_editing() for row in self._rows)

    def set_infos(self, infos: list) -> None:
        """Shows these attributes. The same attributes of the same kinds in the same order are only
        UPDATED (an open drop-down, a field being dragged are left alone); anything else builds the
        rows anew — the picked ones stay picked by name."""
        signatures = [AttributeRow.signature_of(info) for info in infos]
        if signatures == [row.signature() for row in self._rows]:
            for row, info in zip(self._rows, infos):
                row.update_info(info)
            return
        picked = set(self.picked())
        for row in self._rows:
            self._layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows, self._last_picked = [], None
        for info in infos:
            row = AttributeRow(info, self)
            row.set_selected(info["name"] in picked)
            row.picked.connect(self._on_picked)
            row.grip_moved.connect(self._on_grip_moved)
            row.grip_released.connect(self._on_grip_released)
            for signal in ("renamed", "value_set", "drag_started", "dragged", "drag_finished", "key_clicked",
                           "lock_clicked", "menu_requested", "action_requested"):
                getattr(row, signal).connect(getattr(self, signal))
            self._layout.addWidget(row)
            self._rows.append(row)
        self._line.raise_()
        if set(self.picked()) != picked:
            self.picked_changed.emit()

    # ---- picking

    def _on_picked(self, row, modifiers) -> None:
        control = bool(modifiers & qt.QtCore.Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        if shift and self._last_picked in self._rows:
            first, last = sorted((self._rows.index(self._last_picked), self._rows.index(row)))
            for index, each in enumerate(self._rows):
                each.set_selected(first <= index <= last or (control and each.is_selected()))
            self.picked_changed.emit()
            return
        if control:
            row.set_selected(not row.is_selected())
        else:
            only = row.is_selected() and len(self.picked()) == 1
            for each in self._rows:
                each.set_selected(each is row and not only)      # a click on the only picked row unpicks it
        self._last_picked = row
        self.picked_changed.emit()

    def clear_picked(self) -> None:
        for row in self._rows:
            row.set_selected(False)
        self.picked_changed.emit()

    def pick_all(self) -> None:
        for row in self._rows:
            row.set_selected(True)
        self.picked_changed.emit()

    # ---- a row dragged to another place

    def _on_grip_moved(self, row, global_position) -> None:
        y = self.mapFromGlobal(global_position).y()
        index = len(self._rows)
        for position, each in enumerate(self._rows):
            if y < each.geometry().center().y():
                index = position
                break
        self._drop_index = index
        at = (self._rows[index].geometry().top() if index < len(self._rows) else self._rows[-1].geometry().bottom()) - 1
        self._line.setGeometry(16, max(0, at), self.width() - 20, 2)
        self._line.show()
        self._line.raise_()

    def _on_grip_released(self, row) -> None:
        index, self._drop_index = self._drop_index, -1
        self._line.hide()
        if index < 0 or row not in self._rows:
            return
        names = self.names()
        source = names.index(row.name)
        if index in (source, source + 1):
            return
        name = names.pop(source)
        names.insert(index - 1 if index > source else index, name)
        self._new_order = names
        qt.QtCore.QTimer.singleShot(0, self._emit_order)

    def _emit_order(self) -> None:
        names, self._new_order = self._new_order, []
        if names:
            self.order_changed.emit(names)
