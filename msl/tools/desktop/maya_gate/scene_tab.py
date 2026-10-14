# tools/desktop/maya_gate/scene_tab.py
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.link import scene_rate, scene_settings
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.widgets.atoms.checkboxes.base_checkbox import BaseCheckbox
from msl_tools.msl.ui.widgets.atoms.comboboxes.base_combo_box import BaseComboBox
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl


class SceneTab(qt.QtWidgets.QWidget):
    """Maya Gate's "Scene" tab: what a Maya of the current environment does with scenes.

    NEW SCENES — what one starts with (at Maya's start and on every File › New):
    - Frame rate: "As is" (Maya's own preference left alone) or 24 / 25 / 30 / 48 / 50 / 60
      (MSL_GATE_SCENE_FPS), with the check on opening: say so - in Maya and in the hub's log - when
      an opened scene or a .ma reference is at another rate (MSL_GATE_SCENE_CHECK). The scene is
      never changed.
    - Range (playback + animation range, "1-120"), Units (mm / cm / m), Up axis (Y / Z).
    ANIMATION — set once when Maya starts: Playback (every frame / real-time / × 0.5 / × 2), New keys
    (the global tangent type), Auto key (on / off).

    Every setting starts "As is": nothing is passed and Maya's own preference stays. The launch
    carries the set ones (core/link/scene_settings.py), tools/maya/scene_defaults.py puts them in
    place; a scene that exists keeps its own rate, units and range.

    Stored per environment in the page's config branch `scene`:
    {"<env>": {"fps", "check", "range", "units", "up", "speed", "tangents", "autokey"}}.
    Takes effect at the next start of a Maya in that environment.
    """

    KEEP = "As is"
    RATES = list(scene_rate.UNITS)   # "24", "25", "30", ...

    def __init__(self, config, environment: str, parent=None):
        super().__init__(parent)
        self._config = config          # the page's `scene` node: {"<env>": {"fps": "30", "check": True, ...}}
        self._environment = environment

        self._title = qt.QtWidgets.QLabel()
        self._title.setObjectName("sceneTitle")
        hint = qt.QtWidgets.QLabel(
            "What a new scene starts with — at Maya’s start and on every File › New. "
            "Scenes that exist keep their own rate, units and range.")
        hint.setObjectName("sceneHint")
        hint.setWordWrap(True)

        self._rate = SegmentedControl([self.KEEP] + self.RATES, self.KEEP)
        self._rate.setToolTip("As is: Maya’s own preference is left as it is.\n"
                              "A number: new scenes of this environment start at that many frames per second.")
        self._range = qt.QtWidgets.QLineEdit()
        self._range.setObjectName("sceneRange")
        self._range.setPlaceholderText("as is")
        self._range.setFixedWidth(96)
        self._range.setToolTip("Playback and animation range of new scenes: first and last frame, e.g. 1-120.\n"
                               "Empty: Maya’s own preference.")
        self._units = SegmentedControl([self.KEEP] + list(scene_settings.UNITS), self.KEEP)
        self._units.setToolTip("The linear unit of new scenes (Maya’s working units).")
        self._up = SegmentedControl([self.KEEP] + list(scene_settings.UP_AXES.values()), self.KEEP)
        self._up.setToolTip("Maya’s up axis — a preference of Maya, not of a scene.")
        # a drop-down, not a SegmentedControl: five options as wide as "Every frame" made the window ~100 px wider
        self._speed = BaseComboBox([self.KEEP] + [shown for shown, _value in scene_settings.SPEEDS.values()],
                                   self.KEEP, enable_wheel=False)
        self._speed.setToolTip("Playback speed: every frame (may run slower than the rate) or in real time.")
        self._tangents = BaseComboBox([self.KEEP] + [shown for shown, *_tangents in scene_settings.TANGENTS.values()],
                                      self.KEEP, enable_wheel=False)
        self._tangents.setToolTip("The tangents new keys get (Maya’s default in / out tangent).\n"
                                  "Stepped: auto in, stepped out — for blocking.")
        self._autokey = SegmentedControl([self.KEEP] + list(scene_settings.AUTO_KEY.values()), self.KEEP)
        self._autokey.setToolTip("Auto key when Maya starts.")
        self._check = BaseCheckbox("When a scene opens, say so if it or a reference is at another frame rate")
        self._check.setToolTip("A warning in Maya’s Script Editor (and so in this hub’s log) and a "
                               "message in the viewport.\nNothing in the scene is changed — a scene’s "
                               "rate changed afterwards moves its keys. References: .ma files only.")
        self._note = qt.QtWidgets.QLabel()
        self._note.setObjectName("sceneNote")
        self._note.setWordWrap(True)

        grid = qt.QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._row(grid, 0, "Frame rate", self._rate, self._hint("fps"))
        self._row(grid, 1, "Range", self._range, self._hint("first – last frame, e.g. 1-120"))
        self._row(grid, 2, "Units", self._units)
        self._row(grid, 3, "Up axis", self._up)   # its own row: beside Units it made the window ~30 px wider
        grid.setColumnStretch(3, 1)

        animation = qt.QtWidgets.QLabel("Animation")
        animation.setObjectName("sceneTitle")
        animation_hint = qt.QtWidgets.QLabel("Set when Maya starts — for every scene of the session.")
        animation_hint.setObjectName("sceneHint")
        animation_grid = qt.QtWidgets.QGridLayout()
        animation_grid.setContentsMargins(0, 0, 0, 0)
        animation_grid.setHorizontalSpacing(10)
        animation_grid.setVerticalSpacing(8)
        self._row(animation_grid, 0, "Playback", self._speed)
        self._row(animation_grid, 1, "New keys", self._tangents, self._caption("Auto key"), self._autokey)
        animation_grid.setColumnStretch(3, 1)
        for caption_grid in (grid, animation_grid):   # one caption column for both grids
            caption_grid.setColumnMinimumWidth(0, 70)

        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._title)
        layout.addWidget(hint)
        layout.addLayout(grid)
        layout.addWidget(self._check)
        layout.addSpacing(8)
        layout.addWidget(animation)
        layout.addWidget(animation_hint)
        layout.addLayout(animation_grid)
        layout.addSpacing(6)
        layout.addWidget(self._note)
        layout.addStretch()

        self._showing = False
        self._show_environment()
        self._rate.current_changed.connect(self._on_rate)
        self._check.toggled.connect(self._on_check)
        self._range.editingFinished.connect(self._on_range)
        self._range.textEdited.connect(self._on_range_typed)
        self._units.current_changed.connect(lambda text: self._store("units", "" if text == self.KEEP else text))
        self._up.current_changed.connect(lambda text: self._store("up", "" if text == self.KEEP else text.lower()))
        self._speed.currentTextChanged.connect(lambda text: self._store("speed", self._key_of(scene_settings.SPEEDS, text)))
        self._tangents.currentTextChanged.connect(
            lambda text: self._store("tangents", self._key_of(scene_settings.TANGENTS, text)))
        self._autokey.current_changed.connect(lambda text: self._store("autokey", "" if text == self.KEEP else text.lower()))

    # --- building ---------------------------------------------------------------------

    @staticmethod
    def _caption(text: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("sceneCaption")
        return label

    @staticmethod
    def _hint(text: str) -> qt.QtWidgets.QLabel:
        label = qt.QtWidgets.QLabel(text)
        label.setObjectName("sceneHint")
        return label

    def _row(self, grid, row: int, caption: str, *widgets) -> None:
        grid.addWidget(self._caption(caption), row, 0)
        holder = qt.QtWidgets.QHBoxLayout()
        holder.setContentsMargins(0, 0, 0, 0)
        holder.setSpacing(10)
        for widget in widgets:
            holder.addWidget(widget)
        holder.addStretch()
        grid.addLayout(holder, row, 1, 1, 3)

    @staticmethod
    def _key_of(choices: dict, shown: str) -> str:
        return next((key for key, value in choices.items() if value[0] == shown), "")

    # --- the environment's settings -------------------------------------------------

    def settings_for(self, environment: str) -> dict:
        """{"fps": "30" or "", "check": bool, "range": "1 120" or "", "units", "up", "speed", "tangents",
        "autokey"} of `environment` (defaults where nothing is stored)."""
        stored = self._config.get(environment) if hasattr(self._config, "get") else None
        fps = str(stored.get("fps", "") if stored is not None else "")
        check = bool(stored.get("check", True)) if stored is not None else True
        settings = {"fps": fps if fps in self.RATES else "", "check": check}
        settings.update(scene_settings.cleaned(stored))
        return settings

    def set_environment(self, environment: str) -> None:
        self._environment = environment
        self._show_environment()

    def _show_environment(self) -> None:
        settings = self.settings_for(self._environment)
        self._showing = True
        try:
            self._title.setText("New scenes in %s" % self._environment)
            self._rate.set_current(settings["fps"] or self.KEEP)
            self._check.setChecked(settings["check"])
            span = scene_settings.parse_range(settings["range"])
            self._range.setText("%s-%s" % span if span else "")
            self._set_range_state("")
            self._units.set_current(settings["units"] or self.KEEP)
            self._up.set_current(scene_settings.UP_AXES.get(settings["up"], self.KEEP))
            self._speed.setCurrentText(scene_settings.SPEEDS[settings["speed"]][0] if settings["speed"] else self.KEEP)
            self._tangents.setCurrentText(scene_settings.TANGENTS[settings["tangents"]][0] if settings["tangents"]
                                          else self.KEEP)
            self._autokey.set_current(scene_settings.AUTO_KEY.get(settings["autokey"], self.KEEP))
        finally:
            self._showing = False
        self._show_note()

    def _store(self, key: str, value) -> None:
        if self._showing:
            return
        current = self.settings_for(self._environment)
        current[key] = value
        self._config[self._environment] = current
        self._show_note()

    def _on_rate(self, text: str) -> None:
        self._store("fps", "" if text == self.KEEP else text)

    def _on_check(self, checked: bool) -> None:
        self._store("check", bool(checked))

    def _on_range_typed(self, _text: str) -> None:
        self._set_range_state("")

    def _on_range(self) -> None:
        """Enter / leaving the field: an empty one = as is; one that isn't a range is marked and not kept."""
        text = self._range.text().strip()
        if not text:
            self._set_range_state("")
            self._store("range", "")
            return
        span = scene_settings.parse_range(text)
        if span is None:
            self._set_range_state("error")
            self._note.setText("Range: first and last frame, the first smaller — e.g. 1-120. Not kept.")
            return
        self._set_range_state("")
        self._range.setText("%s-%s" % span)
        self._store("range", scene_settings.range_text(span))

    def _set_range_state(self, state: str) -> None:
        if (self._range.property("state") or "") != state:
            self._range.setProperty("state", state)   # maya_gate.qss: the error border
            repolish(self._range)

    def _show_note(self) -> None:
        settings = self.settings_for(self._environment)
        said = []
        if settings["fps"]:
            said.append("new scenes at %s fps%s" % (settings["fps"], ", a word when an opened scene or a reference "
                                                    "isn’t" if settings["check"] else ""))
        said += scene_settings.describe(settings)
        if said:
            self._note.setText("→ from the next start of a Maya in %s: %s." % (self._environment, "; ".join(said)))
        else:
            self._note.setText("Everything as is: Maya’s own preferences decide; nothing is checked on opening.")
        self._check.setEnabled(bool(settings["fps"]))
