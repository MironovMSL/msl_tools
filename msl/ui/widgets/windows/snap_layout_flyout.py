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


# Each layout is a list of zones; each zone is (x, y, w, h) as fractions
# of the target screen's available geometry (0..1). The renderer groups
# zones into columns by x-origin, so keep each layout aligned to a simple
# column grid (this covers rows, columns, and a "main + stacked" combo,
# but not arbitrary free-form rect packing).
LAYOUT_HALVES          = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)]
LAYOUT_THIRDS          = [(0.0, 0.0, 1 / 3, 1.0), (1 / 3, 0.0, 1 / 3, 1.0), (2 / 3, 0.0, 1 / 3, 1.0)]
LAYOUT_MAIN_PLUS_STACK = [(0.0, 0.0, 0.6, 1.0), (0.6, 0.0, 0.4, 0.5), (0.6, 0.5, 0.4, 0.5)]
LAYOUT_QUADS           = [(0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 0.5, 0.5), (0.0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)]

DEFAULT_LAYOUTS = [LAYOUT_HALVES, LAYOUT_THIRDS, LAYOUT_MAIN_PLUS_STACK, LAYOUT_QUADS]


class _ZoneButton(qt.QtWidgets.QAbstractButton):
    """One rectangle within a layout thumbnail. Purely visual + clickable;
    colors are pushed in from the flyout so theming stays centralized
    rather than each zone owning its own palette."""

    def __init__(self, zone_rect: tuple[float, float, float, float], parent=None):
        super().__init__(parent)
        self.zone_rect = zone_rect
        self.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(qt.QtWidgets.QSizePolicy.Policy.Expanding, qt.QtWidgets.QSizePolicy.Policy.Expanding)
        self._fill_idle = qt.QtGui.QColor(255, 255, 255, 30)
        self._fill_hover = qt.QtGui.QColor(255, 255, 255, 70)
        self._border = qt.QtGui.QColor(255, 255, 255, 90)

    def set_colors(self, idle, hover, border) -> None:
        self._fill_idle = qt.QtGui.QColor(idle)
        self._fill_hover = qt.QtGui.QColor(hover)
        self._border = qt.QtGui.QColor(border)
        self.update()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        fill = self._fill_hover if self.underMouse() else self._fill_idle
        rect = qt.QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(qt.QtGui.QPen(self._border, 1))
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

    def set_zone_colors(self, idle, hover, border) -> None:
        for button in self._buttons:
            button.set_colors(idle, hover, border)


class SnapLayoutFlyout(qt.QtWidgets.QWidget):
    """Popup with a row of layout thumbnails. Emits zone_chosen(fractions)
    when the user clicks a zone, then closes itself."""

    zone_chosen = qt.QtCore.Signal(tuple)

    def __init__(self, layouts=None, parent=None):
        super().__init__(parent, qt.QtCore.Qt.WindowType.Popup
                                  | qt.QtCore.Qt.WindowType.FramelessWindowHint
                                  | qt.QtCore.Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # TODO: hook into ThemeManager once the "icon-specific vs text_*
        # token" decision (see project notes) is resolved. Native OS snap
        # flyouts also stay visually neutral regardless of app theme, so
        # a fixed dark palette here is a reasonable placeholder, not a
        # shortcut we're pretending is final.
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

    def set_theme_colors(self, background, border, zone_idle, zone_hover, zone_border) -> None:
        self._background_color = qt.QtGui.QColor(background)
        self._border_color = qt.QtGui.QColor(border)
        for thumbnail in self._thumbnails:
            thumbnail.set_zone_colors(zone_idle, zone_hover, zone_border)
        self.update()

    def _on_zone_clicked(self, zone_rect) -> None:
        self.zone_chosen.emit(zone_rect)
        self.close()

    def show_near(self, anchor_widget: qt.QtWidgets.QWidget) -> None:
        anchor_rect = qt.QtCore.QRect(
            anchor_widget.mapToGlobal(qt.QtCore.QPoint(0, 0)),
            anchor_widget.size(),
        )
        self.adjustSize()
        x = anchor_rect.right() - self.width()
        y = anchor_rect.bottom() + 6
        self.move(x, y)
        self.show()

    def paintEvent(self, event) -> None:
        painter = qt.QtGui.QPainter(self)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        path = qt.QtGui.QPainterPath()
        path.addRoundedRect(qt.QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                             self._corner_radius, self._corner_radius)
        painter.fillPath(path, self._background_color)
        painter.setPen(qt.QtGui.QPen(self._border_color, 1))
        painter.drawPath(path)


import sys
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QPushButton, QVBoxLayout, QLabel

# Подключаем функции Windows API для изменения стилей окна
user32 = ctypes.windll.user32
GWL_STYLE = -16
WS_POPUP = 0x80000000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000  # Возвращает системное изменение размеров и Aero Snap
WS_MAXIMIZEBOX = 0x00010000  # Обязательно для работы Snap Layouts
WS_MINIMIZEBOX = 0x00020000

# Системные сообщения Windows
WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083  # Позволяет "съесть" стандартную рамку
HTCAPTION = 2
HTMAXBUTTON = 9


class NativeFramelessWindow(QWidget):
    def __init__(self):
        super().__init__()
        # ВАЖНО: Больше НЕ используем FramelessWindowHint!
        # Оставляем окно обычным для Qt, но стили настроим через Win32 API.
        self.resize(800, 600)

        # Интерфейс
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Кастомная шапка
        self.title_bar = QWidget()
        self.title_bar.setStyleSheet("background-color: #202020; min-height: 40px; max-height: 40px;")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(10, 0, 0, 0)

        title_label = QLabel("Теперь подсказки Snap Layouts сверху экрана работают!")
        title_label.setStyleSheet("color: white; font-size: 13px;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self.btn_maximize = QPushButton("🗖")
        self.btn_maximize.setStyleSheet("""
            QPushButton { background-color: transparent; color: white; border: none; width: 46px; height: 40px; }
            QPushButton:hover { background-color: #303030; }
        """)
        title_layout.addWidget(self.btn_maximize)
        main_layout.addWidget(self.title_bar)

        content = QWidget()
        content.setStyleSheet("background-color: #1c1c1c;")
        main_layout.addWidget(content)

        # Применяем нативные стили Windows после создания окна
        self.apply_native_styles()

    def apply_native_styles(self):
        hwnd = int(self.winId())
        # Задаем окну стиль, в котором есть рамка (WS_THICKFRAME) и кнопки максимизации на уровне OS
        style = WS_POPUP | WS_SYSMENU | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        # Обновляем геометрию окна, чтобы применить стили
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004)

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))

        # ТРЮК №1: Убираем белую стандартную рамку Windows, которую вернул WS_THICKFRAME
        if msg.message == WM_NCCALCSIZE:
            # Возвращаем True, сообщая Windows: "клиентская зона занимает 100% окна, рамку рисовать не нужно"
            return True, 0

        # ТРЮК №2: Обрабатываем зоны кликов и наведений
        elif msg.message == WM_NCHITTEST:
            x = wintypes.SHORT(msg.lParam & 0xFFFF).value
            y = wintypes.SHORT((msg.lParam >> 16) & 0xFFFF).value
            global_pos = QPoint(x, y)

            # Кнопка развертывания (Snap Layouts по наведению)
            local_btn_pos = self.btn_maximize.mapFromGlobal(global_pos)
            if self.btn_maximize.rect().contains(local_btn_pos):
                self.btn_maximize.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
                self.btn_maximize.update()
                return True, HTMAXBUTTON
            else:
                self.btn_maximize.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                self.btn_maximize.update()

            # Шапка окна (Перетаскивание + подсказка Snap Layouts у верхнего края экрана!)
            local_bar_pos = self.title_bar.mapFromGlobal(global_pos)
            if self.title_bar.rect().contains(local_bar_pos):
                return True, HTCAPTION

        return super().nativeEvent(event_type, message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NativeFramelessWindow()
    window.show()
    sys.exit(app.exec())

