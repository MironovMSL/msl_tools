# tools/desktop/maya_gate/version_row.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.maya_paths import MayaPaths
from msl_tools.msl.ui.widgets.atoms.buttons import ApplicationButton


class MayaVersionRow(qt.QtWidgets.QWidget):
    """Row of installed Maya versions (one ApplicationButton per version),
    filtered by a minimum-year cutoff — versions below it start hidden and
    slide/fade in when the cutoff moves down (out when it moves up).

    Ported from MSL_MayaGate's QCustomMayaWidget. Behavior and the
    position/opacity animation are kept as-is; two real changes:

    1. Versions now come from MayaPaths.get_available_installs(), not
       MSL_MayaGate's own Resources.maya_paths. That dict is NOT sorted
       (unlike the old Resources, which pre-sorted at discovery time) —
       this class sorts by year itself, or the row renders in whatever
       order os.iterdir() happened to return.
    2. `clicked` now emits the selected YEAR (str), not the executable
       path. Launching moved to ProcessLauncher.launch_maya(version=...),
       which resolves the executable itself — the row no longer needs to
       hand the caller a path at all.

    Signals:
        clicked(str) — emits the selected version's year, e.g. "2025".
    """

    HEIGHT = 68

    clicked = qt.QtCore.Signal(str)

    def __init__(self, min_year: str, parent=None):
        super().__init__(parent)
        self.min_year: str = min_year

        self.maya_list: list[tuple[int, int, ApplicationButton]] = []  # (index, year, widget)
        self._prev_index: int | None = None
        self._new_index: int | None = None
        self.default_pos: list | None = None
        self.positions_initialized: bool = False
        self._running_animations: list = []

        self.setFixedHeight(self.HEIGHT)
        self._build_layout()
        self._populate()

    def _build_layout(self) -> None:
        self.main_layout = qt.QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.setAlignment(qt.QtCore.Qt.AlignmentFlag.AlignTop)

    def _populate(self) -> None:
        installs = MayaPaths.get_available_installs()
        for idx, version in enumerate(sorted(installs, key=int)):
            year = int(version)
            executable = MayaPaths.get_executable_path(version)

            widget = self._create_widget(year, executable)
            self.main_layout.addWidget(widget)
            self.maya_list.append((idx, year, widget))

            if year == int(self.min_year):
                self._prev_index = idx
                self._new_index = idx
            if year < int(self.min_year):
                widget.hide()
                widget.graphicsEffect().setOpacity(0.0)

        self.main_layout.addStretch()

    def _create_widget(self, year: int, executable_path) -> ApplicationButton:
        button = ApplicationButton(f"Maya {year}", executable_path)
        # ApplicationButton emits its own application_path — the row
        # translates that into "this year was picked" for its own callers.
        button.clicked.connect(lambda _path, y=year: self.clicked.emit(str(y)))
        return button

    def on_min_year_changed(self, year) -> None:
        if self.default_pos is None:
            self.get_default_pos_widgets()

        self._new_index = self.get_index_by_year(year)
        diff = self._prev_index - self._new_index

        new_positions, changed_widgets = self.compute_positions(year)

        if diff > 0:  # show
            self.animate_maya_buttons(int(year), new_positions, changed_widgets, True)
        elif diff < 0:  # hide
            self.animate_maya_buttons(int(year), new_positions, changed_widgets, False)

        self._prev_index = self._new_index
        self.prev_positions = new_positions
        self.min_year = year

    def get_default_pos_widgets(self) -> None:
        widgets = [w for _, _, w in self.maya_list]
        if not widgets:
            self.default_pos = []
            return

        positions = [w.pos() for w in widgets]
        w, s, y = widgets[-1].width(), self.main_layout.spacing(), positions[-1].y()

        self.default_pos = [qt.QtCore.QPoint((w + s) * i, y) for i in range(len(widgets))]
        self.prev_positions, _ = self.compute_positions(int(self.min_year))

    def get_index_by_year(self, year: int) -> int | None:
        for idx, y, w in self.maya_list:
            if y == int(year):
                return int(idx)
        return None

    def compute_positions(self, year: int) -> tuple[list["qt.QtCore.QPoint"], list[ApplicationButton]]:
        all_widgets = [w for _, _, w in self.maya_list]
        new_visible = all_widgets[self._new_index:]
        old_visible = all_widgets[self._prev_index:]

        changed_widgets = [w for w in new_visible + old_visible if (w in new_visible) ^ (w in old_visible)]

        available_positions = self.default_pos[:len(all_widgets) - self._new_index]
        base_y = all_widgets[-1].pos().y()

        new_positions = [available_positions.pop(0) if (w in new_visible and available_positions)
                          else qt.QtCore.QPoint(0, base_y) for w in all_widgets]

        return new_positions, changed_widgets

    def animate_maya_buttons(self, year: int, new_positions: list, target_widgets: list, show: bool) -> None:
        self._running_animations.clear()

        widgets = [w for _, _, w in self.maya_list]
        if not widgets:
            return

        current_positions = (self.prev_positions if not self.positions_initialized else [w.pos() for w in widgets])
        self.positions_initialized = True

        base_delay = 40
        duration = 500
        main_group = qt.QtCore.QParallelAnimationGroup(self)

        if show:
            for w in target_widgets:
                w.show()
            self.main_layout.activate()
            for w, old_pos in zip(widgets, current_positions):
                w.move(old_pos)

        for i, w in enumerate(widgets):
            _, end_opacity = self.get_opacity_values(widgets, w, target_widgets, show)
            effect = w.graphicsEffect()
            current_opacity = effect.opacity()

            anim_pos = qt.QtCore.QPropertyAnimation(w, b"pos")
            anim_pos.setDuration(duration)
            anim_pos.setEasingCurve(qt.QtCore.QEasingCurve.Type.OutBack if show else qt.QtCore.QEasingCurve.Type.InBack)
            anim_pos.setStartValue(current_positions[i])
            anim_pos.setEndValue(new_positions[i])

            anim_opacity = qt.QtCore.QPropertyAnimation(effect, b"opacity")
            anim_opacity.setDuration(duration)
            anim_opacity.setEasingCurve(qt.QtCore.QEasingCurve.Type.InOutQuad)
            anim_opacity.setStartValue(current_opacity)
            anim_opacity.setEndValue(end_opacity)

            seq = qt.QtCore.QSequentialAnimationGroup(self)
            pause = qt.QtCore.QPauseAnimation(i * base_delay)
            parallel = qt.QtCore.QParallelAnimationGroup(self)
            parallel.addAnimation(anim_pos)
            parallel.addAnimation(anim_opacity)
            seq.addAnimation(pause)
            seq.addAnimation(parallel)

            main_group.addAnimation(seq)

            if not show and end_opacity == 0.0:
                main_group.finished.connect(lambda w=w: w.hide())

            self._running_animations.extend([anim_pos, anim_opacity, seq, parallel, pause])

        main_group.start(qt.QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        self._running_animations.append(main_group)

    def get_opacity_values(self, widgets: list, widget: object, target_widgets: list, show: bool) -> tuple:
        if show:
            if widget in target_widgets:
                start_opacity, end_opacity = 0.0, 1.0
            elif widget in widgets[self._new_index:]:
                start_opacity = end_opacity = 1.0
            else:
                start_opacity = end_opacity = 0.0
        else:  # hide
            if widget in target_widgets:
                start_opacity, end_opacity = 1.0, 0.0
            elif widget in widgets[self._new_index:]:
                start_opacity = end_opacity = 1.0
            else:
                start_opacity = end_opacity = 0.0

        return start_opacity, end_opacity


if __name__ == "__main__":
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.ui.widgets.themed_widget_playground_dialog import ThemedWidgetPlaygroundDialog

    with QtApplicationContext():
        dialog = ThemedWidgetPlaygroundDialog()
        row = MayaVersionRow("2024")
        row.clicked.connect(lambda year: print("selected year:", year))
        dialog.add_case("MayaVersionRow", row)
        dialog.show()