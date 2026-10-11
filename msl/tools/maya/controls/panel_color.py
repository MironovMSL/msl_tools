# tools/maya/controls/panel_color.py
"""The Controls panel's COLOR card: Maya's index palette, a color of your own (RGB) and the colors
you saved, where the color goes (the viewport and / or the Outliner; the shapes or the transform),
side colors, taking the color from an object, the colors the scene already uses. Every click acts
on what is selected at once; a color under the pointer is tried on first. (The curves' line width is
handled here too, its field stands in the SELECTED card.) Methods of ControlsPanel, kept apart by
concern."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls import colors
from msl_tools.msl.tools.maya.controls.widgets import DragNumberField, PlaceMark, Swatches
from msl_tools.msl.tools.maya.rename.buttons import ToggleIconButton
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.buttons.color_swatch_button import ColorSwatchButton
from msl_tools.msl.ui.widgets.atoms.segmented.segmented_control import SegmentedControl
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

COLOR_TARGETS = ("Shape", "Transform")
SAVED_MAX = 20
TRY_AT_MOST = 150           # a color is tried on (under the pointer) on this many objects at most
SCENE_COLORS = 5            # this many of the scene's colors are shown (the most used)


class _WordToggle(ToggleIconButton):
    """An on / off choice that SAYS what it is: the icon and a word (a ToggleIconButton keeps its
    lit state in the `on` property; the text beside the icon is the only difference)."""

    def __init__(self, icon, word: str, tooltip: str, parent=None):
        super().__init__(icon, word, tooltip, parent)
        self.setObjectName("controlsWordToggle")
        self.setText(word)


class _ColorMixin:

    def _color_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        # WHERE the selected objects wear a color — on the shape, on the transform, in the Outliner:
        # three marks in the heading (seen with the card folded too). Painting a transform over a
        # painted shape, or the other way, was a riddle without them.
        self._place_marks = {"shape": PlaceMark("Shape"), "transform": PlaceMark("Transform"),
                             "outliner": PlaceMark("Outliner")}
        for mark in self._place_marks.values():
            mark.setObjectName("controlsPlaceMark")
        card = self._color = FoldingCard("COLOR", icons.get_icon("brush", sub_folder="actions"),
                                         extras=list(self._place_marks.values()))
        self._places = {"shape": [], "transform": [], "outliner": [], "index": None, "hidden": 0}
        self._palette = Swatches(side=16, gap=2, columns=16)
        self._palette.setObjectName("controlsPalette")
        self._palette_colors = list(colors.INDEX_COLORS)
        self._show_palette()

        # your color, and what gives one: taken from an object, kept, the ones you kept, the scene's
        self._own = ColorSwatchButton(colors.to_hex(colors.SIDE_COLORS["left"]), "Your color — a click picks it "
                                      "and colors the selection with it")
        self._own.setObjectName("controlsOwnColor")
        self._pick = self._tool_button("color_pick", "Take the color", "Take the color of the selected object as "
                                                                       "your color")
        self._save_color = self._tool_button("bookmark_add", "Save the color", "Keep your color among the saved "
                                                                              "ones (a right click on one removes it)")
        self._saved = Swatches(side=16, gap=2, columns=8)
        self._saved.setObjectName("controlsSaved")
        self._by_side = qt.QtWidgets.QPushButton("L / R")
        self._by_side.setObjectName("controlsWordButton")
        self._by_side.setIcon(qt.QtGui.QIcon())
        self._by_side.setToolTip("By side\nEach selected object in its side's color (left, right, middle — by "
                                 "where it stands)\nRight click: see the three colors and change them")
        self._by_side.setContextMenuPolicy(qt.QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        own = qt.QtWidgets.QHBoxLayout()
        own.setSpacing(4)
        own.addWidget(self._own)
        own.addWidget(self._pick)
        own.addWidget(self._save_color)
        self._saved_rule = qt.QtWidgets.QFrame()
        self._saved_rule.setObjectName("controlsRule")
        self._saved_rule.setFixedSize(1, 16)
        own.addSpacing(2)
        own.addWidget(self._saved_rule)
        own.addSpacing(2)
        own.addWidget(self._saved, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)
        own.addStretch(1)
        own.addWidget(self._by_side)

        # the colors this scene's controls already wear: to hit the same ones without matching by eye
        # (at the end of the row below, the SCENE_COLORS most used: a row of their own cost the card
        # the height the new layout had won)
        self._scene_colors = Swatches(side=16, gap=2, columns=SCENE_COLORS)
        self._scene_colors.setObjectName("controlsSceneColors")
        self._scene_caption = self._caption("Scene")
        self._scene_caption.setToolTip("The colors the objects of this scene are drawn in (curves, meshes, "
                                       "joints…), the most used first — a click colors the selection · right "
                                       "click: select the objects of it")
        self._scene_caption.hide()
        self._scene_colors.hide()

        # where a color goes — said in words: two icons alone were a riddle
        self._to_viewport = _WordToggle(icons.get_icon("viewport", sub_folder="actions"), "Viewport",
                                        "The color goes into the viewport: the drawing override — how the object "
                                        "is drawn")
        self._to_outliner = _WordToggle(icons.get_icon("outliner", sub_folder="actions"), "Outliner",
                                        "The color goes into the Outliner: the object's name there (lifted to read "
                                        "like the viewport)")
        self._color_on = SegmentedControl(list(COLOR_TARGETS), "Shape")
        self._color_on.setToolTip("Shape: the override on the curves (the transform stays clean, a joint or a "
                                  "group takes it itself) · Transform: on the object")
        where = qt.QtWidgets.QHBoxLayout()
        where.setSpacing(4)
        where.addWidget(self._to_viewport)
        where.addWidget(self._to_outliner)
        rule = qt.QtWidgets.QFrame()
        rule.setObjectName("controlsRule")
        rule.setFixedSize(1, 16)
        where.addSpacing(2)
        where.addWidget(rule)
        where.addSpacing(2)
        where.addWidget(self._color_on)
        where.addStretch(1)
        where.addWidget(self._scene_caption)
        where.addWidget(self._scene_colors, 0, qt.QtCore.Qt.AlignmentFlag.AlignVCenter)

        card.body_layout.addWidget(self._palette)
        card.body_layout.addLayout(own)
        card.body_layout.addLayout(where)
        # a color tried on while the pointer is over it (see _on_color_hover)
        self._try_state = None
        self._try_timer = qt.QtCore.QTimer(self)
        self._try_timer.setSingleShot(True)
        self._try_timer.setInterval(90)
        self._try_timer.timeout.connect(self._try_hovered)
        self._try_wanted = None
        return card

    def _connect_color(self) -> None:
        self._palette.clicked.connect(self._on_index)
        self._palette.hovered.connect(lambda key: self._on_color_hover("index", key))
        self._palette.menu_requested.connect(lambda key, position: self._color_menu_for("index", key).exec(position))
        self._saved.hovered.connect(lambda key: self._on_color_hover("rgb", key))
        self._scene_colors.hovered.connect(lambda key: self._on_color_hover("rgb", key))
        self._scene_colors.clicked.connect(self._on_saved_color)
        self._scene_colors.menu_requested.connect(lambda key, position: self._color_menu_for("scene", key).exec(position))
        self._own.color_changed.connect(self._on_own_color)
        self._save_color.clicked.connect(self._on_save_color)
        self._saved.clicked.connect(self._on_saved_color)
        self._saved.menu_requested.connect(self._on_saved_menu)
        for toggle in (self._to_viewport, self._to_outliner):
            toggle.toggled.connect(self._save_color_settings)
        self._color_on.current_changed.connect(self._save_color_settings)
        self._by_side.clicked.connect(self._on_by_side)
        for place, mark in self._place_marks.items():
            mark.clicked.connect(lambda _checked=False, place=place: self._on_place_clicked(place))
            mark.customContextMenuRequested.connect(
                lambda position, place=place, mark=mark: self._place_menu(place).exec(mark.mapToGlobal(position)))
        self._by_side.customContextMenuRequested.connect(
            lambda position: self._side_colors_menu().exec(self._by_side.mapToGlobal(position)))
        self._pick.clicked.connect(self._on_pick_color)
        self._line.value_changed.connect(self._on_line_width)
        self._color.toggled.connect(lambda opened: self._save_folded("color", opened))

    # ---- the three marks: where the selection wears a color

    def _show_color_places(self) -> None:
        """The heading's marks say what the selected objects wear NOW, and where; the palette rings
        the index color the shapes are in. (Never while a color is tried on.)"""
        if self._trying:
            return
        places = {"shape": [], "transform": [], "outliner": [], "index": None, "hidden": 0}
        count = 0
        try:
            from msl_tools.msl.tools.maya.controls import scene
            targets = scene.selected_transforms()
            count = len(targets)
            if targets:
                places = scene.color_places(targets)
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't read where the selection is colored", error)
        self._places = places
        words = {"shape": "on the shape", "transform": "on the transform", "outliner": "in the Outliner"}
        for place, mark in self._place_marks.items():
            found = places[place]
            hidden = place == "transform" and bool(places["hidden"])
            mark.set_colors(found, warn=hidden)
            if not count:
                tip = f"Nothing is selected — select an object to see whether it is colored {words[place]}"
            elif not found:
                tip = f"No color {words[place]}"
            else:
                tip = (", ".join(colors.to_hex(rgb) for rgb in found[:4]) + f" {words[place]}" +
                       (f" ({len(found)} different colors in the selection)" if len(found) > 1 else "") +
                       "\nClick: make it your color · right click: take it off here, move it")
            if hidden:
                tip += ("\n⚠ " + (f"{places['hidden']} objects have" if places["hidden"] > 1 else "It has") +
                        " a color on the SHAPE too: in the viewport the shape's is seen, this one is under it")
            mark.setToolTip(tip)
        if count:
            self._palette.set_current(str(places["index"]) if places["index"] else "")

    def _on_place_clicked(self, place: str) -> None:
        found = self._places.get(place) or []
        if found:
            self._take_rgb(found[0])
        else:
            self._say(f"No color there to take ({place})", "")

    def _place_menu(self, place: str) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        found = self._places.get(place) or []
        word = {"shape": "the shape", "transform": "the transform", "outliner": "the Outliner"}[place]
        self._menu_caption(menu, (", ".join(colors.to_hex(rgb) for rgb in found[:3]) + f" on {word}") if found else
                           f"No color on {word}")
        if not found:
            return menu
        rgb = found[0]
        self._menu_item(menu, "color_pick", "Make it your color", lambda: self._take_rgb(rgb), hint="click")
        self._menu_item(menu, "clear", "Take the color off here", lambda: self._clear_place(place),
                        "Only this place: the others keep theirs")
        if place in ("shape", "transform"):
            other = "transform" if place == "shape" else "shape"
            self._menu_item(menu, "arrow_right", f"Move it to the {other}", lambda: self._move_place(place, other),
                            "It looks the same; where it is kept changes")
        self._menu_item(menu, "select_all", "Select everything of this color", lambda: self._select_color(rgb))
        return menu

    def _clear_place(self, place: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if targets:
            count = scene.clear_color_at(targets, place)
            self._say(f"The color taken off {place} on {count} · Ctrl+Z undoes it", "done")
            self._show_color_places()
            self.refresh_scene_colors()

    def _move_place(self, source: str, target: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if targets:
            count = scene.move_color(targets, source, target)
            self._say(f"The color moved from the {source} to the {target} on {count} · Ctrl+Z undoes it" if count else
                      "Nothing moved: an object without shapes keeps its color on itself", "done" if count else "")
            self._show_color_places()

    # ---- the three side colors: seen and changed from the L / R button's menu

    def _side_colors_menu(self) -> "qt.QtWidgets.QMenu":
        menu = self._menu()
        self._menu_caption(menu, "The side colors — a click changes one")
        ratio = self.devicePixelRatioF()
        for side, word in (("left", "Left"), ("center", "Middle"), ("right", "Right")):
            rgb = colors.SIDE_COLORS[side]
            pixmap = qt.QtGui.QPixmap(int(16 * ratio), int(16 * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(qt.QtCore.Qt.GlobalColor.transparent)
            painter = qt.QtGui.QPainter(pixmap)
            painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(qt.QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(qt.QtGui.QColor.fromRgbF(*rgb))
            painter.drawRoundedRect(qt.QtCore.QRectF(1, 1, 14, 14), 3, 3)
            painter.end()
            action = menu.addAction(qt.QtGui.QIcon(pixmap), f"{word}\t{colors.to_hex(rgb)}",
                                    lambda side=side, word=word: self._pick_side_color(side, word))
            action.setToolTip(f"What a control on the {word.lower()} gets: at Create (Side color), by “L / R”, "
                              "in a mirror")
        menu.addSeparator()
        changed = any(colors.SIDE_COLORS[side] != colors.SIDE_DEFAULTS[side] for side in colors.SIDE_DEFAULTS)
        self._menu_item(menu, "restart", "Back to blue · yellow · red", self._reset_side_colors,
                        "Maya's usual three").setEnabled(changed)
        return menu

    def _pick_side_color(self, side: str, word: str) -> None:
        now = qt.QtGui.QColor.fromRgbF(*colors.SIDE_COLORS[side])
        picked = qt.QtWidgets.QColorDialog.getColor(now, self.window(), f"The {word.lower()} side's color")
        if not picked.isValid() or picked == now:
            return
        stored = dict(self._settings.get("side_colors") or {})
        stored[side] = picked.name()
        self._settings["side_colors"] = stored
        colors.set_side_colors(stored)
        self._say(f"{word} is {picked.name()} now — for new controls, “L / R” and mirrors", "done")
        self._refresh_live()

    def _reset_side_colors(self) -> None:
        self._settings["side_colors"] = {}
        colors.set_side_colors(None)
        self._say("The side colors are blue · yellow · red again", "done")
        self._refresh_live()

    def _apply_color_settings(self) -> None:
        s = self._settings
        colors.set_side_colors(dict(s.get("side_colors") or {}))
        self._to_viewport.setChecked(bool(s.get("color_viewport", True)))
        self._to_outliner.setChecked(bool(s.get("color_outliner", False)))
        target = s.get("color_on", "Shape")
        self._color_on.set_current(target if target in COLOR_TARGETS else "Shape", animate=False)
        own = s.get("own_color", "")
        if own:
            self._own.set_color(own)
        self._line.set_value(float(s.get("line_width", 1.0)))
        self._color.set_open(not dict(s.get("folded") or {}).get("color", False))
        self._show_saved()

    def _save_color_settings(self, *_args) -> None:
        if self._loading:
            return
        values = {"color_viewport": self._to_viewport.isChecked(), "color_outliner": self._to_outliner.isChecked(),
                  "color_on": self._color_on.current(), "own_color": self._own.hex(), "line_width": self._line.value()}
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings[key] = value

    # ------------------------------------------------------------------ showing

    def refresh_palette(self) -> None:
        """Maya's index colors as THIS Maya has them (asked when the window shows)."""
        try:
            from msl_tools.msl.tools.maya.controls import scene
            self._palette_colors = scene.index_palette()
        except Exception:   # outside Maya: the default palette
            self._palette_colors = list(colors.INDEX_COLORS)
        self._show_palette()

    def _show_palette(self) -> None:
        self._palette.set_items([(str(index), None if index == 0 else rgb,
                                  "None — Maya's default color" if index == 0 else f"Index {index}")
                                 for index, rgb in enumerate(self._palette_colors)])

    def _saved_colors(self) -> list:
        return [text for text in (self._settings.get("saved_colors") or []) if isinstance(text, str)]

    def _show_saved(self) -> None:
        self._saved.set_items([(text, colors.from_hex(text), f"{text} — a click colors the selection · right "
                                                             f"click: more") for text in self._saved_colors()])
        wanted = bool(self._saved_colors())
        for widget in (self._saved, self._saved_rule):
            if wanted == widget.isHidden():
                widget.setVisible(wanted)

    def refresh_scene_colors(self) -> None:
        """The row of the colors this scene's controls wear (read when the panel is shown or entered,
        and after a color was given)."""
        if self._trying:
            return                  # a color is being tried on: what the scene shows now is not its own
        self._show_color_places()
        used = []
        try:
            from msl_tools.msl.tools.maya.controls import scene
            used = scene.used_colors(SCENE_COLORS)
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't read the scene's colors", error)
        self._scene_colors.set_items([(colors.to_hex(rgb), rgb, f"{colors.to_hex(rgb)} — on {count} "
                                       f"object{'s' if count != 1 else ''} of this scene\nA click colors the "
                                       "selection · right click: select them") for rgb, count in used])
        for widget in (self._scene_caption, self._scene_colors):
            if bool(used) == widget.isHidden():
                widget.setVisible(bool(used))

    # ------------------------------------------------------------------ a color tried on under the pointer

    def _on_color_hover(self, kind: str, key: str) -> None:
        """The pointer is over a color (or left: key ""): the selection wears it for as long — a look
        only, no undo step; the click gives it for real."""
        self._try_wanted = (kind, key) if key else None
        if key:
            self._try_timer.start()         # (sweeping over the palette must not flicker the scene)
        else:
            self._try_timer.stop()
            self._end_try()

    def _try_hovered(self) -> None:
        wanted = self._try_wanted
        if wanted is None:
            return
        try:
            from msl_tools.msl.tools.maya.controls import scene
            if self._try_state is None:
                targets = scene.selected_transforms()
                if not targets or len(targets) > TRY_AT_MOST or not (self._to_viewport.isChecked()
                                                                     or self._to_outliner.isChecked()):
                    return
                # a selected object is drawn in the selection's highlight, and a color tried on it was
                # not seen. The viewports' highlight steps aside for the look — the selection STAYS, so
                # the Channel Box and the Attribute Editor don't flicker. Only a joint colored on itself
                # never shows its color while selected: then the selection itself steps aside.
                self._try_state = scene.color_state(targets)
                self._try_targets = targets
                self._trying = True
                if scene.colored_on_a_joint(targets, self._color_on.current() == "Shape"):
                    self._try_held = scene.selection_aside()
                else:
                    type(self)._try_panels = scene.highlight_aside()
            else:
                targets = self._try_targets
                scene.restore_color_state(self._try_state)
            kind, key = wanted
            if kind == "index":
                scene.try_color(targets, index=int(key), **self._where())
            else:
                scene.try_color(targets, rgb=colors.from_hex(key), **self._where())
        except ImportError:
            pass
        except Exception as error:
            self._report("Couldn't try the color on", error)

    def _end_try(self) -> None:
        """The look is over: the colors are as they were."""
        state, self._try_state = self._try_state, None
        held, self._try_held = getattr(self, "_try_held", None), None
        self._try_wanted = None
        self._try_timer.stop()
        if state is not None:
            try:
                from msl_tools.msl.tools.maya.controls import scene
                scene.restore_color_state(state)
                if held is not None:
                    scene.selection_back(held)       # the selection is what it was
                self._highlight_back()
            except Exception as error:
                self._report("Couldn't put the colors back", error)
            finally:
                self._trying = False

    def _highlight_back(self) -> None:
        """The viewports get their selection highlight back (also one left off by a window that was
        closed in the middle of a look: the panels are kept by the CLASS)."""
        panels, type(self)._try_panels = type(self)._try_panels, []
        if panels:
            try:
                from msl_tools.msl.tools.maya.controls import scene
                scene.highlight_back(panels)
            except Exception as error:
                self._report("Couldn't switch the selection highlight back on", error)

    _try_panels: list = []   # the viewports whose selection highlight is off for a look (class-level)
    _trying = False          # a color is tried on: the selection is aside, nothing must follow it now
    _try_targets = ()
    _try_held = None

    # ------------------------------------------------------------------ every control of a color

    def _select_color(self, rgb) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        from maya import cmds
        if rgb is None:
            self._say("That is “no color”: nothing to select by", "")
            return
        self._end_try()
        found = scene.controls_of_color(rgb)
        if not found:
            self._say(f"Nothing in this scene is drawn in {colors.to_hex(rgb)}", "")
            return
        cmds.select(found, replace=True)
        self._say(f"{len(found)} object{'s' if len(found) != 1 else ''} in {colors.to_hex(rgb)} selected", "done")

    def _color_menu_for(self, kind: str, key: str) -> "qt.QtWidgets.QMenu":
        """The menu of a color square: of the index palette, of the saved ones, of the scene's."""
        menu = self._menu()
        if kind == "index":
            index = int(key)
            rgb = self._palette_colors[index] if 0 < index < len(self._palette_colors) else None
            self._menu_caption(menu, f"Index {index}" if index else "No color")
            self._menu_item(menu, "brush", "Color the selection", lambda: self._on_index(key), hint="click")
        else:
            rgb = colors.from_hex(key)
            self._menu_caption(menu, key)
            self._menu_item(menu, "brush", "Color the selection", lambda: self._on_saved_color(key), hint="click")
        if rgb is not None:
            self._menu_item(menu, "select_all", "Select everything of this color", lambda: self._select_color(rgb),
                            "Every object of the scene drawn in it: curves, meshes, joints…")
            if kind != "saved":
                self._menu_item(menu, "color_pick", "Make it your color", lambda: self._take_rgb(rgb))
        if kind == "saved":
            self._menu_item(menu, "delete", "Remove it from the saved", lambda: self._remove_saved(key))
        return menu

    def _take_rgb(self, rgb) -> None:
        self._own.set_color(colors.to_hex(rgb))
        self._save_color_settings()
        self._say(f"{colors.to_hex(rgb)} is your color now", "done")

    def _remove_saved(self, text: str) -> None:
        self._settings["saved_colors"] = [each for each in self._saved_colors() if each != text]
        self._show_saved()

    # ------------------------------------------------------------------ coloring

    def _where(self) -> dict:
        return {"viewport": self._to_viewport.isChecked(), "outliner": self._to_outliner.isChecked(),
                "on_shape": self._color_on.current() == "Shape"}

    def _targets(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the objects to color first", "error")
        elif not (self._to_viewport.isChecked() or self._to_outliner.isChecked()):
            self._say("Switch on where the color goes: the viewport, the Outliner or both", "error")
            return []
        return targets

    def _on_index(self, key: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        self._end_try()             # the look ends first: one Ctrl+Z goes back to what the color WAS
        targets = self._targets()
        if targets:
            index = int(key)
            if index:
                scene.color(targets, index=index, **self._where())
            else:
                scene.reset_color(targets)      # "none" = no override and no Outliner color at all
            self._palette.set_current(key)
            self._say(f"{len(targets)} in index {index}" if index else f"{len(targets)} back to Maya's default color",
                      "done")
            self.refresh_scene_colors()

    def _apply_rgb(self, rgb, what: str) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        self._end_try()
        targets = self._targets()
        if targets:
            scene.color(targets, rgb=rgb, **self._where())
            self._palette.set_current("")
            self._say(f"{len(targets)} in {what}", "done")
            self.refresh_scene_colors()

    def _on_own_color(self, text: str) -> None:
        self._save_color_settings()
        self._apply_rgb(colors.from_hex(text), text)

    def _on_saved_color(self, text: str) -> None:
        self._own.set_color(text)
        self._saved.set_current(text)
        self._save_color_settings()
        self._apply_rgb(colors.from_hex(text), text)

    def _on_save_color(self) -> None:
        text = self._own.hex()
        saved = self._saved_colors()
        if text in saved:
            self._say(f"{text} is saved already")
            return
        self._settings["saved_colors"] = (saved + [text])[-SAVED_MAX:]
        self._show_saved()
        self._say(f"Saved {text}", "done")

    def _on_saved_menu(self, text: str, position) -> None:
        self._color_menu_for("saved", text).exec(position)

    def _on_by_side(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = self._targets()
        if targets:
            counted = scene.color_by_side(targets, self._sides(), **self._where())
            self._say(" · ".join(f"{count} {side}" for side, count in counted.items()) + " — in their sides' colors",
                      "done")
            self.refresh_scene_colors()

    def _on_pick_color(self) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        targets = scene.selected_transforms()
        if not targets:
            self._say("Select the object whose color to take", "error")
            return
        rgb, index = scene.read_color(targets[0])
        if rgb is None:
            self._say(f"{targets[0].rpartition('|')[2]} has Maya's default color")
            return
        self._own.set_color(colors.to_hex(rgb))
        self._palette.set_current(str(index) if index else "")
        self._save_color_settings()
        self._say(f"Took {colors.to_hex(rgb)}" + (f" (index {index})" if index else "") + " — your color now", "done")

    def _show_line_width(self) -> None:
        """The Line field shows the first selected control's width (nothing is sent)."""
        try:
            from msl_tools.msl.tools.maya.controls import scene
            controls = scene.controls_in_selection()
            width = scene.line_width(controls[0]) if controls else None
        except ImportError:
            return
        if width is not None and not self._line.hasFocus() and abs(self._line.value() - width) > 1e-6:
            self._line.set_value(width)

    def _on_line_width(self, width: float) -> None:
        from msl_tools.msl.tools.maya.controls import scene
        self._save_color_settings()
        controls = scene.controls_in_selection()
        if controls:
            count = scene.set_line_width(controls, width)
            self._say(f"Line width {width:g} on {count} curve{'s' if count != 1 else ''}", "done")
