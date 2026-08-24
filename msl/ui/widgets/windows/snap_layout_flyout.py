"""Windows 11 "Snap Layouts"-style flyout: a small popup, shown near the
maximize button, offering a handful of multi-zone layouts. Picking a zone
snaps the window that owns the flyout to that zone.

Scope note: this only arranges the owning window. Native Windows Snap
Layouts also offers to fill the remaining zones with other open
application windows (Snap Assist) — that needs OS-level window
enumeration/placement (win32 APIs) outside any single Qt widget's reach
and is intentionally not attempted here.
"""

import msl_tools.msl.ui.qt_bindings as qt


LAYOUT_HALVES          = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)]
LAYOUT_THIRDS          = [(0.0, 0.0, 1 / 3, 1.0), (1 / 3, 0.0, 1 / 3, 1.0), (2 / 3, 0.0, 1 / 3, 1.0)]
LAYOUT_MAIN_PLUS_STACK = [(0.0, 0.0, 0.6, 1.0), (0.6, 0.0, 0.4, 0.5), (0.6, 0.5, 0.4, 0.5)]
LAYOUT_QUADS           = [(0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 0.5, 0.5), (0.0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]

DEFAULT_LAYOUTS        = [LAYOUT_HALVES, LAYOUT_THIRDS, LAYOUT_MAIN_PLUS_STACK, LAYOUT_QUADS]


class _ZoneButton(qt.QtWidgets.QAbstractButton):
    """One rectangle within a layout thumbnail. Purely visual + clickable;
    colors are pushed in from the flyout so theming stays centralized
    rather than each zone owning its own palette."""

    def __init__(self, zone_rect: tuple[float, float, float, float], parent=None):
        super().__init__(parent)
        self.zone_rect = zone_rect
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Expanding)

        self._fill_idle      = qt.QtGui.QColor(255, 255, 255, 30)
        self._fill_hover     = qt.QtGui.QColor(255, 255, 255, 70)
        self._fill_pressed   = qt.QtGui.QColor(255, 255, 255, 110)
        self._border         = qt.QtGui.QColor(255, 255, 255, 90)
        self._border_pressed = qt.QtGui.QColor(255, 255, 255, 140)

        # QAbstractButton doesn't guarantee a repaint on press/release for
        # a custom-painted subclass with no style-based rendering — force
        # it explicitly, same reasoning as the enterEvent/leaveEvent
        # overrides below.
        self.pressed.connect(self.update)
        self.released.connect(self.update)

    def set_colors(self, idle, hover, pressed, border, border_pressed=None) -> None:
        self._fill_idle      = qt.QtGui.QColor(idle)
        self._fill_hover     = qt.QtGui.QColor(hover)
        self._fill_pressed   = qt.QtGui.QColor(pressed)
        self._border         = qt.QtGui.QColor(border)
        self._border_pressed = qt.QtGui.QColor(border_pressed) if border_pressed is not None else self._border
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        if self.isDown():
            fill, border = self._fill_pressed, self._border_pressed
        elif self.underMouse():
            fill, border = self._fill_hover, self._border
        else:
            fill, border = self._fill_idle, self._border

        rect = qt.QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(qt.QtGui.QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 3, 3)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


class _LayoutThumbnail(qt.QtWidgets.QWidget):
    """Renders one layout template as a small grid of _ZoneButton
    rectangles, using stretch factors derived from the zone fractions so
    proportions (e.g. 60/40) render correctly without manual pixel math."""

    zone_clicked = qt.QtCore.Signal(tuple)   # emits the zone_rect fractions

    _THUMB_WIDTH  = 130
    _THUMB_HEIGHT = 78
    _ZONE_SPACING = 3

    def __init__(self, zones: list[tuple[float, float, float, float]], parent=None):
        super().__init__(parent)
        self.setFixedSize(self._THUMB_WIDTH, self._THUMB_HEIGHT)
        self._buttons: list[_ZoneButton] = []
        self._build(zones)

    def _build(self, zones) -> None:
        columns: dict[float, list[tuple[float, float, float, float]]] = {}
        for zone in zones:
            columns.setdefault(round(zone[0], 4), []).append(zone)

        root = qt.QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(self._ZONE_SPACING)

        for x_origin in sorted(columns.keys()):
            column_zones = sorted(columns[x_origin], key=lambda z: z[1])
            column_width = column_zones[0][2]

            if len(column_zones) == 1:
                root.addWidget(self._make_button(column_zones[0]), int(round(column_width * 1000)))
                continue

            column_layout = qt.QtWidgets.QVBoxLayout()
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(self._ZONE_SPACING)
            for zone in column_zones:
                column_layout.addWidget(self._make_button(zone), int(round(zone[3] * 1000)))
            root.addLayout(column_layout, int(round(column_width * 1000)))

    def _make_button(self, zone) -> _ZoneButton:
        button = _ZoneButton(zone, self)
        button.clicked.connect(lambda _checked=False, z=zone: self.zone_clicked.emit(z))
        self._buttons.append(button)
        return button

    def set_zone_colors(self, idle, hover, pressed, border, border_pressed=None) -> None:
        for button in self._buttons:
            button.set_colors(idle, hover, pressed, border, border_pressed)

class SnapLayoutFlyout(qt.QtWidgets.QWidget):
    """Popup with a row of layout thumbnails. Emits zone_chosen(fractions)
    when the user clicks a zone, then closes itself."""

    zone_chosen = qt.QtCore.Signal(tuple)

    _SHOW_ANIMATION_DURATION_MS = 140
    _SHOW_SLIDE_OFFSET = 8

    def __init__(self, layouts=None, parent=None):
        super().__init__(parent, qt.QtCore.Qt.WindowType.Popup
                                  | qt.QtCore.Qt.WindowType.FramelessWindowHint
                                  | qt.QtCore.Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._show_animation: qt.QtCore.QParallelAnimationGroup | None = None

        self._background_color = qt.QtGui.QColor(30, 30, 30, 235)
        self._border_color = qt.QtGui.QColor(255, 255, 255, 40)
        self._corner_radius = 8

        layout = qt.QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._thumbnails: list[_LayoutThumbnail] = []
        for zones in (layouts or DEFAULT_LAYOUTS):
            thumbnail = _LayoutThumbnail(zones, self)
            thumbnail.zone_clicked.connect(self._on_zone_clicked)
            layout.addWidget(thumbnail)
            self._thumbnails.append(thumbnail)

    def set_theme_colors(self, background, border, zone_idle, zone_hover, zone_pressed,
                         zone_border, zone_border_pressed=None) -> None:
        self._background_color = qt.QtGui.QColor(background)
        self._border_color = qt.QtGui.QColor(border)
        for thumbnail in self._thumbnails:
            thumbnail.set_zone_colors(zone_idle, zone_hover, zone_pressed, zone_border, zone_border_pressed)
        self.update()

    def _on_zone_clicked(self, zone_rect) -> None:
        self.zone_chosen.emit(zone_rect)
        self.close()

    # --- show animation (fade + slight downward slide) ---

    def _stop_show_animation(self) -> None:
        animation = self._show_animation
        self._show_animation = None
        if animation is not None and qt.shiboken.isValid(animation):
            animation.stop()

    def _clear_show_animation_ref(self) -> None:
        self._show_animation = None

    def show_near(self, anchor_widget: qt.QtWidgets.QWidget) -> None:
        self._stop_show_animation()

        anchor_rect = qt.QtCore.QRect(
            anchor_widget.mapToGlobal(qt.QtCore.QPoint(0, 0)),
            anchor_widget.size(),
        )
        self.adjustSize()
        target_x = anchor_rect.right() - self.width()
        target_y = anchor_rect.bottom() + 6
        start_y = target_y - self._SHOW_SLIDE_OFFSET

        self.setWindowOpacity(0.0)
        self.move(target_x, start_y)
        self.show()

        opacity_anim = qt.QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        opacity_anim.setDuration(self._SHOW_ANIMATION_DURATION_MS)
        opacity_anim.setStartValue(0.0)
        opacity_anim.setEndValue(1.0)
        opacity_anim.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)

        pos_anim = qt.QtCore.QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(self._SHOW_ANIMATION_DURATION_MS)
        pos_anim.setStartValue(qt.QtCore.QPoint(target_x, start_y))
        pos_anim.setEndValue(qt.QtCore.QPoint(target_x, target_y))
        pos_anim.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutCubic)

        group = qt.QtCore.QParallelAnimationGroup(self)
        group.addAnimation(opacity_anim)
        group.addAnimation(pos_anim)
        group.finished.connect(self._clear_show_animation_ref)
        self._show_animation = group
        group.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    # --- Qt event overrides ---

    def hideEvent(self, event) -> None:
        self._stop_show_animation()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                             self._corner_radius, self._corner_radius)
        painter.fillPath(path, self._background_color)
        painter.setPen(qt.QtGui.QPen(self._border_color, 1))
        painter.drawPath(path)