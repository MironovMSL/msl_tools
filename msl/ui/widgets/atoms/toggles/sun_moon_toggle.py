"""Sun/moon theme toggle atom: a single currentColor silhouette that
morphs between a crescent moon and a sun with radiating rays via a
circular mask-hole trick.

Ported from Uiverse.io's "Type-Delta" sun/moon CSS switch
(https://uiverse.io/Type-Delta/...). checked=True is mapped to the moon
(dark theme) rather than the CSS original's checked=sun, so isChecked()/
setChecked()/toggled can be used directly as "is dark theme" without a
wrapper method.

Scope note: this is a binary toggle by construction (the mask-hole either
overlaps the disc or slides fully outside it) — it doesn't extend to 3+
theme states. If a 3rd theme is needed later, that's a separate widget,
not an extension of this one (see BaseToggle-based ThemeToggleCheckbox
prototype for an N-state-capable alternative).
"""

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.toggles.base_toggle import BaseToggle


class SunMoonToggle(BaseToggle):
    """Header-sized sun/moon theme toggle. Paints no background of its
    own — set_icon_color() should be fed theme.text_primary (same
    pattern as the minimize/maximize/close nav icons) so it stays
    contrasted against the header on any theme."""

    _VIEWBOX = 20
    _IDLE_OPACITY = 0.4

    _RAY_POSITIONS = [
        (18.0, 10.0), (14.0, 16.928), (6.0, 16.928),
        (2.0, 10.0), (6.0, 3.1718), (14.0, 3.1718),
    ]

    def __init__(self, size: int =20, parent=None):
        super().__init__(parent)
        # self.setFixedSize(size, size)
        self.setFixedWidth(size)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Fixed, qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self._icon_color = qt.QtGui.QColor("#bbbbbb")

    def set_icon_color(self, color) -> None:
        self._icon_color = qt.QtGui.QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        visual_t = 1.0 - self.progress

        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)

        # DEBUG: показать реальную hit-area виджета — убрать после проверки
        # painter.fillRect(self.rect(), qt.QtGui.QColor(255, 0, 0, 80))

        painter.save()
        scale = min(self.width(), self.height()) / self._VIEWBOX
        painter.translate(self.rect().center())
        painter.scale(scale, scale)
        painter.translate(-self._VIEWBOX / 2, -self._VIEWBOX / 2)

        angle = self.lerp(40.0, 90.0, visual_t)
        painter.translate(10.0, 10.0)
        painter.rotate(angle)
        painter.translate(-10.0, -10.0)

        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self._icon_color)
        painter.setOpacity(self.lerp(self._IDLE_OPACITY, 1.0, self.hoverProgress))

        self._paint_sun_moon(painter, visual_t)
        self._paint_rays(painter, visual_t)

        painter.restore()

    def _paint_sun_moon(self, painter, visual_t: float) -> None:
        painter.save()
        sun_moon_scale = self.lerp(1.0, 0.55, visual_t)
        painter.translate(10.0, 10.0)
        painter.scale(sun_moon_scale, sun_moon_scale)
        painter.translate(-10.0, -10.0)

        main_path = qt.QtGui.QPainterPath()
        main_path.addEllipse(qt.QtCore.QPointF(10.0, 10.0), 8.0, 8.0)

        hole_center = qt.QtCore.QPointF(11.0 + self.lerp(0.0, 16.0, visual_t),
                                         3.0 + self.lerp(0.0, -3.0, visual_t))
        hole_path = qt.QtGui.QPainterPath()
        hole_path.addEllipse(hole_center, 8.0, 8.0)

        painter.drawPath(main_path.subtracted(hole_path))
        painter.restore()

    def _paint_rays(self, painter, visual_t: float) -> None:
        radius = 1.5 * visual_t
        if radius <= 0.001:
            return
        for cx, cy in self._RAY_POSITIONS:
            painter.drawEllipse(qt.QtCore.QPointF(cx, cy), radius, radius)