"""Orbit-style day/night theme toggle atom: the sun and moon travel
along a semicircular arc around the widget's center and crossfade as
they pass, rather than using a mask-hole morph or a "vault" rotation
trick. Scales with the widget's own size (not fixed-size like
SunMoonToggle), so it also works as a larger standalone switch, not
just a small header icon.
"""

import math

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.widgets.atoms.toggles.base_toggle import BaseToggle


class OrbitThemeToggle(BaseToggle):
    """Circular day/night scene toggle. checked=True -> night (moon)."""

    def __init__(self, size: int | None = None, parent=None):
        super().__init__(parent)
        if size is not None:
            self.setFixedSize(size, size)

    def sizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(90, 90)

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(60, 60)

    # --- painting ---

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        size = min(rect.width(), rect.height())
        cx, cy = rect.center().x(), rect.center().y()
        radius = size / 2 - 4
        switch_rect = qt.QtCore.QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        p = self.progress  # left un-clamped: OutBack overshoot on position/angle looks intentional

        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(qt.QtGui.QColor(0, 0, 0, 35))
        painter.drawEllipse(switch_rect.translated(0, size * 0.05))

        clip_path = qt.QtGui.QPainterPath()
        clip_path.addEllipse(switch_rect)
        painter.save()
        painter.setClipPath(clip_path)

        self._paint_sky(painter, switch_rect, p)
        self._paint_stars(painter, switch_rect, p)
        self._paint_clouds(painter, switch_rect, size, p)
        self._paint_sun_and_moon(painter, cx, cy, size, p)
        self._paint_mountains(painter, switch_rect, size, p)
        self._paint_terrain(painter, switch_rect, size, p)
        self._paint_trees(painter, switch_rect, size, p)

        painter.restore()

        border_color = self.lerp_color(qt.QtGui.QColor("#ffffff"), qt.QtGui.QColor("#2a3b5c"), p)
        painter.setPen(qt.QtGui.QPen(border_color, max(2.0, size * 0.045)))
        painter.setBrush(qt.QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(switch_rect)

    def _paint_sky(self, painter, switch_rect, p: float) -> None:
        gradient = qt.QtGui.QLinearGradient(switch_rect.topLeft(), switch_rect.bottomLeft())
        gradient.setColorAt(0.0, self.lerp_color(qt.QtGui.QColor("#5ab5e6"), qt.QtGui.QColor("#0b1325"), p))
        gradient.setColorAt(1.0, self.lerp_color(qt.QtGui.QColor("#aee0ff"), qt.QtGui.QColor("#1a2845"), p))
        painter.fillRect(switch_rect, gradient)

    def _paint_stars(self, painter, switch_rect, p: float) -> None:
        opacity = max(0, min(255, round(255 * p)))
        if opacity <= 0:
            return
        size = switch_rect.width()
        color = qt.QtGui.QColor(255, 255, 255, opacity)
        for x_factor, y_factor, star_size in (
            (0.25, 0.22, 2.0), (0.70, 0.32, 2.5), (0.30, 0.50, 1.8),
            (0.55, 0.20, 1.5), (0.62, 0.48, 1.3),
        ):
            x = switch_rect.left() + switch_rect.width() * x_factor
            y = switch_rect.top() + switch_rect.height() * y_factor
            self._draw_circle(painter, x, y, size * 0.015 * star_size, color)

    def _paint_clouds(self, painter, switch_rect, size: float, p: float) -> None:
        opacity = max(0, min(255, round(255 * (1.0 - p))))
        if opacity <= 0:
            return
        color = qt.QtGui.QColor(255, 255, 255, opacity)
        self._draw_cloud(painter, switch_rect.left() - size * 0.05, switch_rect.top() + size * 0.38,
                          size * 0.38, color)
        self._draw_cloud(painter, switch_rect.right() - size * 0.25, switch_rect.top() + size * 0.58,
                          size * 0.30, color)

    def _paint_sun_and_moon(self, painter, cx: float, cy: float, size: float, p: float) -> None:
        orbit_radius = size * 0.33

        sun_angle = math.radians(self.lerp(-90, 90, p))
        sun_x, sun_y = cx + math.cos(sun_angle) * orbit_radius, cy + math.sin(sun_angle) * orbit_radius
        sun_opacity = max(0, min(255, round(255 * (1.0 - p))))
        self._draw_sun(painter, sun_x, sun_y, size * 0.15, sun_opacity)

        moon_angle = math.radians(self.lerp(90, 270, p))
        moon_x, moon_y = cx + math.cos(moon_angle) * orbit_radius, cy + math.sin(moon_angle) * orbit_radius
        moon_opacity = max(0, min(255, round(255 * p)))
        self._draw_moon(painter, moon_x, moon_y, size * 0.15, moon_opacity)

    def _paint_mountains(self, painter, switch_rect, size: float, p: float) -> None:
        color_1 = self.lerp_color(qt.QtGui.QColor("#4ca382"), qt.QtGui.QColor("#162238"), p)
        color_2 = self.lerp_color(qt.QtGui.QColor("#65b899"), qt.QtGui.QColor("#1e2c45"), p)

        self._draw_mountain(painter, [
            (switch_rect.left() - size * 0.15, switch_rect.bottom() - size * 0.12),
            (switch_rect.left() + size * 0.25, switch_rect.top() + size * 0.48),
            (switch_rect.left() + size * 0.60, switch_rect.bottom() - size * 0.12),
        ], color_1)

        self._draw_mountain(painter, [
            (switch_rect.right() - size * 0.45, switch_rect.bottom() - size * 0.10),
            (switch_rect.right() - size * 0.20, switch_rect.top() + size * 0.57),
            (switch_rect.right() + size * 0.10, switch_rect.bottom() - size * 0.10),
        ], color_2)

    def _paint_terrain(self, painter, switch_rect, size: float, p: float) -> None:
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.lerp_color(qt.QtGui.QColor("#348e6a"), qt.QtGui.QColor("#0d1526"), p))
        terrain_rect = qt.QtCore.QRectF(
            switch_rect.left() - size * 0.15, switch_rect.bottom() - size * 0.32,
            size * 1.3, size * 0.55,
        )
        painter.drawEllipse(terrain_rect)

    def _paint_trees(self, painter, switch_rect, size: float, p: float) -> None:
        for x_factor, y_factor, scale in ((0.30, 0.76, 0.75), (0.72, 0.78, 1.0), (0.50, 0.86, 0.60)):
            tree_x = switch_rect.left() + switch_rect.width() * x_factor
            tree_y = switch_rect.top() + switch_rect.height() * y_factor
            self._draw_tree(painter, tree_x, tree_y, size * 0.24 * scale, p)

    # --- draw helpers ---

    @staticmethod
    def _draw_circle(painter, x, y, radius, color) -> None:
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(qt.QtCore.QRectF(x - radius, y - radius, radius * 2, radius * 2))

    def _draw_cloud(self, painter, x, y, width, color) -> None:
        painter.save()
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        height = width * 0.35
        painter.drawRoundedRect(qt.QtCore.QRectF(x, y, width, height), height / 2, height / 2)
        painter.drawEllipse(qt.QtCore.QRectF(x + width * 0.25, y - height * 0.45, height * 1.4, height * 1.4))
        painter.restore()

    def _draw_sun(self, painter, x, y, radius, opacity) -> None:
        painter.save()
        glow = qt.QtGui.QColor(255, 211, 0, round(opacity * 0.25))
        self._draw_circle(painter, x, y, radius * 1.7, glow)
        self._draw_circle(painter, x, y, radius, qt.QtGui.QColor(255, 220, 40, opacity))
        painter.restore()

    def _draw_moon(self, painter, x, y, radius, opacity) -> None:
        painter.save()
        self._draw_circle(painter, x, y, radius, qt.QtGui.QColor(220, 225, 235, opacity))
        crater_color = qt.QtGui.QColor(110, 115, 125, round(opacity * 0.55))
        self._draw_circle(painter, x - radius * 0.35, y - radius * 0.25, radius * 0.18, crater_color)
        self._draw_circle(painter, x - radius * 0.30, y + radius * 0.28, radius * 0.13, crater_color)
        self._draw_circle(painter, x + radius * 0.28, y + radius * 0.20, radius * 0.15, crater_color)
        painter.restore()

    def _draw_mountain(self, painter, points, color) -> None:
        path = qt.QtGui.QPainterPath()
        path.moveTo(qt.QtCore.QPointF(*points[0]))
        for x, y in points[1:]:
            path.lineTo(qt.QtCore.QPointF(x, y))
        path.closeSubpath()
        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def _draw_tree(self, painter, x, y, height, p: float) -> None:
        painter.save()
        tree_color = self.lerp_color(qt.QtGui.QColor("#15452d"), qt.QtGui.QColor("#070c14"), p)
        trunk_color = self.lerp_color(qt.QtGui.QColor("#704629"), qt.QtGui.QColor("#080d14"), p)

        path = qt.QtGui.QPainterPath()
        path.moveTo(x, y - height)
        path.lineTo(x + height * 0.55, y - height * 0.45)
        path.lineTo(x + height * 0.25, y - height * 0.45)
        path.lineTo(x + height * 0.75, y - height * 0.10)
        path.lineTo(x + height * 0.35, y - height * 0.10)
        path.lineTo(x + height, y + height * 0.30)
        path.lineTo(x - height, y + height * 0.30)
        path.lineTo(x - height * 0.35, y - height * 0.10)
        path.lineTo(x - height * 0.75, y - height * 0.10)
        path.lineTo(x - height * 0.25, y - height * 0.45)
        path.lineTo(x - height * 0.55, y - height * 0.45)
        path.closeSubpath()

        painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(tree_color)
        painter.drawPath(path)

        painter.setBrush(trunk_color)
        trunk_width, trunk_height = height * 0.18, height * 0.35
        painter.drawRoundedRect(
            qt.QtCore.QRectF(x - trunk_width / 2, y + height * 0.15, trunk_width, trunk_height), 2, 2)
        painter.restore()


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext

    with QtApplicationContext():
        window = qt.QtWidgets.QWidget()
        window.resize(300, 300)
        layout = qt.QtWidgets.QVBoxLayout(window)
        layout.setSpacing(20)
        layout.addStretch()

        toggle = OrbitThemeToggle()
        layout.addWidget(toggle, alignment=qt.QtCore.Qt.AlignmentFlag.AlignCenter)

        label = qt.QtWidgets.QLabel("DAY")
        label.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignCenter)
        toggle.toggled.connect(lambda checked: label.setText("NIGHT" if checked else "DAY"))
        layout.addWidget(label)
        layout.addStretch()

        window.show()