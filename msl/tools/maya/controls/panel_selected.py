# tools/maya/controls/panel_selected.py
"""The Controls panel's SELECTED card: everything that works on the controls selected in the scene —
their shape (turn, resize, steps, CVs, replace, add, copy / paste, combine, take the curve off), the
other side (mirror, the shape carried over, a live link), zero (groups, the matrix and back), drive
(constraints, the matrix, let go), show and select (on top, controls below / in the scene / of the same
shape), locators and joints on the selection, saving the selected curves as a shape — and what a
hovered button would do, shown in the preview. Methods of ControlsPanel, kept apart by concern (moved
out of panel.py as they were)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls import shapes as shape_data
from msl_tools.msl.tools.maya.controls.editor import ShapeEditor, axis_step_button
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField, HierarchyStrip, Swatches, TurnButton
from msl_tools.msl.tools.maya.rename.buttons import GroupButton
from msl_tools.msl.ui.theme.qss import color_property, make_rounded_popup, repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard


class _SelectedMixin:

    def _selected_tools(self) -> FoldingCard:
        """SELECTED: everything that works on the controls selected in the scene, in TWO rows. Row 1:
        six GROUP buttons (another shape, the other side, zero, drive, show and select,
        make) and save; a group shows the action used last, a click repeats it, its corner / a right
        click / holding it opens the group. Row 2: the "steps" button (the numbers) and the tools of
        the shape itself — edit the CVs, turn, smaller / bigger / fit, the six steps along the axes."""
        icons = UiResources().iconManager
        card = self._selected_card = FoldingCard("SELECTED", icons.get_icon("select_all", sub_folder="actions"))

        self._tool_icons = {}

        def tool(icon, tone, text, tooltip, menu=False):
            button = self._tool_button(icon, text, tooltip)
            button.setProperty("tone", tone)
            self._tool_icons[button] = icon
            if menu:
                button.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            return button

        # the shape itself (orange)
        self._turns = {}
        for axis in shape_data.AXES:
            self._turns[axis] = TurnButton(axis, f"Turn about {axis}\nThe selected controls' shapes about their "
                                                 f"own {axis}, by the angle under the steps button (Shift: the other way)")
            self._turns[axis].setObjectName("controlsTool")
        self._shrink = tool("shrink", "orange", "Smaller", "The selected controls' shapes smaller: divided by "
                                                           "the factor under the steps button")
        self._grow = tool("grow", "orange", "Bigger", "The selected controls' shapes bigger: times the factor "
                                                      "under the steps button")
        self._cvs = tool("cvs", "orange", "Edit the shape", "The selected controls' CVs get selected: move, turn "
                         "and scale the SHAPE with Maya's own tools, the control's channels stay as they are · "
                         "again: back to the controls")
        # another shape (blue)
        self._replace = tool("replace", "blue", "Replace", "The selected controls get the picked shape — as big as "
                                                           "theirs, same color and line width")
        self._add_shape = tool("add", "blue", "Add the picked shape", "The picked shape BESIDE what the selected "
                                                                      "controls have")
        self._copy_shape = tool("copy", "blue", "Copy the shape", "Keep the selected control's shape to paste onto "
                                                                  "others")
        self._paste_shape = tool("paste", "blue", "Paste the shape", "The selected controls get the copied shape as "
                                 "it is — same size, same place about the pivot; each keeps its own color")
        self._combine = tool("merge", "blue", "Combine", "The selected curves become ONE control, the last "
                                                         "selected — staying where they are, colors kept")
        self._strip_shape = tool("shape_off", "blue", "Take the curve off", "The selected objects lose their curve — "
                                 "a joint that was made a control (the bone on the preview) is a plain joint "
                                 "again, drawn as a bone")
        # the other side (teal)
        self._mirror = tool("mirror_shape", "teal", "Mirror", "A mirrored copy of each selected control on the "
                            "other side (lf_ ↔ rt_, _L ↔ _R; a name without a side gets one: arm_ctrl → rt_arm_ctrl): its zero groups too, under the other side's parent; "
                            "when that control is there already, its shape is made the mirror of this one\n"
                            "Right click: across Y / Z, or flip in place", menu=True)
        self._mirror_update = tool("mirror_update", "teal", "Shape to the other side", "Only the SHAPE: the other "
                                   "side's control (it is there already) gets the mirror of the selected one's "
                                   "shape — fix one side, carry it over; its color, place and groups stay. Either "
                                   "way, by what is selected\nRight click: across Y / Z", menu=True)
        # zero (violet)
        self._zero_groups_button = tool("zero_out", "violet", "Zero with groups", "Groups above each selected "
                                        "control where it stands (the suffixes of the Zero row below), its "
                                        "translate / rotate read 0")
        self._zero_matrix_button = tool("zero_matrix", "violet", "Zero into the matrix", "What the selected "
                                        "controls' channels say moves into their offsetParentMatrix: they read 0, "
                                        "no group")
        self._matrix_back_button = tool("matrix_out", "violet", "Out of the matrix", "The other way: what the "
                                        "offsetParentMatrix holds back into the channels, the matrix empty")
        # drive: tie a control that exists to its object, or let go (pink)
        self._drive_constraint = tool("drive_constraint", "pink", "Drive with constraints", "The object follows "
                                      "its control through parent + scale constraints, staying where it is\n"
                                      "Select CONTROLS — each finds its object by its name (lf_arm_ctrl → "
                                      "lf_arm_jnt) — or a control and its object(s): pairs by the order picked, "
                                      "or one control for all")
        self._drive_matrix = tool("drive_matrix", "pink", "Drive with the matrix", "The object follows its control "
                                  "through its offsetParentMatrix: no constraint node, its channels read zero\n"
                                  "Select controls (objects found by name), or a control and its object(s)")
        self._drive_off = tool("drive_off", "pink", "Let go", "Untie, from either end: a selected OBJECT is freed "
                               "of the control that drives it; a selected CONTROL lets go of what it drives. "
                               "The objects stay where they stand")
        # show and select (yellow)
        self._on_top_button = tool("on_top", "yellow", "Always on top", "The selected controls' curves drawn "
                                                                        "through the geometry — on / off")
        self._select_below = tool("branch", "yellow", "Controls under the selection", "Select every control "
                                                                                      "(curve) under what is selected")
        self._select_all = tool("select_all", "yellow", "Controls in the scene", "Select every control (curve) in "
                                                                               "the scene")
        self._select_same = tool("same_shape", "yellow", "Controls of the same shape", "Select every control in "
                                 "the scene whose shape is the same as the selected one's (whatever its size and "
                                 "color) — then Replace, color or resize them all at once\nRight click: only "
                                 "under the selection", menu=True)
        self._fit_button = tool("frame_fit", "orange", "Fit to its object", "The selected controls' shapes as big "
                                "as “fit” makes a new one, across the axis the shape faces. Only the shape "
                                "is scaled\nTo what: select the control AND the object (one object for several "
                                "controls, or as many objects as controls) — or only controls: each is fitted "
                                "to the object it drives, else the one its name says")
        # helpers of the rigging itself (plain)
        self._locators = tool("locator", "", "Locators on the selection", "A locator on each selected object — "
                              "at its pivot, turned like it — and on each selected vertex, CV, edge or face (its "
                              "middle)\nRight click: along the surface's normal · ONE locator in the "
                              "middle of everything selected (the center of an edge loop)", menu=True)
        self._joints = tool("joint_chain", "", "Joints on the selection", "A chain of joints through what is "
                            "selected, in the order picked — locators set out for a skeleton, or vertices: "
                            "each joint under the one before, its X down the bone, named after what it stands "
                            "on (lf_arm_loc → lf_arm_jnt)\nRight click: separate joints, not a chain", menu=True)
        # into the library (green)
        self._capture = tool("bookmark_add", "green", "Save as a shape", "Save the selected curves as a shape of "
                                                                         "yours (it goes under Mine)")

        # ---- row 1: the actions, in groups (each member button lives on, unseen: its click is the action)
        groups = (("shape", "blue", "Another shape",
                   (("replace", self._replace, "replace", None), ("add", self._add_shape, "add", None),
                    ("copy", self._copy_shape, "", None), ("paste", self._paste_shape, "paste", None),
                    ("combine", self._combine, "", None), ("strip", self._strip_shape, "", None))),
                  ("side", "teal", "The other side",
                   (("mirror", self._mirror, "mirror", "_mirror_menu"),
                    ("mirror_update", self._mirror_update, "mirror_update", "_mirror_update_menu"))),
                  ("zero", "violet", "Zero",
                   (("zero_groups", self._zero_groups_button, "zero_groups", None),
                    ("zero_matrix", self._zero_matrix_button, "zero_matrix", None),
                    ("matrix_back", self._matrix_back_button, "matrix_back", None))),
                  ("drive", "pink", "Drive",
                   (("constraint", self._drive_constraint, "", None), ("matrix", self._drive_matrix, "", None),
                    ("off", self._drive_off, "", None))),
                  ("select", "yellow", "Show and select",
                   (("below", self._select_below, "", None), ("all", self._select_all, "", None),
                    ("same", self._select_same, "", "_same_shape_menu"), ("on_top", self._on_top_button, "", None))),
                  ("make", "", "Make on the selection",
                   (("locators", self._locators, "", "_locators_menu"), ("joints", self._joints, "", "_joints_menu"))))
        self._groups = {}
        line = qt.QtWidgets.QHBoxLayout()
        line.setSpacing(3)
        for key, tone, title, members in groups:
            face = GroupButton(tone, icon_size=16)
            face.setObjectName("controlsTool")
            face.setFixedSize(32, 22)
            for _member, button, _hover, _menu_name in members:
                button.setParent(card)
                button.hide()
            self._groups[key] = {"face": face, "title": title, "members": members}
            face.run_requested.connect(lambda key=key: self._run_group(key))
            face.menu_requested.connect(lambda key=key: self._open_group(key))
            face.hovered.connect(lambda on, key=key: self._on_group_hover(key, on))
            line.addWidget(face)
        line.addSpacing(2)
        line.addWidget(self._rule())
        line.addSpacing(2)
        line.addWidget(self._capture)
        line.addStretch(1)
        card.body_layout.addLayout(line)

        # ---- the numbers: how far a step goes, how much a turn turns, how much "bigger" grows, the line
        self._shape_step = DragNumberField(0.1, 0.001, 1000.0, 0.05, width=56, decimals=3)
        self._shape_step.setToolTip("The step of the six −X … +Z buttons — drag with the middle mouse button, the wheel")
        self._shape_angle = DragNumberField(90.0, 1.0, 180.0, 5.0, width=56, decimals=1)
        self._shape_angle.setToolTip("The angle, in degrees, the turn buttons X / Y / Z turn the shape by "
                                     "(Shift + click: the other way)")
        self._shape_factor = DragNumberField(1.25, 1.01, 10.0, 0.05, width=56, decimals=2)
        self._shape_factor.setToolTip("The factor Smaller / Bigger change the shape by")
        self._shifts = {}
        for index, axis in enumerate(shape_data.AXES):
            for sign, mark in ((-1, "−"), (1, "+")):
                self._shifts[(index, sign)] = axis_step_button(
                    axis, mark, f"The selected controls' shapes one step along their own {mark}{axis}: off the "
                                "pivot, the control itself stays (Shift: five steps) — the step is under the "
                                "steps button")
        # the curves' line width: a thing of the shape, so it stands here (it was in the COLOR card)
        self._line = DragNumberField(1.0, -1.0, 20.0, 0.5, width=56, decimals=1)
        self._line.setToolTip("Line width\nHow thick the selected controls' curves are drawn (-1 = Maya's "
                              "preference) — drag with the middle mouse button, the wheel, Up / Down. It shows "
                              "the first selected control's")
        self._steps_button = tool("sliders", "orange", "Steps", "")
        holder = qt.QtWidgets.QWidget()
        form = qt.QtWidgets.QGridLayout(holder)
        form.setContentsMargins(10, 6, 10, 6)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        for row, (caption, field, unit) in enumerate((("Move step", self._shape_step, "the −X … +Z buttons"),
                                                      ("Turn angle", self._shape_angle, "degrees, the X Y Z buttons"),
                                                      ("Scale factor", self._shape_factor, "Smaller / Bigger"),
                                                      ("Line width", self._line, "of the selected curves"))):
            form.addWidget(self._caption(caption), row, 0)
            form.addWidget(field, row, 1)
            form.addWidget(self._caption(unit), row, 2)
        self._steps_menu = self._menu()          # kept: it owns the four fields
        action = qt.QtWidgets.QWidgetAction(self._steps_menu)
        action.setDefaultWidget(holder)
        self._steps_menu.addAction(action)
        self._steps_button.clicked.connect(lambda: self._steps_menu.exec(
            self._steps_button.mapToGlobal(qt.QtCore.QPoint(0, self._steps_button.height()))))
        for field in (self._shape_step, self._shape_angle, self._shape_factor, self._line):
            field.value_changed.connect(self._show_steps)

        # ---- row 2: the steps button, then the buttons that use its numbers (tight: this row is the
        # card's widest, and the window's minimum width must stay under its default)
        steps = qt.QtWidgets.QHBoxLayout()
        steps.setSpacing(2)
        steps.addWidget(self._steps_button)
        steps.addWidget(self._cvs)               # editing the points belongs with the shape's own tools
        steps.addWidget(self._rule())
        for axis in shape_data.AXES:
            steps.addWidget(self._turns[axis])
        steps.addWidget(self._rule())
        for button in (self._shrink, self._grow, self._fit_button):
            steps.addWidget(button)
        steps.addWidget(self._rule())
        for button in self._shifts.values():
            steps.addWidget(button)
        steps.addStretch(1)
        card.body_layout.addLayout(steps)
        self._show_steps()
        self._show_groups()
        return card

    @staticmethod
    def _rule() -> "qt.QtWidgets.QFrame":
        rule = qt.QtWidgets.QFrame()
        rule.setObjectName("controlsRule")
        rule.setFixedSize(1, 16)
        return rule

    def _show_steps(self, *_args) -> None:
        """The steps button says its numbers (they are out of sight until it is clicked)."""
        self._steps_button.setToolTip(
            f"Steps\nMove {self._shape_step.value():g} · Turn {self._shape_angle.value():g}° · "
            f"Scale ×{self._shape_factor.value():g} · Line {self._line.value():g}\nClick: change them — how far "
            "the −X … +Z buttons move the shape, the angle of the turn buttons, the factor of Smaller / Bigger, "
            "the selected curves' line width")

    # ------------------------------------------------------------------ groups of actions

    def _group_last(self, key: str):
        """(member key, button, hover key, menu builder's name) of the group's action used last."""
        members = self._groups[key]["members"]
        last = dict(self._settings.get("tool_last") or {}).get(key, "")
        return next((member for member in members if member[0] == last), members[0])

    def _show_groups(self) -> None:
        """Each group button shows the action used last: its icon, its tooltip — and is lit while
        any of the group's actions is already true of the selection."""
        icons = UiResources().iconManager
        for key, group in self._groups.items():
            face = group["face"]
            member, button, _hover, _menu_name = self._group_last(key)
            if face.property("member") != member:
                face.setProperty("member", member)
                face.set_source_icon(icons.get_icon(self._tool_icons.get(button, ""), sub_folder="actions"))
            lit = any(bool(each[1].property("on")) for each in group["members"])
            if bool(face.property("on")) != lit:
                face.setProperty("on", lit)
                repolish(face)
            face.setToolTip(f"{button.toolTip()}\n\n{group['title']}: the corner, a right click or holding the "
                            "button opens the rest of the group")

    def _run_group(self, key: str, member: str = "") -> None:
        """The group's action: the one named (it becomes the group's button), else the one used last."""
        members = self._groups[key]["members"]
        picked = next((each for each in members if each[0] == member), None) or self._group_last(key)
        if member and dict(self._settings.get("tool_last") or {}).get(key) != member:
            last = dict(self._settings.get("tool_last") or {})
            last[key] = member
            self._settings["tool_last"] = last
            self._show_groups()
        picked[1].click()

    def _group_menu(self, key: str) -> "qt.QtWidgets.QMenu":
        group = self._groups[key]
        last = self._group_last(key)[0]
        menu = self._menu()
        self._menu_caption(menu, group["title"])
        for member, button, hover, menu_name in group["members"]:
            button.ensurePolished()          # an unseen button still takes its color from the stylesheet
            name, _line, tip = button.toolTip().partition("\n")
            action = self._menu_item(menu, self._tool_icons.get(button, ""), name + (" ●" if button.property("on") else ""),
                                     lambda key=key, member=member: self._run_group(key, member), tip,
                                     color=button.iconColor, hint="last" if member == last else "")
            if hover:
                action.hovered.connect(lambda hover=hover: self._on_action_hover(hover, True))
            if menu_name:
                more = getattr(self, menu_name)()
                more.setTitle(f"{name} — more")
                menu.addMenu(more)
        menu.aboutToHide.connect(lambda: self._on_group_hover(key, False))
        return menu

    def _open_group(self, key: str) -> None:
        face = self._groups[key]["face"]
        self._group_menu(key).exec(face.mapToGlobal(qt.QtCore.QPoint(0, face.height())))

    def _on_group_hover(self, key: str, on: bool) -> None:
        hover = self._group_last(key)[2]
        if on and hover:
            self._on_action_hover(hover, True)
        elif not on and self._hovered_action:
            self._hovered_action = ""
            self._refresh_live()

    _hovered_action = ""

    def _watch_hover(self, button, key: str) -> None:
        button.hovered.connect(lambda on, key=key: self._on_action_hover(key, on))
        button.clicked.connect(self._after_action_click)

    def _on_action_hover(self, key: str, on: bool) -> None:
        if on or self._hovered_action == key:
            self._hovered_action = key if on else ""
            self._refresh_live()

    def _after_action_click(self, *_args) -> None:
        # the click changed the control: show the next click's effect once Maya has done its part
        qt.QtCore.QTimer.singleShot(0, self._refresh_live)

    def _show_action(self) -> None:
        key = self._hovered_action
        try:
            from msl_tools.msl.tools.maya.controls import scene
            holders = scene.selected_transforms() if key.startswith(("zero", "matrix")) else \
                scene.controls_in_selection()
            before = scene.read_curves(holders[0]) if holders else []
            rgb = scene.read_color(holders[0])[0] if holders else None
        except (ImportError, RuntimeError, ValueError):
            holders, before, rgb = [], [], None
        if not holders:
            self._draw_live()
            return
        reach = max([abs(value) for curve in before for point in curve.points for value in point] or [1.0]) or 1.0
        picked = shape_data.scaled(shape_data.oriented(self._picked_shape().curves, self._view.axis()), reach)
        back = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
        after, zero, text = before, None, ""
        if key.startswith("turn_"):
            angle = self._shape_angle.value()
            after = shape_data.turned(before, key[-1], -angle if back else angle)
            text = f"turn {'−' if back else ''}{angle:g}° about {key[-1]}"
        elif key.startswith("shift_"):
            axis, sign = int(key[6]), (1 if key.endswith("+") else -1)
            step = sign * self._shape_step.value() * (5 if back else 1)
            after = [shape_data.Curve([tuple(value + (step if index == axis else 0.0) for index, value in enumerate(point))
                                       for point in curve.points], curve.degree, curve.closed) for curve in before]
            text = f"{step:+g} along {shape_data.AXES[axis]}"
        elif key in ("shrink", "grow"):
            factor = self._shape_factor.value() if key == "grow" else 1.0 / self._shape_factor.value()
            after = shape_data.scaled(before, factor)
            text = f"×{factor:.3g}"
        elif key == "replace":
            after, text = picked, "gets " + self._picked_shape().title().lower()
        elif key == "add":
            after, text = before + picked, "plus " + self._picked_shape().title().lower()
        elif key == "paste" and _SelectedMixin._copied_shape:
            after, text = list(_SelectedMixin._copied_shape), "gets the copied shape"
        elif key in ("mirror", "mirror_update"):
            after = [shape_data.Curve([(-x, y, z) for x, y, z in curve.points], curve.degree, curve.closed)
                     for curve in before]
            text = "as the other side gets it"
        elif key == "zero_groups":
            names = self._offset_suffixes()
            zero, text = ("groups", len(names)), " › ".join(names) + " › above it"
        elif key == "zero_matrix":
            zero, text = ("matrix", 1), "zeroed in its matrix"
        elif key == "matrix_back":
            text = "back in its channels"
        else:
            self._draw_live()
            return
        if not before and zero is None:
            self._draw_live()
            return
        name = holders[0].rpartition("|")[2] + (f"  +{len(holders) - 1}" if len(holders) > 1 else "")
        self._view.set_notes([])
        self._view.set_title(name, text)
        self._view.set_action(before, after, self._color_for(rgb) if rgb is not None else None, zero)

    def _refresh_states(self, selected: "list | None" = None) -> None:
        """The SELECTED buttons show what is ALREADY true of the selection: tied by constraints / the
        matrix, zeroed with groups / in the matrix, drawn on top — the button of it is lit (`on`)."""
        found = {}
        try:
            from msl_tools.msl.tools.maya.controls import scene
            found = scene.states(scene.selected_transforms() if selected is None else selected)
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't read what the selection is tied to", error)
        total = 0 if selected is None else len(selected)
        for key, button, what in (("constraint", self._drive_constraint, "tied by constraints"),
                                  ("matrix", self._drive_matrix, "tied through the matrix"),
                                  ("zero_groups", self._zero_groups_button, "zeroed with groups"),
                                  ("zero_matrix", self._zero_matrix_button, "zeroed in the matrix"),
                                  ("on_top", self._on_top_button, "drawn on top"),
                                  ("mirror_link", self._mirror_update, "in a live mirror link (right click: Unlink)")):
            count = int(found.get(key, 0))
            if bool(button.property("on")) != bool(count):
                button.setProperty("on", bool(count))
                repolish(button)
            base = button.toolTip().split("\n● ")[0]
            button.setToolTip(base + (f"\n● {count} of the selected {'is' if count == 1 else 'are'} {what}"
                                      if count else ""))
        tied = bool(found.get("constraint") or found.get("matrix"))
        if bool(self._drive_off.property("on")) != tied:
            self._drive_off.setProperty("on", tied)
            repolish(self._drive_off)
        self._show_groups()

    def _selected_controls(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        controls = scene.controls_in_selection()
        if not controls:
            self._say("Select controls (curves) first", "error")
        return controls

    def _turn(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            back = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
            angle = self._shape_angle.value()
            scene.turn(controls, axis, -angle if back else angle)
            self._say(f"Turned {len(controls)} {'−' if back else ''}{angle:g}° about {axis}", "done")

    def _shift_shape(self, axis: int, sign: int) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shift = bool(qt.QtWidgets.QApplication.keyboardModifiers() & qt.QtCore.Qt.KeyboardModifier.ShiftModifier)
            offset = [0.0, 0.0, 0.0]
            offset[axis] = sign * self._shape_step.value() * (5 if shift else 1)
            scene.shift(controls, offset)
            self._say(f"The shape of {len(controls)} moved {offset[axis]:+g} along {shape_data.AXES[axis]} · "
                      "Ctrl+Z undoes it", "done")

    def _resize(self, factor: float) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            scene.resize(controls, factor)
            self._say(f"{'Bigger' if factor > 1 else 'Smaller'}: {len(controls)}", "done")

    def _on_replace(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shape = self._picked_shape()
            if self._taken and self._edited is not None:
                # a shape TAKEN from the scene goes back as it is: same size, same place about the pivot
                # (Replace would size a library shape to the control — this one has its own size)
                count = scene.set_curves(controls, shape_data.oriented(shape.curves, self._view.axis()))
                self._say(f"{count} got the edited shape back, exactly · Ctrl+Z undoes it", "done")
                return
            count = scene.replace(controls, shape, self._view.axis())
            self._say(f"{count} got the shape “{shape.title()}” · Ctrl+Z undoes it", "done")

    _copied_shape: list = []     # the copied curves, kept by the CLASS: they outlive a closed window

    def _on_cvs(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        state = scene.toggle_cvs()
        if state == "cvs":
            self._say("The shapes' CVs are selected: move, turn, scale them — click again for the controls", "done")
        elif state == "objects":
            self._say("Back to the controls", "")
        else:
            self._say("Select controls (curves) first", "error")

    def _on_copy_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            _SelectedMixin._copied_shape = scene.read_curves(controls[0])
            self._say(f"Copied the shape of {controls[0].rpartition('|')[2]} — select controls and paste", "done")

    def _on_paste_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        if not _SelectedMixin._copied_shape:
            self._say("Nothing copied yet: select a control and copy its shape", "error")
            return
        controls = self._selected_controls()
        if controls:
            scene.set_curves(controls, _SelectedMixin._copied_shape)
            self._say(f"Pasted the shape onto {len(controls)} · Ctrl+Z undoes it", "done")

    def _on_add_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            shape = self._picked_shape()
            scene.add_shape(controls, shape, self._view.axis())
            self._say(f"Added “{shape.title()}” to {len(controls)} · Ctrl+Z undoes it", "done")

    def _on_strip_shape(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            stripped = scene.strip_shapes(controls)
            self._say(f"The curve is off {len(stripped)}: " + ", ".join(stripped[:3]) + ("…" if len(stripped) > 3 else "")
                      + " · Ctrl+Z undoes it", "done")
            self._refresh_live()        # they are no controls any more: the preview, the line, the eye

    def _on_combine(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        if len(controls) < 2:
            self._say("Select two or more curves: they become one control, the LAST selected", "error")
            return
        keeper = scene.combine(controls)
        self._say(f"{len(controls)} curves are one control now: {keeper.rpartition('|')[2]} · Ctrl+Z undoes it", "done")

    def _on_top(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            state = scene.toggle_on_top(controls)
            if state is None:
                self._say("This Maya's curves have no “always on top”", "error")
            else:
                self._say(f"{len(controls)} drawn {'over everything' if state else 'as usual again'}", "done")

    def _same_shape_menu(self) -> "qt.QtWidgets.QMenu":
        tone = self._select_same.iconColor
        menu = self._menu()
        self._menu_caption(menu, "Controls of the same shape as the selected")
        self._menu_item(menu, "same_shape", "In the scene", lambda: self._select_same_shape(False), "", tone,
                        hint="click")
        self._menu_item(menu, "branch", "Only under the selection", lambda: self._select_same_shape(True),
                        "Among what is under the selected objects", tone)
        return menu

    def _select_same_shape(self, below: bool) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from maya import cmds
        controls = self._selected_controls()
        if not controls:
            return
        found = scene.same_shape(controls, scene.selected_transforms() if below else None)
        cmds.select(found or controls, replace=True)
        extra = len(found) - len([control for control in controls if control in found])
        self._say(f"{len(found)} control{'s' if len(found) != 1 else ''} of that shape selected" +
                  (f" — {extra} more than you had" if extra > 0 else " — no others like it"), "done" if extra > 0 else "")

    def _fit_selected(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        # objects selected WITH the controls are what to fit to — the names needn't say anything
        objects = [node for node in scene.selected_transforms() if not scene.curve_shapes(node)]
        if objects and len(objects) not in (1, len(controls)):
            self._say(f"{len(controls)} controls and {len(objects)} objects: select ONE object for all the "
                      "controls, or as many objects as controls (in the same order)", "error")
            return
        fitted, alone = scene.fit_controls(controls, objects)
        if not fitted:
            self._say("No object to fit to: " + ", ".join(alone[:3]) + " — select the control AND the object, "
                      "or a control that drives one / is named after one", "error")
            return
        if objects:
            self._say(f"{fitted} fitted to " + (objects[0].rpartition("|")[2] if len(objects) == 1 else
                                                 f"the {len(objects)} selected objects") + " · Ctrl+Z undoes it", "done")
            return
        self._say(f"{fitted} fitted to {'its object' if fitted == 1 else 'their objects'}" +
                  (f" · {len(alone)} with no object: " + ", ".join(alone[:2]) if alone else "") +
                  " · Ctrl+Z undoes it", "done")

    def _link_mirror(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        linked, missing = scene.link_mirror(controls, self._sides(), axis)
        if not linked:
            self._say("Nothing linked — the other side's control isn't there (Mirror makes one), or this one "
                      "follows already", "error")
            return
        self._say(f"{linked} other-side shape{'s' if linked != 1 else ''} now FOLLOW{'S' if linked == 1 else ''} "
                  "— change this shape and the other side is its mirror" +
                  (f" · {len(missing)} not linked: " + ", ".join(missing[:2]) if missing else ""), "done")

    def _unlink_mirror(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            freed = scene.unlink_mirror(controls)
            self._say(f"{freed} mirror link{'s' if freed != 1 else ''} taken away — the shapes stay as they are"
                      if freed else "No mirror link on the selection", "done" if freed else "")

    def _select_controls(self, below: bool) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from maya import cmds
        roots = scene.selected_transforms() if below else None
        if below and not roots:
            self._say("Select what to look under first", "error")
            return
        found = scene.all_controls(roots)
        if not found:
            self._say("No controls (curves) there", "")
            return
        cmds.select(found, replace=True)
        self._say(f"Selected {len(found)} control{'s' if len(found) != 1 else ''}", "done")

    def _mirror_to_other(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        made, updated, alone = scene.mirror_controls(controls, self._sides(), axis, self._side_color.isChecked())
        if not made and not updated:
            self._say("Nothing to mirror: the names say no side (lf_ / rt_, _L / _R…)", "error")
            return
        parts = []
        if made:
            parts.append(f"Mirrored {len(made)}: " + ", ".join(path.rpartition("|")[2] for path in made[:2]) +
                         ("…" if len(made) > 2 else ""))
        if updated:
            parts.append(f"{updated} other-side shape{'s' if updated != 1 else ''} updated")
        if alone:
            parts.append(f"{len(alone)} say no side")
        self._say(" · ".join(parts) + " · Ctrl+Z undoes it", "done")

    def _mirror_shapes(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        updated, missing = scene.mirror_shapes_to_twins(controls, self._sides(), axis)
        if not updated:
            self._say("No other side to carry the shape to — Mirror makes one", "error")
            return
        text = f"{updated} shape{'s' if updated != 1 else ''} carried to the other side (across {axis})"
        if missing:
            text += f" · {len(missing)} without one: " + ", ".join(missing[:2])
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _mirror_update_menu(self) -> "qt.QtWidgets.QMenu":
        tone = self._mirror_update.iconColor
        menu = self._menu()
        self._menu_caption(menu, "Only the shape, to the control on the other side")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_update", f"Across {axis}", lambda axis=axis: self._mirror_shapes(axis),
                            f"The mirror plane stands across the world's {axis}", tone, hint="click" if axis == "X" else "")
        menu.addSeparator()
        self._menu_caption(menu, "Keep the other side following (live)")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_update", f"Link across {axis}", lambda axis=axis: self._link_mirror(axis),
                            "From now on the other side's shape IS the mirror of this one: edit its CVs, replace "
                            "it, resize it — the other side follows at once. Posing the controls changes nothing",
                            tone)
        self._menu_item(menu, "drive_off", "Unlink", self._unlink_mirror,
                        "From either end; the shapes stay as they are", tone)
        return menu

    def _on_mirror_update_menu(self, position) -> None:
        self._mirror_update_menu().exec(self._mirror_update.mapToGlobal(position))

    def _mirror_menu(self) -> "qt.QtWidgets.QMenu":
        tone = self._mirror.iconColor
        menu = self._menu()
        self._menu_caption(menu, "A mirrored copy on the other side")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_shape", f"Across {axis}", lambda axis=axis: self._mirror_to_other(axis),
                            f"The mirror plane stands across the world's {axis}: the copy, its zero groups, its name",
                            tone, hint="click" if axis == "X" else "")
        menu.addSeparator()
        self._menu_caption(menu, "Flip this shape, where it is")
        for axis in shape_data.AXES:
            self._menu_item(menu, "mirror_sides", f"Along its own {axis}", lambda axis=axis: self._flip(axis),
                            "No copy: the shape is turned inside out along that axis of the control", tone)
        return menu

    def _on_mirror_menu(self, position) -> None:
        self._mirror_menu().exec(self._mirror.mapToGlobal(position))

    def _flip(self, axis: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if controls:
            scene.flip(controls, axis)
            self._say(f"Flipped {len(controls)} across their own {axis} · Ctrl+Z undoes it", "done")

    def _zero_targets(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the controls to zero first", "error")
        return targets

    def _zero_groups(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            names = self._offset_suffixes()
            scene.zero_with_groups(targets, names)
            self._say(f"Zeroed {len(targets)} with {', '.join(names)} above · Ctrl+Z undoes it", "done")

    def _zero_matrix(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            scene.zero_with_matrix(targets)
            self._say(f"Zeroed {len(targets)} through the offsetParentMatrix · Ctrl+Z undoes it", "done")

    def _matrix_back(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._zero_targets()
        if targets:
            held = [target for target in targets if scene.has_offset_matrix(target)]
            if not held:
                self._say("Their offsetParentMatrix holds nothing", "")
                return
            scene.matrix_to_channels(held)
            self._say(f"{len(held)} back in the channels, the offsetParentMatrix empty · Ctrl+Z undoes it", "done")

    def _drive_selected(self, mode: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        pairs, problems = scene.pair_up(scene.selected_transforms())
        if not pairs:
            self._say("Nothing to tie — " + (problems[0] if problems else "select controls"), "error")
            return
        notes = []
        done = scene.drive_pairs(pairs, mode, notes)
        how = "constraints" if mode == "constraint" else "the matrix"
        text = f"{done} now follow{'s' if done == 1 else ''} {'its control' if done == 1 else 'their controls'} " \
               f"through {how}"
        for each in (notes + problems)[:1]:
            text += f" · NOT tied — {each}" + (f" (+{len(notes + problems) - 1})" if len(notes + problems) > 1 else "")
        self._say(text + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")

    def _make_locators(self, center: bool, along_normal: bool = False) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        try:
            made, total = scene.locators_on_selection(center=center, along_normal=along_normal,
                                                      axis=self._view.axis())
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        if not made:
            self._say("Select objects, vertices, edges or faces first", "error")
            return
        short = [path.rpartition("|")[2] for path in made]
        if center:
            text = f"One locator in the middle of {total} selected: {short[0]}"
        else:
            text = f"{len(made)} locator{'s' if len(made) != 1 else ''}: " + ", ".join(short[:3]) + \
                ("…" if len(short) > 3 else "")
            if total > len(made):
                text += f" · the first {len(made)} of {total} (right click: one in the middle)"
        if along_normal:
            text += f" · {self._view.axis()} along the normal"
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _locators_menu(self) -> "qt.QtWidgets.QMenu":
        axis = self._view.axis()
        menu = self._menu()
        self._menu_caption(menu, "A locator on each selected thing")
        self._menu_item(menu, "locator", "On each", lambda: self._make_locators(False),
                        "An object: at its pivot, turned like it · a vertex, edge, face: where it is", hint="click")
        self._menu_item(menu, "locator", f"On each, {axis} along the normal", lambda: self._make_locators(False, True),
                        "Vertices, edges, faces of a mesh: the locator faces away from the surface "
                        "(the axis is the preview's)")
        menu.addSeparator()
        self._menu_caption(menu, "One locator for all of it")
        self._menu_item(menu, "center", "In the middle", lambda: self._make_locators(True),
                        "The center of an edge loop, of several objects")
        self._menu_item(menu, "center", f"In the middle, {axis} across the loop", lambda: self._make_locators(True, True),
                        "Turned along the limb the loop goes around")
        return menu

    def _on_locators_menu(self, position) -> None:
        self._locators_menu().exec(self._locators.mapToGlobal(position))

    def _make_joints(self, chain: bool) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        try:
            made, total = scene.joints_on_selection(chain=chain)
        except RuntimeError as error:
            self._say(f"Maya refused: {error}".strip(), "error")
            return
        if not made:
            self._say("Select locators (or other objects, vertices) in the order of the chain first", "error")
            return
        short = [path.rpartition("|")[2] for path in made]
        text = (f"A chain of {len(made)} joints: " if chain and len(made) > 1 else
                f"{len(made)} joint{'s' if len(made) != 1 else ''}: ") + ", ".join(short[:3]) + \
            ("…" if len(short) > 3 else "")
        if total > len(made):
            text += f" · the first {len(made)} of {total}"
        self._say(text + " · Ctrl+Z undoes it", "done")

    def _joints_menu(self) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        self._menu_caption(menu, "Joints where the selection is")
        self._menu_item(menu, "joint_chain", "A chain, in the order picked", lambda: self._make_joints(True),
                        "Each joint under the one before, X down the bone", hint="click")
        self._menu_item(menu, "joints_separate", "Separate joints", lambda: self._make_joints(False),
                        "Not connected, each turned like its object")
        return menu

    def _on_joints_menu(self, position) -> None:
        self._joints_menu().exec(self._joints.mapToGlobal(position))

    def _undrive_selected(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        selected = scene.selected_transforms()
        if not selected:
            self._say("Select the object to free, or the control that should let go", "error")
            return
        freed = scene.undrive(selected)
        if not freed:
            self._say("Nothing selected is tied to a control", "")
            return
        self._say(f"Let go of {len(freed)}: " + ", ".join(freed[:3]) + ("…" if len(freed) > 3 else "") +
                  " · Ctrl+Z undoes it", "done")

    def _on_capture(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        controls = self._selected_controls()
        if not controls:
            return
        curves = [curve for control in controls for curve in scene.read_curves(control)]
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        title = menu.addAction(f"Save {len(curves)} curve{'s' if len(curves) != 1 else ''} as a shape — its name:")
        title.setEnabled(False)
        _field_action(menu, controls[0].rpartition("|")[2], "Shape name", lambda name: self._save_shape(name, curves))
        menu.exec(self._capture.mapToGlobal(qt.QtCore.QPoint(0, self._capture.height())))
