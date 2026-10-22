# tools/maya/animation/keys_row.py
"""The Animation tool's tool GROUPS under the sliders - laid out FLAT for now (the user's call while the
tools are being tested: every tool its own visible button, no "last used" buttons with menus). Each
group is a tinted block with a colored edge in its hue and its name in small capitals first; the
buttons wrap inside it. In the reference's own order:

    PRECISE    − [step] +   the picked channels / keys by an exact step (precise.py)
    NUDGE      ◀ [N] ▶ and the rest of nudging, spacing and inbetweens
    DEFAULT    reset the pose (all, move, rotate, scale, all three), snapshot of a preferred default pose
    BAKE       bake on 1-4 / N, from the last selected, infinity; share / copy / paste key times
    CLEAN UP · COLOR KEYS · PLAY   (phase 2's other tools)

What each action does and acts on: keys_scene.py / precise.py / default_pose.py (one undo step each).
The row only says what happened (`said(text, state)` -> the window's header) and keeps its numbers
in the panel's settings (`frames`, `precise`, the bake / share options).
"""
from __future__ import annotations

from dataclasses import dataclass

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.animation import keys as ky
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField
from msl_tools.msl.tools.maya.rename.buttons import QuickButton
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.layouts.flow_layout import FlowLayout

N, STEP = ky.N, ky.STEP     # stand for the frames field's / the precise field's number in an action's arguments
fill = ky.fill

BUTTON = 24     # a tool button's height (and width without a badge)


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    tip: str
    icon: str
    call: str           # the module's function
    args: tuple = ()
    badge: str = ""     # a few letters beside the icon, where icons alone would look alike
    tone: str = ""      # the button's own hue ("" = its group's)
    module: str = "keys_scene"
    options: str = ""   # OPTIONS key: its right click offers those choices


# what each group is: key, title, hue, its tools ("frames" / "precise" = that number field's place)
GROUPS = (
    ("precise", "Precise", "blue", (
        Action("minus", "Precise −", "The picked channels (Channel Box) - or the picked keys (Graph Editor) - "
               "lowered by exactly the step. Ctrl: a tenth of it, Shift: five steps", "minus", "precise", ("-STEP",), module="precise"),
        "precise",
        Action("plus", "Precise +", "The picked channels - or the picked keys - raised by exactly the step. Ctrl: a tenth of it, "
               "Shift: five steps",
               "add", "precise", (STEP,), module="precise"),
    )),
    ("nudge", "Nudge", "teal", (
        Action("left", "Nudge left", "The keys in play N frames left: the picked keys, the range's, or the current "
               "frame's (the time follows; on an empty frame the nearest key comes to it)", "key_nudge_left",
               "nudge", ("-N", "")),
        "frames",
        Action("right", "Nudge right", "The keys in play N frames right", "key_nudge_right", "nudge", (N, "")),
        Action("slide_left", "Time offsetter left", "The keys stay where they are; the motion slides N frames left "
               "under them", "timeline", "time_offset", (N,), badge="◀"),
        Action("slide_right", "Time offsetter right", "The keys stay; the motion slides N frames right under them",
               "timeline", "time_offset", ("-N",), badge="▶"),
        Action("all_left", "All keys left", "Every key of the selected objects N frames left (the time follows)",
               "key_nudge_left", "nudge", ("-N", "all"), badge="all"),
        Action("all_right", "All keys right", "Every key of the selected objects N frames right",
               "key_nudge_right", "nudge", (N, "all"), badge="all"),
        Action("scene_left", "Scene left", "Every key in the scene N frames left", "scene", "nudge",
               ("-N", "scene"), badge="◀"),
        Action("scene_right", "Scene right", "Every key in the scene N frames right", "scene", "nudge",
               (N, "scene"), badge="▶"),
        Action("space", "Set inbetween", "The picked keys (or the range's) laid out N frames apart from the first "
               "one - the keys after them stay", "keys_space", "set_spacing", (N,), badge="N"),
        Action("space_1", "Set inbetween on ones", "The picked keys (or the range's) one frame apart", "keys_space",
               "set_spacing", (1,), badge="1"),
        Action("space_2", "Set inbetween on twos", "Two frames apart", "keys_space", "set_spacing", (2,),
               badge="2"),
        Action("space_3", "Set inbetween on threes", "Three frames apart", "keys_space", "set_spacing", (3,),
               badge="3"),
        Action("space_4", "Set inbetween on fours", "Four frames apart", "keys_space", "set_spacing", (4,),
               badge="4"),
        Action("insert", "Insert inbetween", "N empty frames after the current frame - or after each picked key, or "
               "after every key in the highlighted range", "keys_insert", "inbetween", (N,)),
        Action("remove", "Remove inbetween", "N frames taken out after the current frame (the picked keys, the "
               "range's keys) - never past the key before", "keys_remove", "inbetween", ("-N",)),
        Action("insert_scene", "Insert inbetween · scene", "N empty frames after the current frame, on every curve "
               "of the scene", "keys_insert", "inbetween", (N, True), badge="sc"),
        Action("remove_scene", "Remove inbetween · scene", "N frames taken out after the current frame, on every "
               "curve of the scene", "keys_remove", "inbetween", ("-N", True), badge="sc"),
    )),
    ("default", "Default pose", "pink", (
        Action("pose", "Reset pose", "Every keyable channel of the selected objects back to its default (your "
               "snapshot's value where it has one)", "restart", "reset", ("all",), module="default_pose"),
        Action("translate", "Reset translation", "Move back to its default", "move", "reset", ("translate",),
               module="default_pose"),
        Action("rotate", "Reset rotation", "Rotate back to its default", "restart", "reset", ("rotate",),
               badge="R", module="default_pose"),
        Action("scale", "Reset scale", "Scale back to its default", "grow", "reset", ("scale",),
               module="default_pose"),
        Action("trs", "Reset translation, rotation and scale", "Move, rotate and scale back to their defaults",
               "zero_out", "reset", ("trs",), module="default_pose"),
        Action("snapshot", "Snapshot preferred default pose", "The selected objects' pose kept as THEIR default - "
               "by name without the namespace, so another copy of the rig shares it. Reset and Blend to / Scale From "
               "Default use it. Right click: what is kept, forget it.", "bookmark_add", "snapshot", (),
               module="default_pose", options="default"),
    )),
    ("bake", "Baking", "violet", (
        Action("ones", "Bake on ones", "A key on every frame (picked span / range / the animation range)",
               "keys_bake", "bake", (1,), badge="1", options="bake"),
        Action("twos", "Bake on twos", "A key every 2 frames, the keys between go", "keys_bake", "bake", (2,),
               badge="2", options="bake"),
        Action("threes", "Bake on threes", "A key every 3 frames", "keys_bake", "bake", (3,), badge="3",
               options="bake"),
        Action("fours", "Bake on fours", "A key every 4 frames", "keys_bake", "bake", (4,), badge="4",
               options="bake"),
        Action("every", "Bake every N frames", "A key every N frames (the Nudge group's number)", "keys_bake",
               "bake", (N,), badge="N", options="bake"),
        Action("from_last", "Bake from the last selected", "The other selected objects get their keys exactly on "
               "the last one's key times (the range / the animation range); constraints baked and deleted",
               "keys_bake", "bake_from_last", (), badge="last", options="bake"),
        Action("infinity", "Bake infinity", "A cycling curve's infinity made real keys in the highlighted range "
               "(else the playback range)", "infinity", "bake_infinity", (), options="bake"),
        Action("share", "Share key times", "Every curve of the selected objects gets a key wherever any of them has "
               "one - the shape kept", "keys_share", "share_times", (), options="times"),
        Action("share_last", "Share from the last selected", "The others get a key wherever the object selected "
               "LAST has one", "keys_share", "share_times", (True,), badge="last", options="times"),
        Action("copy", "Copy key times", "Keep the key times in play (picked, the range's, else the selection's) "
               "to paste them", "copy", "copy_times", ()),
        Action("copy_color", "Copy color key times", "Keep the times of the keys of ONE color - the color of the key "
               "on the current frame", "copy", "copy_times", (True,), badge="col"),
        Action("paste_merge", "Paste merge key times", "Keys at the copied times, the selection's own stay",
               "paste", "paste_times", (ky.MERGE,), badge="M"),
        Action("paste_insert", "Paste insert key times", "Replace, with the first copied time on the current frame",
               "paste", "paste_times", (ky.INSERT,), badge="I"),
        Action("paste_replace", "Paste replace key times", "Keys at the copied times; keys inside their span on "
               "other frames go", "paste", "paste_times", (ky.REPLACE,), badge="R"),
        Action("paste_tint", "Paste tint key times", "The selection's keys on the copied times take the copied "
               "color - no key is added", "paste", "paste_tint", (), badge="col"),
    )),
    ("tangents", "Tangents", "red", (
        Action("cycle", "Cycle match tangent", "The last key of each curve takes the first key's tangent, so a cycle "
               "flows through its seam. Shift: the first key takes the last's. Right click: first / last key",
               "tangent_cycle", "cycle", (), module="tangents_scene", options="cycle"),
        Action("best_guess", "Best guess tangent", "Maya's own tangents picked by the keys: clamped on the ends and "
               "the extremes, auto between - a better first pass than auto everywhere", "tangent_best_guess",
               "tangent", ("best_guess",), module="tangents_scene", options="tangent"),
        Action("polished", "Polished tangent", "Smooth without overshooting: extremes and holds stay, the keys "
               "between ease through, the ends lean into the curve", "tangent_polished", "tangent", ("polished",),
               module="tangents_scene", options="tangent"),
        Action("flow", "Flow tangent", "The momentum carried through every key - smooth even if it overshoots "
               "(a tail wagging)", "tangent_flow", "tangent", ("flow",), module="tangents_scene", options="tangent"),
        Action("bounce", "Bounce tangent", "Sharp: each side points at its neighbor - hitting a wall, no easing. "
               "On in tangents only: shark fins", "tangent_bounce", "tangent", ("bounce",), module="tangents_scene",
               options="tangent"),
        Action("auto", "Auto tangent", "Maya's auto tangents", "tangent_auto", "tangent", ("auto",),
               module="tangents_scene", options="native"),
        Action("spline", "Spline tangent", "Maya's spline tangents", "tangent_spline", "tangent", ("spline",),
               module="tangents_scene", options="native"),
        Action("clamped", "Clamped tangent", "Maya's clamped tangents", "tangent_clamped", "tangent", ("clamped",),
               module="tangents_scene", options="native"),
        Action("linear", "Linear tangent", "Maya's linear tangents", "tangent_linear", "tangent", ("linear",),
               module="tangents_scene", options="native"),
        Action("flat", "Flat tangent", "Maya's flat tangents", "tangent_flat", "tangent", ("flat",),
               module="tangents_scene", options="native"),
        Action("step", "Step tangent", "Maya's stepped tangents (the out side)", "tangent_step", "tangent",
               ("step",), module="tangents_scene", options="step"),
        Action("plateau", "Plateau tangent", "Maya's plateau tangents", "tangent_plateau", "tangent", ("plateau",),
               module="tangents_scene", options="native"),
    )),
    ("clean", "Clean up", "orange", (
        Action("snap", "Smart snap", "Keys between frames to the nearest whole frame, holding the pose there",
               "snap_grid", "smart_snap", ()),
        Action("redundant", "Remove redundant keys", "Keys that don't change the curve", "sweep",
               "remove_redundant", ()),
        Action("static", "Remove static curves", "Curves that hold one value all along (the value stays)",
               "minus", "remove_static", ()),
        Action("crop", "Crop to the range", "Keys outside the highlighted range (or the picked keys' span) go, "
               "the motion inside kept", "crop", "crop", ()),
        Action("reverse", "Reverse", "The animation backwards inside the picked span / the range / the playback "
               "range", "reverse", "reverse", ()),
        Action("clear", "Clear animation", "Every curve of the selected objects deleted (the pose stays)",
               "clear", "clear", ()),
    )),
    ("color", "Color keys", "red", (
        Action("red", "Tint red", "Plain keys - the poses (Maya's own key flags, nothing added)", "keyframe",
               "tint", (ky.RED,), tone="red"),
        Action("yellow", "Tint yellow", "Breakdowns, inbetweens (Maya's special tick)", "keyframe", "tint",
               (ky.YELLOW,), tone="yellow"),
        Action("green", "Tint green", "Baked keys (Maya's breakdown key: it keeps its place between its "
               "neighbors when they move)", "keyframe", "tint", (ky.GREEN,), tone="green"),
        Action("red_scene", "Every key in the scene red", "All the colors in the scene cleared", "scene",
               "tint_scene_red", (), tone="red"),
        Action("remove_red", "Remove red keys", "Every red key of the selection", "clear", "remove_color",
               (ky.RED,), tone="red"),
        Action("remove_yellow", "Remove yellow keys", "Every yellow key of the selection", "clear",
               "remove_color", (ky.YELLOW,), tone="yellow"),
        Action("remove_green", "Remove green keys", "Every green key of the selection", "clear", "remove_color",
               (ky.GREEN,), tone="green"),
    )),
    ("play", "Play", "green", (
        Action("keys", "Play keys", "Playback from key to key, each pose held until the next (again: stop)",
               "play", "play", ("keys",), badge="key"),
        Action("color_keys", "Play color keys", "Only the keys of the color the current frame's key has",
               "play", "play", ("color",), badge="col"),
        Action("twos", "Play on twos", "Every second frame, held for two", "play", "play", (2,), badge="2"),
        Action("threes", "Play on threes", "Every third frame", "play", "play", (3,), badge="3"),
        Action("fours", "Play on fours", "Every fourth frame", "play", "play", (4,), badge="4"),
    )),
)

REFUSED = ("Nothing", "Not ", "Copy key times first", "Pick ", "Highlight", "Select ", "Bake every", "No cycling",
           "No key on that side", "No key of that color", "The last selected has no key",
           "No key of the selection is on", "No channel", "No default pose")


def actions() -> list:
    """Every Action of the row, in order (for tests and the hotkeys' cross-check)."""
    return [item for _key, _title, _tone, items in GROUPS for item in items if isinstance(item, Action)]


def run(call: str, args: tuple, frames: float, say: bool = False, module: str = "keys_scene",
        step: float = 1.0) -> str:
    """One function of the animation package's `module` with the numbers filled in."""
    import importlib
    target = importlib.import_module(f"msl_tools.msl.tools.maya.animation.{module}")
    return getattr(target, call)(*fill(args, frames, step), say=say)


class _Group(qt.QtWidgets.QFrame):
    """One group: a tinted block with a colored edge (animation.qss: QFrame#animationGroup[tone]), its name in
    small capitals first, then its widgets - all wrapping like words."""

    def __init__(self, title: str, tone: str, parent=None):
        super().__init__(parent)
        self.setObjectName("animationGroup")
        self.setProperty("tone", tone)
        self.setToolTip(title)
        self.flow = FlowLayout(self, spacing=3)
        self.flow.setContentsMargins(7, 4, 5, 4)
        caption = qt.QtWidgets.QLabel(title.upper())
        caption.setObjectName("animationGroupTitle")
        caption.setProperty("tone", tone)
        caption.setFixedHeight(BUTTON)
        self.flow.addWidget(caption)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(width)

    def sizeHint(self) -> qt.QtCore.QSize:
        width = max(self.width(), 200)
        return qt.QtCore.QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> qt.QtCore.QSize:
        return qt.QtCore.QSize(120, self.heightForWidth(max(self.width(), 120)))


class KeysRow(qt.QtWidgets.QWidget):
    """The tool groups. Signals: said(text, state) - what an action did ("done" / "error")."""

    said = qt.QtCore.Signal(str, str)

    def __init__(self, get, put, parent=None):
        super().__init__(parent)
        self._get, self._put = get, put
        self.buttons = {}        # "group.key" -> its button (tests, hotkeys' cross-check)
        layout = qt.QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.frames = DragNumberField(float(get("frames", 1.0)), 0.1, 1000.0, 1.0, width=36, decimals=1)
        self.frames.setObjectName("animationFrames")
        self.frames.setToolTip("Frames\nHow many frames a nudge, an inbetween, the spacing and \"bake every N\" use. "
                               "Wheel / Up / Down step it, a middle-drag scrubs it; right click: ready values.")
        self.frames.value_changed.connect(lambda value: self._put("frames", float(value)))
        self.frames.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.frames.customContextMenuRequested.connect(self._frames_menu)
        self.precise = DragNumberField(float(get("precise", 1.0)), 0.001, 100000.0, 1.0, width=52, decimals=3)
        self.precise.setObjectName("animationFrames")
        self.precise.setToolTip("Precise step\nHow much − and + change a value by (in the channel's own units: "
                                "degrees for a rotation). Right click: ready values.")
        self.precise.value_changed.connect(lambda value: self._put("precise", float(value)))
        self.precise.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.precise.customContextMenuRequested.connect(self._precise_menu)
        for field in (self.frames, self.precise):     # never handed the keyboard when the window opens
            field.setFocusPolicy(qt.QtCore.Qt.FocusPolicy.ClickFocus)
        self.groups = {}
        for group, title, tone, items in GROUPS:
            box = _Group(title, tone)
            for item in items:
                if item == "frames":
                    box.flow.addWidget(self.frames)
                elif item == "precise":
                    box.flow.addWidget(self.precise)
                else:
                    box.flow.addWidget(self._button(group, item))
            self.groups[group] = box
            layout.addWidget(box)

    def _button(self, group: str, action: Action) -> QuickButton:
        icons = UiResources().iconManager
        button = QuickButton(icons.get_icon(action.icon, sub_folder="actions"), action.badge or action.title[:3],
                             f"{action.title}\n{action.tip}", icon_size=16)
        button.setObjectName("animationTool")
        tone = action.tone or next(t for g, _title, t, _i in GROUPS if g == group)
        button.setProperty("tone", tone)
        if action.badge and button._source_icon is not None:
            button.setText(action.badge)
        button.setFixedHeight(BUTTON)
        if not button.text():
            button.setFixedWidth(BUTTON)
        button.clicked.connect(lambda _checked=False, a=action: self._run(a))
        if action.options:
            button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda _pos, b=button, a=action: self._options_menu(b, a))
        self.buttons[f"{group}.{action.key}"] = button
        return button

    # ------------------------------------------------------------------ number fields

    PRESETS = (1, 2, 3, 4, 5, 10, 20, 50, 100)     # the reference's "Set Nudge Value" choices
    PRECISE_PRESETS = (0.001, 0.01, 0.1, 0.5, 1, 5, 10, 45, 90)

    def _frames_menu(self, _position) -> None:
        self._number_menu(self.frames, "FRAMES", self.PRESETS)

    def _precise_menu(self, _position) -> None:
        self._number_menu(self.precise, "PRECISE STEP", self.PRECISE_PRESETS)

    def _number_menu(self, field, caption: str, values) -> None:
        menu = self._new_menu()
        title = menu.addAction(caption)
        title.setEnabled(False)
        for value in values:
            item = menu.addAction(f"{value:g}", lambda v=value: field.set_value(v, emit=True))
            item.setCheckable(True)
            item.setChecked(abs(field.value() - value) < 1e-9)
        menu.exec(field.mapToGlobal(qt.QtCore.QPoint(0, field.height() + 2)))

    # ------------------------------------------------------------------ options (right click)

    OPTIONS = {
        "bake": (("bake_tangents", "NEW KEYS' TANGENTS", (("type", "Keep the tangent type", "Linear stays linear, "
                  "stepped stays stepped, the rest Maya's default"), ("shape", "Keep the curve's shape", "Tangents as "
                  "steep as the curve there"), ("step", "Stepped", "Every new key stepped"))),
                 ("infinity", "BAKE INFINITY THEN", (("crop", "Crop the cycle", "Infinity set to constant"),
                  ("extend", "Extend the cycle", "The cycle goes on past the keys as it did")))),
        "times": (("share_tangents", "SHARED KEYS' TANGENTS", (("type", "Keep the tangent type", "Linear stays "
                   "linear, stepped stays stepped, the rest Maya's default"), ("shape", "Keep the curve's shape",
                   "Tangents as steep as the curve there"))),),
    }

    def _options_menu(self, button, action: Action) -> None:
        if action.options == "default":
            self._default_menu(button)
            return
        if action.options in ("tangent", "native", "step", "cycle"):
            self._tangent_menu(button, action)
            return
        menu = self._new_menu()
        first = True
        for key, caption, choices in self.OPTIONS.get(action.options, ()):
            if not first:
                menu.addSeparator()
            first = False
            title = menu.addAction(caption)
            title.setEnabled(False)
            now = self._get(key, choices[0][0]) or choices[0][0]
            for value, text, tip in choices:
                item = menu.addAction(text, lambda k=key, v=value, t=text: self._choose(k, v, t))
                item.setCheckable(True)
                item.setChecked(value == now)
                item.setToolTip(tip)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    def _default_menu(self, button) -> None:
        """The snapshot's right click: what is kept, and forgetting it (for the selection / all)."""
        try:
            from msl_tools.msl.tools.maya.animation import default_pose
            kept = default_pose.kept_names()
        except Exception:
            kept = []
        menu = self._new_menu()
        title = menu.addAction(f"PREFERRED DEFAULT POSE · {len(kept)} kept")
        title.setEnabled(False)
        for name in kept[:12]:
            line = menu.addAction(f"   {name}")
            line.setEnabled(False)
        if len(kept) > 12:
            more = menu.addAction(f"   … and {len(kept) - 12} more")
            more.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Snapshot the selected", lambda: self._say(lambda: run("snapshot", (), 0,
                                                                              module="default_pose")))
        menu.addAction("Forget the selected", lambda: self._say(lambda: run("forget", (), 0, module="default_pose")))
        menu.addAction("Forget them all", lambda: self._say(lambda: run("forget", (True,), 0,
                                                                        module="default_pose")))
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    TANGENT_LINES = (("in", "In tangent", "Only the in tangents of the keys in play"),
                     ("out", "Out tangent", "Only the out tangents"), None,
                     ("first", "First key", "Each curve's first key"), ("last", "Last key", "Each curve's last key"),
                     ("both", "Both ends", "Each curve's first and last key"), None,
                     ("all", "All keys", "Every key of the curves in play"))

    def _tangent_menu(self, button, action: Action) -> None:
        """A tangent tool's right click (the reference's): a side, the curves' end keys, or all their keys -
        each runs the tool at once."""
        from msl_tools.msl.tools.maya.animation import tangents_scene
        menu = self._new_menu()
        tool = action.args[0] if action.args else ""
        if action.options == "cycle":
            menu.addAction("First key  ·  takes the last key's tangent",
                           lambda: self._say(lambda: tangents_scene.cycle(True)))
            menu.addAction("Last key  ·  takes the first key's tangent",
                           lambda: self._say(lambda: tangents_scene.cycle(False)))
        else:
            lines = (("all", "All keys", "Every key of the curves in play"),) if action.options == "step" \
                else self.TANGENT_LINES
            for line in lines:
                if line is None:
                    menu.addSeparator()
                    continue
                key, text, tip = line
                if key in ("in", "out"):
                    do = (lambda k=key: tangents_scene.tangent(tool, "selected", k))
                else:
                    do = (lambda k=key: tangents_scene.tangent(tool, k))
                item = menu.addAction(text, lambda d=do: self._say(d))
                item.setToolTip(tip)
            if action.options in ("native", "step"):
                menu.addSeparator()
                item = menu.addAction("Set Maya's global tangent",
                                      lambda: self._say(lambda: tangents_scene.set_global(tool)))
                item.setToolTip(f"New keys get {action.title.lower()}s (Maya's preference)")
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height() + 2)))

    def _choose(self, key: str, value: str, text: str) -> None:
        self._put(key, value)
        self.said.emit(text, "")

    def _run(self, action: Action) -> None:
        args = action.args
        if action.call == "cycle":               # Shift: the first key takes the last's (the reference's)
            modifiers = qt.QtWidgets.QApplication.keyboardModifiers()
            args = (bool(modifiers & qt.QtCore.Qt.KeyboardModifier.ShiftModifier),)
        if action.module == "precise":           # Ctrl = a tenth of the step, Shift = five steps (precise.py)
            modifiers = qt.QtWidgets.QApplication.keyboardModifiers()
            args = args + (ky.precise_times(bool(modifiers & qt.QtCore.Qt.KeyboardModifier.ControlModifier),
                                     bool(modifiers & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)),)
        frames, step = self.frames.commit_text(), self.precise.commit_text()   # typed but not entered yet
        for field in (self.frames, self.precise):
            if field.hasFocus():
                field.clearFocus()                # the number is taken: the field lets go of the keyboard
        self._say(lambda: run(action.call, args, frames, module=action.module, step=step))

    # ------------------------------------------------------------------ helpers

    def _new_menu(self) -> "qt.QtWidgets.QMenu":
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setToolTipsVisible(True)
        return menu

    def _say(self, do) -> None:
        try:
            text = do()
        except Exception as error:     # outside Maya, or Maya refused
            self.said.emit(str(error), "error")
            return
        if text.startswith(REFUSED):
            state = "error"
        elif text.startswith(("No ", "Every key is", "Playback stopped")):
            state = ""
        else:
            state = "done"
        self.said.emit(text, state)
