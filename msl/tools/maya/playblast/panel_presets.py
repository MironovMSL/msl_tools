# tools/maya/playblast/panel_presets.py
"""The Playblast panel's sets of choices: what it shows, whole presets, what was made before."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.playblast import capture, naming
from msl_tools.msl.tools.maya.playblast.visibility_dialog import VisibilityDialog
from msl_tools.msl.tools.maya.playblast.panel_tables import (MASK_LOOK_DEFAULTS, PRESETS, PRESET_KEYS, SHOW_CUSTOM,
                                                             SHOW_VIEWPORT, _plain)


class _PresetsMixin:
    """PlayblastPanel's choices that come as sets: what the playblast shows, the presets of the
    whole playblast, what was made before (methods of PlayblastPanel, moved as they were)."""

    # ------------------------------------------------------------------ what the playblast shows

    def _show_presets(self) -> dict:
        """name -> the kinds shown: the built-in presets, then the user's own (a same name replaces)."""
        presets = {name: list(kinds) for name, kinds in capture.VISIBILITY_PRESETS.items()}
        if "show_presets" in self._config.data:
            for name, kinds in _plain(self._config["show_presets"]).items():
                presets[str(name)] = [str(kind) for kind in kinds]
        return presets

    def _own_show_presets(self) -> dict:
        return dict(_plain(self._config["show_presets"])) if "show_presets" in self._config.data else {}

    def _fill_show(self, current: str) -> None:
        loading, self._loading = self._loading, True
        names = [SHOW_VIEWPORT, *self._show_presets(), SHOW_CUSTOM]
        self._visible.clear()
        self._visible.addItems(names)
        self._set_combo(self._visible, current if current in names else SHOW_VIEWPORT)
        self._loading = loading
        self._describe_show()

    def _shown_kinds(self):
        """The kinds the playblast shows, or None = whatever the viewport shows."""
        choice = self._visible.currentText()
        if choice == SHOW_VIEWPORT:
            return None
        if choice == SHOW_CUSTOM:
            return tuple(_plain(self._settings.get("show_custom") or []))
        return tuple(self._show_presets().get(choice, ()))

    def _describe_show(self) -> None:
        kinds = self._shown_kinds()
        if kinds is None:
            text = "The playblast shows what the viewport shows."
        else:
            names = [capture.VISIBILITY_LABELS.get(kind, kind) for kind in kinds]
            text = "The playblast shows only:\n" + (", ".join(names) or "nothing")
        self._visible.setToolTip(text + "\n\nThe viewport itself is put back afterwards.")

    def _on_show_edit(self) -> None:
        choice = self._visible.currentText()
        own = self._own_show_presets()
        kinds = self._shown_kinds()
        if kinds is None:
            try:
                kinds = [kind for kind, shown in capture.visibility_state().items() if shown]
            except capture.CaptureError:
                kinds = []
        answer = VisibilityDialog.ask(self.window(), kinds, preset=choice if choice in own else "",
                                      removable=choice in own)
        if answer is None:
            return
        kinds, name, removed = answer
        if removed:
            own.pop(choice, None)
            self._config["show_presets"] = own
            self._fill_show(SHOW_VIEWPORT)
        elif name and name not in (SHOW_VIEWPORT, SHOW_CUSTOM):
            own[name] = list(kinds)
            self._config["show_presets"] = own
            self._fill_show(name)
        else:
            self._settings["show_custom"] = list(kinds)
            self._fill_show(SHOW_CUSTOM)
        self._on_changed()

    def _on_browse(self) -> None:
        values = self._token_values()
        current = naming.expand(self._folder.text().strip() or naming.DEFAULT_FOLDER, values)
        folder = qt.QtWidgets.QFileDialog.getExistingDirectory(self, "Where playblasts go", current)
        if folder:
            project = values["project"].replace("\\", "/")
            if project and folder.replace("\\", "/").lower().startswith(project.lower() + "/"):
                folder = "{project}" + folder.replace("\\", "/")[len(project):]  # stays right in another project
            self._folder.setText(folder)
            self._on_changed()

    # ------------------------------------------------------------------ presets of the whole playblast

    def _preset_list(self) -> list:
        """[(name, values)], in the order shown: the built-in ones until the user saves or removes one."""
        if "presets" in self._config.data:
            try:
                return [(str(entry["name"]), _plain(entry["values"])) for entry in self._config["presets"]]
            except (KeyError, TypeError, ValueError):
                pass
        return [(name, dict(values)) for name, values in PRESETS.items()]

    def _preset_now(self) -> dict:
        """What a preset saved now would hold."""
        values = {key: _plain(self._settings.get(key, self.DEFAULTS[key])) for key in PRESET_KEYS}
        values["mask"] = dict(self._mask_look(), shown=self._mask_on.isChecked())
        return values

    @staticmethod
    def _preset_matches(values: dict, now: dict) -> bool:
        """Everything the preset sets is what is set now (what it leaves out doesn't count)."""
        for key, value in values.items():
            if key == "mask":
                look = now["mask"]
                if any(dict(MASK_LOOK_DEFAULTS, **look).get(name) != item for name, item in value.items()):
                    return False
            elif now.get(key) != value:
                return False
        return True

    def _mark_presets(self) -> None:
        presets = self._preset_list()
        self._presets.set_chips([(name, name, "") for name, _values in presets],
                                removable={name for name, _values in presets})
        now = self._preset_now()
        self._presets.set_marked([name for name, values in presets if self._preset_matches(values, now)])

    def _on_preset(self, name: str) -> None:
        values = dict(self._preset_list()).get(name)
        if values is None or self._busy:
            return
        for key, value in values.items():
            if key == "mask":
                saved = dict(_plain(self._settings.get("mask") or {}))
                saved.update(value)
                self._settings["mask"] = saved
            else:
                self._settings[key] = value
        self._apply_settings()
        self.refresh()
        self._save_mask()

    def _on_preset_saved(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self._save_settings()
        presets = [(old, values) for old, values in self._preset_list() if old != name]
        self._config["presets"] = [{"name": old, "values": values}
                                   for old, values in presets + [(name, self._preset_now())]]
        self._mark_presets()

    def _on_preset_removed(self, name: str) -> None:
        self._config["presets"] = [{"name": old, "values": values}
                                   for old, values in self._preset_list() if old != name]
        self._mark_presets()

    def _history(self) -> list:
        try:
            return [dict(entry) for entry in self._config["history"]]
        except (KeyError, TypeError, ValueError):
            return []

    @staticmethod
    def _is_this_scene(entry: dict, scene: str, scene_path: str) -> bool:
        """A record of this scene: by the scene's FILE when the record has one (two "shot_010"
        of two projects aren't one scene); by name for older records and unsaved scenes."""
        if entry.get("scene_path") and scene_path:
            return entry["scene_path"] == scene_path
        return entry.get("scene") == scene

    def _refresh_recent(self) -> None:
        """The RECENT card: this scene's last playblasts that still exist, newest first."""
        scene, scene_path = capture.scene_name() or "untitled", capture.scene_path()
        self._recent_scene = scene_path
        mine = [entry for entry in self._history()
                if self._is_this_scene(entry, scene, scene_path) and entry.get("path")
                and Path(entry["path"]).exists()]
        self._recent.show_results(mine[-self.RECENT_SHOWN:][::-1], self._tools, total=len(mine),
                                  slots=self.RECENT_SHOWN)

    def _on_recent_clear(self) -> None:
        """Forgets this scene's results (the files stay)."""
        scene, scene_path = capture.scene_name() or "untitled", capture.scene_path()
        self._config["history"] = [entry for entry in self._history()
                                   if not self._is_this_scene(entry, scene, scene_path)]
        self._refresh_recent()
