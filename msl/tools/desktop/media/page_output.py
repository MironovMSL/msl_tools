# tools/desktop/media/page_output.py
"""The Media page's presets and where results go."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.environment.send_to import has_send_to
from msl_tools.msl.ui.theme.qss import make_rounded_popup


class _OutputMixin:
    """MediaPage's presets and where its results go (methods of MediaPage, moved as they were;
    the state they use is made in MediaPage.__init__)."""

    # --- presets ----------------------------------------------------------------------------

    def _presets_of(self, panel) -> dict:
        """The presets of `panel`: the user's once they changed anything, the built-in ones until then."""
        if self._has_node("presets", panel.KEY):
            return self._node("presets", panel.KEY)
        return {name: dict(settings) for name, settings in panel.PRESETS.items()}

    def _refresh_presets(self) -> None:
        panel = self._panel()
        shown = panel is not None
        self._presets_caption.setVisible(shown)
        self._presets.setVisible(shown)
        if not shown:
            return
        presets = self._presets_of(panel)
        chips = [(name, name, ",  ".join(f"{key}: {value}" for key, value in settings.items())
                  + chr(10) + "Click: use these settings  ·  right click: remove") for name, settings in presets.items()]
        self._presets.set_chips(chips, removable=set(presets))
        self._mark_preset()

    def _on_preset_clicked(self, name: str) -> None:
        panel = self._panel()
        settings = self._presets_of(panel).get(name) if panel is not None else None
        if settings is None:
            return
        self._applying = True
        try:
            panel.apply_settings({**panel.settings(), **settings})
        finally:
            self._applying = False
        self._on_panel_changed()
        self._say(f"“{name}” applied.")

    def _on_preset_added(self, name: str) -> None:
        panel = self._panel()
        if panel is None:
            return
        presets = self._presets_of(panel)
        replaced = name in presets
        presets[name] = panel.settings()
        self._config["presets"][panel.KEY] = presets
        self._refresh_presets()
        self._say(f"Preset “{name}” " + ("updated." if replaced else "saved."))

    def _on_preset_removed(self, name: str) -> None:
        panel = self._panel()
        if panel is None:
            return
        presets = self._presets_of(panel)
        presets.pop(name, None)
        self._config["presets"][panel.KEY] = presets
        self._refresh_presets()

    # --- where results go --------------------------------------------------------------------

    def _folder(self) -> str:
        """The one folder for all results ("" = next to each source)."""
        folder = str(self._settings.get("output_folder", "") or "")
        return folder if folder and Path(folder).is_dir() else ""

    def _on_folder_menu(self) -> None:
        menu = make_rounded_popup(qt.QtWidgets.QMenu(self))
        menu.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        folder = self._folder()
        beside = menu.addAction("Next to each source")
        beside.setCheckable(True)
        beside.setChecked(not folder)
        beside.triggered.connect(lambda: self._set_folder(""))
        if folder:
            current = menu.addAction(f"Into {folder}")
            current.setCheckable(True)
            current.setChecked(True)
        menu.addSeparator()
        menu.addAction("Choose a folder…").triggered.connect(self._on_choose_folder)
        menu.addSeparator()
        notify = menu.addAction("Tell me when the jobs are done")
        notify.setCheckable(True)
        notify.setChecked(self._notifies())
        notify.setToolTip("A notice from Windows when the last job is over and this window isn’t in front")
        notify.triggered.connect(lambda checked: self._settings.__setitem__("notify", bool(checked)))
        send_to = menu.addAction("Explorer: “Send to → MSL Media”")
        send_to.setCheckable(True)
        send_to.setChecked(has_send_to(self.SEND_TO_NAME))
        send_to.setToolTip("Adds “MSL Media” to the “Send to” menu of Explorer’s right click: files sent there "
                           "open here — in the hub that is open, or a new one")
        send_to.triggered.connect(lambda checked: self._set_send_to(bool(checked)))
        self._folder_menu = menu  # for tests; the menu deletes itself on close
        menu.popup(self._folder_button.mapToGlobal(qt.QtCore.QPoint(0, self._folder_button.height())))

    def _on_choose_folder(self) -> None:
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "The folder for results", self._folder())
        if folder:
            self._set_folder(folder)

    def _set_folder(self, folder: str) -> None:
        self._settings["output_folder"] = folder
        self._output_edited = False
        self._suggest_output()
        self._refresh_controls()

    def _suggest_output(self) -> None:
        """Puts a free name into "Save as" — unless the user typed their own."""
        panel = self._panel()
        if panel is None or self._output_edited or not self._one_result():
            return
        self._set_output(panel.output_for(self._sources[0], self._folder() or None, self._queue.outputs()))
        self._output_caption.setToolTip("Save into this folder" if panel.INTO_FOLDER else "Save as")

    def _set_output(self, path: Path) -> None:
        """Where the one result goes: its name into the field, its folder onto the line under it."""
        path = Path(path)
        self._output_dir = path.parent
        self._output.setText(path.name)
        self._output_folder.setText(f"in {path.parent}")

    def _output_path(self) -> Path | None:
        """The path the field stands for (None while it is empty). A name is taken in the
        folder shown under the field; a whole path typed into the field is taken as it is."""
        text = self._output.text().strip()
        if not text:
            return None
        typed = Path(text)
        return typed if typed.is_absolute() else self._output_dir / typed

    def _on_output_typed(self) -> None:
        """A whole path was typed or pasted: its folder moves to the line under the field."""
        text = self._output.text().strip()
        if text and Path(text).is_absolute() and Path(text).name:
            self._set_output(Path(text))

    def _on_browse_output(self) -> None:
        panel = self._panel()
        current = self._output_path() or Path(".")
        if panel is not None and panel.INTO_FOLDER:
            path = qt.QtWidgets.QFileDialog.getExistingDirectory(
                self, "The folder for the frames", str(current if current.is_dir() else current.parent))
        else:
            path, _filter = qt.QtWidgets.QFileDialog.getSaveFileName(self, "Save the result as", str(current),
                                                                     "All files (*.*)")
        if path:
            self._set_output(Path(path))
            self._output_edited = True
