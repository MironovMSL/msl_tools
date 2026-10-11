# tools/maya/controls/panel_editor.py
"""How the Controls panel hands a shape to the shape editor (editor.py) and takes it back: the editor
opened in the library's room, the working copy of the picked shape, a curve taken from the scene and put
back, Reset, saving as a new shape or over the library's own. Methods of ControlsPanel, kept apart by
concern (moved out of panel.py as they were)."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.controls import shapes as shape_data


class _EditorMixin:

    _edited = None          # the picked shape as changed by hand; Create, the ghost and Replace use it

    _taken = ""             # the control the working copy was TAKEN from ("" = it began as a library shape)

    def _pick_saved(self, name: str) -> None:
        """A shape just saved / brought in becomes THE picked shape. The editor's working copy of the
        shape picked before goes with it — else Create kept making that old copy while the library
        showed the new shape as picked (it did: a curve saved from the scene, then Create made a pin)."""
        self._settings["shape"] = name
        self._drop_edited()
        if self._editor.isVisible():
            shape = self._library_shape()
            self._editor.open(shape.curves, shape.title())

    def _drop_edited(self) -> None:
        self._edited, self._taken = None, ""
        self._editor.set_apply_text("Onto the selected controls")

    @staticmethod
    def _unturned(curves: list, axis: str) -> list:
        """Curves as they are on a control, turned back to how the library keeps a shape (facing +Y):
        turned to `axis` again — what Create does — they are exactly what they were."""
        if axis == "X":
            back = lambda q: (q[1], q[0], -q[2])       # the turn to X is its own inverse
        elif axis == "Z":
            back = lambda q: (q[1], q[2], q[0])
        else:
            return curves
        return [shape_data.Curve([back(point) for point in curve.points], curve.degree, curve.closed) for curve in curves]

    @staticmethod
    def _curve_selected() -> bool:
        try:
            from msl_tools.msl.tools.maya.controls import scene
            return bool(scene.controls_in_selection())
        except (ImportError, RuntimeError, ValueError):
            return False

    def _take_shape(self) -> None:
        """The selected control's shape into the editor, as it is in the scene: to be changed and put
        back exactly, made again elsewhere, or saved as a shape of yours."""
        from msl_tools.msl.tools.maya.controls import scene
        controls = self._selected_controls()
        if not controls:
            return
        name = controls[0].rpartition("|")[2]
        curves = self._unturned(scene.read_curves(controls[0]), self._view.axis())
        self._edited = shape_data.Shape(name.rpartition(":")[2], curves, "Mine", True)
        self._taken = name
        self._editor.open(curves, f"{name} · from the scene")
        self._editor.set_apply_text("Back onto the selected controls")
        self._show_preview()
        self._say(f"The curve {name} is in the editor — change it, put it back, or Save… it as a shape of yours "
                  "(Reset: the library's shape)", "done")

    def _set_editing(self, on: bool) -> None:
        if on == self._editor.isVisible():
            return
        for widget in (self._grid, self._view, self._create, self._strip):
            widget.setVisible(not on)
        self._no_favorites.hide()
        self._editor.setVisible(on)
        if not on:
            self._refresh_grid()
        if on:
            shape = self._picked_shape()
            self._editor.open(shape.curves, shape.title() + (" · edited" if self._edited is not None else ""))
            self._editor.set_create_text(self._create.text())
            # a curve is selected in the scene: THAT is what one opens the editor for — it comes in as
            # it is, to be changed, put back or saved as a shape (Reset: the library's shape instead)
            if not self._taken and self._curve_selected():
                self._take_shape()

    def _on_shape_edited(self) -> None:
        if self._taken:
            self._edited = shape_data.Shape(self._edited.name, self._editor.curves(), "Mine", True)
            self._editor.set_title(f"{self._taken} · from the scene · edited")
        else:
            source = self._library_shape()
            self._edited = shape_data.Shape(source.name, self._editor.curves(), source.category, True)
            self._editor.set_title(source.title() + " · edited")
        self._show_preview()

    def _reset_edited(self) -> None:
        self._drop_edited()
        source = self._library_shape()
        self._editor.open(source.curves, source.title())
        self._show_preview()
        self._say(f"“{source.title()}” is as the library has it again", "")

    def _on_save_edited(self) -> None:
        from msl_tools.msl.tools.maya.rename.panel_words import _field_action
        source = self._edited if self._taken else self._library_shape()
        button = self._editor.save_button()
        menu = self._menu()
        if not self._taken:
            # a fix of the shape itself: it stays what and where it is in the library
            self._menu_caption(menu, "The library's shape")
            self._menu_item(menu, "save", f"Update “{source.title()}”", self._update_shape,
                            "The library keeps the shape as it is in the editor now, in its place — "
                            + ("your shape is saved over" if source.user else
                               "a correction of the built-in shape; the library's right-click menu can "
                               "bring the built-in one back"))
            menu.addSeparator()
        self._menu_caption(menu, "A new shape of yours — its name:")
        _field_action(menu, source.name, "Shape name", self._save_edited)
        menu.exec(button.mapToGlobal(qt.QtCore.QPoint(0, button.height())))

    def _update_shape(self) -> None:
        """The picked library shape becomes what is in the editor (not a new shape under Mine)."""
        name = self._settings.get("shape", "circle")
        if self._taken or not self.library.update(name, self._editor.curves()):
            self._say("Nothing to update — pick a shape of the library first", "error")
            return
        self._drop_edited()
        self._refresh_grid()
        shape = self._library_shape()
        self._editor.open(shape.curves, shape.title())
        self._say(f"The library's “{shape.title()}” is updated" +
                  ("" if shape.user else " — right click it in the library to bring the built-in one back"), "done")

    def _save_edited(self, name: str) -> None:
        saved = self.library.add(name, self._editor.curves())
        self._drop_edited()
        self._settings["shape"] = saved
        self._add_favorites([saved])
        self._show_saved_shape()
        self._refresh_grid()
        shape = self._library_shape()
        self._editor.open(shape.curves, shape.title())
        self._say(f"Saved the shape “{saved}” — it is among your favorites (and under Mine)", "done")
