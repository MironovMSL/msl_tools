# ui/widgets/compositions/action_strip.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.theme import ThemeRegistry
from msl_tools.msl.ui.theme.qss import color_property, repolish
from msl_tools.msl.ui.widgets.atoms.buttons.icon_push_button import IconPushButton
from msl_tools.msl.ui.widgets.atoms.buttons.motion_icon_button import MotionIconButton
from msl_tools.msl.ui.widgets.atoms.layouts import FlowLayout


class ActionStrip(qt.QtWidgets.QFrame):
    """A strip of icon buttons of which ONE is picked — the things a tool can
    DO (trim, loop, join, ...), as opposed to the settings of one of them.

        strip = ActionStrip()
        strip.set_items([("trim", "Trim", "Keep one piece of the video", scissors_icon, "change"), ...])
        strip.set_items([("trim", "Trim", "Keep one piece of the video", "scissors", "change"), ...])
                                                 # a NAME of a motion icon instead of a QIcon: it moves
        strip.clicked.connect(...)        # the key of the button that was clicked
        strip.current() / strip.set_current("trim")

    An item's icon is a QIcon — or the name of a motion icon (atoms/icons/
    motion_icons.py): then the button is a MotionIconButton, and its icon
    plays a short animation under the pointer and when it is picked
    (scissors snip, the loop turns) — it shows what the action does.

    Icons only, so the strip itself teaches what they are: while the pointer
    is over a button, its name and one-line description are written in the
    free room after the buttons — at once, no waiting for a tooltip. The
    optional fifth value of an item is its GROUP: a hairline is drawn where
    the group changes. The buttons wrap onto another line when the strip is
    too narrow for them.

    The picked button is marked by a pill the STRIP paints under it, which
    slides to a newly picked one (like SegmentedControl); the button itself
    only changes its icon color through the dynamic property current="true"
    (a property, not :checked — Qt applies qproperty-* only from rules
    without pseudo-states).

    Colors are Qt properties set by ui/theme/widgets.qss: pillTopColor /
    pillColor / pillBorderColor, dividerColor, titleColor / noteColor (the
    hovered button's name and description).

    Signals:
        clicked(str) — a button was clicked (it is the current one by then).
    """

    BUTTON_SIZE = qt.QtCore.QSize(38, 32)
    ICON_SIZE = 20
    GAP_WIDTH = 9          # the room a group divider takes
    PILL_RADIUS = 6
    ANIMATION_MS = 180
    HINT_MARGIN = 14       # between the last button and the hovered one's name
    HINT_MIN_WIDTH = 90    # with less room than this nothing is written

    clicked = qt.QtCore.Signal(str)

    pillTopColor = color_property("_pill_top_color")
    pillColor = color_property("_pill_color")
    pillBorderColor = color_property("_pill_border_color")
    dividerColor = color_property("_divider_color")
    titleColor = color_property("_title_color")
    noteColor = color_property("_note_color")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("actionStrip")
        fallback = ThemeRegistry.fallback()  # until QSS applies
        self._pill_top_color = qt.QtGui.QColor(fallback.accent)
        self._pill_color = qt.QtGui.QColor(fallback.accent)
        self._pill_border_color = qt.QtGui.QColor(fallback.accent)
        self._divider_color = qt.QtGui.QColor(fallback.border)
        self._title_color = qt.QtGui.QColor(fallback.text_primary)
        self._note_color = qt.QtGui.QColor(fallback.text_secondary)
        self._buttons: dict[str, qt.QtWidgets.QPushButton] = {}
        self._texts: dict[str, tuple] = {}      # key -> (title, description)
        self._gaps: list[qt.QtWidgets.QWidget] = []
        self._current = ""
        self._hovered = ""
        self._pill_from = qt.QtCore.QRectF()    # where a slide started
        self._progress = 1.0                    # 0..1 of the slide to the current button
        self._animation = qt.QtCore.QVariantAnimation(self)
        self._animation.setDuration(self.ANIMATION_MS)
        self._animation.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._on_slide)
        self._layout = FlowLayout(self, spacing=3)
        self._layout.setContentsMargins(4, 4, 4, 4)

    # --- content ---------------------------------------------------------------------------

    def set_items(self, items: list) -> None:
        """The buttons, left to right: (key, title, description, icon[, group]).
        The picked key stays picked if it is still there; otherwise the first one is."""
        for widget in [*self._buttons.values(), *self._gaps]:
            self._layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._buttons, self._texts, self._gaps = {}, {}, []
        self._hovered = ""
        previous_group = None
        for item in items:
            key, title, description, icon = item[:4]
            group = item[4] if len(item) > 4 else None
            if self._buttons and group != previous_group:
                gap = qt.QtWidgets.QWidget(self)  # only takes the room: the strip paints the line
                gap.setFixedSize(self.GAP_WIDTH, self.BUTTON_SIZE.height())
                gap.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self._layout.addWidget(gap)
                gap.show()
                self._gaps.append(gap)
            previous_group = group
            tooltip = title + (chr(10) + description if description else "")
            if isinstance(icon, str) and MotionIconButton.has_icon(icon):
                button = MotionIconButton(icon, tooltip, icon_size=self.ICON_SIZE, parent=self)
            else:
                button = IconPushButton(icon if not isinstance(icon, str) else None, tooltip,
                                        icon_size=qt.QtCore.QSize(self.ICON_SIZE, self.ICON_SIZE),
                                        fallback_text=title[:2], parent=self)
            button.setObjectName("actionStripButton")
            button.setFixedSize(self.BUTTON_SIZE)
            button.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.TabFocus)
            button.setAccessibleName(title)
            button.installEventFilter(self)
            button.clicked.connect(lambda _checked=False, picked=key: self._on_clicked(picked))
            self._layout.addWidget(button)
            button.show()
            self._buttons[key] = button
            self._texts[key] = (title, description)
        if self._current not in self._buttons:
            self._current = next(iter(self._buttons), "")
        self._animation.stop()
        self._progress = 1.0
        self._sync()
        self._layout.invalidate()
        self.update()

    def keys(self) -> list[str]:
        return list(self._buttons)

    def current(self) -> str:
        """The picked button's key ("" when there are none)."""
        return self._current

    def set_current(self, key: str, animate: bool = True) -> None:
        """Picks a button without emitting clicked (`animate`: the pill slides there)."""
        if key in self._buttons and key != self._current:
            self._slide_to(key)
            if not animate:
                self._animation.stop()
                self._progress = 1.0
                self.update()

    def _slide_to(self, key: str) -> None:
        self._pill_from = self._pill_rect()
        self._current = key
        self._sync()
        if self.isVisible() and not self._pill_from.isEmpty():
            self._progress = 0.0
            self._animation.stop()
            self._animation.start()
        else:
            self._progress = 1.0
            self.update()

    def _sync(self) -> None:
        for key, button in self._buttons.items():
            picked = key == self._current
            if bool(button.property("current")) != picked:
                button.setProperty("current", picked)
                repolish(button)

    def _on_clicked(self, key: str) -> None:
        if key != self._current:
            self._slide_to(key)
        button = self._buttons.get(key)
        if isinstance(button, MotionIconButton):
            button.play()  # picked: its icon shows once more what it does
        self.clicked.emit(key)

    def _on_slide(self, value) -> None:
        self._progress = float(value)
        self.update()

    # --- hover -----------------------------------------------------------------------------

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind in (qt.QtCore.QEvent.Type.Enter, qt.QtCore.QEvent.Type.Leave):
            key = next((key for key, button in self._buttons.items() if button is watched), "")
            hovered = key if kind == qt.QtCore.QEvent.Type.Enter else ("" if self._hovered == key else self._hovered)
            if hovered != self._hovered:
                self._hovered = hovered
                self.update()
        return super().eventFilter(watched, event)

    # --- painting ----------------------------------------------------------------------------

    def _pill_rect(self) -> qt.QtCore.QRectF:
        """Where the pill is right now: under the current button, or on its way there."""
        button = self._buttons.get(self._current)
        if button is None:
            return qt.QtCore.QRectF()
        target = qt.QtCore.QRectF(button.geometry())
        if self._progress >= 1.0 or self._pill_from.isEmpty():
            return target
        t = self._progress
        start = self._pill_from
        return qt.QtCore.QRectF(start.x() + (target.x() - start.x()) * t, start.y() + (target.y() - start.y()) * t,
                                start.width() + (target.width() - start.width()) * t,
                                start.height() + (target.height() - start.height()) * t)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the frame and background from QSS
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        pill = self._pill_rect()
        if not pill.isEmpty():
            rect = pill.adjusted(0.5, 0.5, -0.5, -0.5)
            fill = qt.QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0.0, self._pill_top_color)
            fill.setColorAt(1.0, self._pill_color)
            painter.setPen(qt.QtGui.QPen(self._pill_border_color, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, self.PILL_RADIUS, self.PILL_RADIUS)

        painter.setPen(qt.QtGui.QPen(self._divider_color, 1))
        for gap in self._gaps:
            x = gap.geometry().center().x() + 0.5
            painter.drawLine(qt.QtCore.QPointF(x, gap.y() + 7), qt.QtCore.QPointF(x, gap.y() + gap.height() - 7))

        self._paint_hint(painter)
        painter.end()

    def _paint_hint(self, painter: qt.QtGui.QPainter) -> None:
        """The hovered button's name and description, in the room after the last button."""
        title, note = self._texts.get(self._hovered, ("", ""))
        if not title or not self._buttons:
            return
        last = list(self._buttons.values())[-1].geometry()
        left = last.right() + self.HINT_MARGIN
        room = self.width() - left - 10
        if room < self.HINT_MIN_WIDTH:
            return
        bold = qt.QtGui.QFont(self.font())
        bold.setWeight(qt.QtGui.QFont.Weight.DemiBold)
        metrics = qt.QtGui.QFontMetrics(bold)
        title_width = metrics.horizontalAdvance(title)
        rect = qt.QtCore.QRectF(left, last.y(), room, last.height())
        flags = qt.QtCore.Qt.AlignmentFlag.AlignVCenter | qt.QtCore.Qt.AlignmentFlag.AlignLeft
        painter.setFont(bold)
        painter.setPen(self._title_color)
        painter.drawText(rect, flags, metrics.elidedText(title, qt.QtCore.Qt.TextElideMode.ElideRight, int(room)))
        rest = room - title_width - 10
        if note and rest > 40:
            plain = qt.QtGui.QFontMetrics(self.font())
            painter.setFont(self.font())
            painter.setPen(self._note_color)
            painter.drawText(rect.adjusted(title_width + 10, 0, 0, 0), flags,
                             plain.elidedText(note, qt.QtCore.Qt.TextElideMode.ElideRight, int(rest)))


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.ui_resources import UiResources
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        icons = UiResources().iconManager
        dialog = ThemedWidgetPlaygroundDialog()
        strip = ActionStrip()
        strip.setMinimumWidth(560)
        names = ("compress", "scissors", "repeat", "text_frame", "volume", "gif", "image_stack", "clapper")
        strip.set_items([(name, name.replace("_", " ").title(), "what it does, in one line",
                          icons.get_icon(name, sub_folder="actions"), "a" if index < 5 else "b")
                         for index, name in enumerate(names)])
        strip.clicked.connect(print)
        dialog.add_case("ActionStrip (hover a button; the pill slides)", strip)
        dialog.show()
