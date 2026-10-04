# tools/maya/playblast/panel_mask.py
"""The Playblast panel's shot mask card."""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.tools.maya.playblast import capture, mask
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.atoms.icons.tinted_icon import TintedIcon
from msl_tools.msl.tools.maya.playblast.panel_tables import (BRAND_LOGO, MASK_BARS, MASK_LETTERBOX,
                                                             MASK_LOOK_DEFAULTS, MASK_OPACITY, MASK_PLACES,
                                                             MASK_PRESETS, MASK_TEXT, _plain)


class _MaskMixin:
    """PlayblastPanel's shot mask card: its looks, presets, slots, logo, font (methods of
    PlayblastPanel, moved as they were; the state they use is made in its __init__)."""

    def _mask_card(self) -> qt.QtWidgets.QFrame:
        """The shot mask's card. Its heading folds it: the mask is set up once and then left alone,
        so folded (one line saying what it is) is how it usually sits."""
        card = qt.QtWidgets.QFrame()
        card.setObjectName("playblastCard")
        icon = TintedIcon(UiResources().iconManager.get_icon("text_frame", sub_folder="actions"), 14)
        icon.setObjectName("playblastCardIcon")
        heading = qt.QtWidgets.QLabel("SHOT MASK")
        heading.setObjectName("playblastSection")
        self._mask_header = qt.QtWidgets.QWidget()
        self._mask_header.setCursor(qt.QtCore.Qt.CursorShape.PointingHandCursor)
        self._mask_header.setToolTip("Click to show or hide the mask's settings")
        self._mask_header.installEventFilter(self)
        top = qt.QtWidgets.QHBoxLayout(self._mask_header)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self._mask_chevron)
        top.addWidget(icon)
        top.addWidget(heading)
        top.addWidget(self._mask_summary, 1)
        top.addWidget(self._mask_on)

        editor = qt.QtWidgets.QHBoxLayout()
        editor.setSpacing(8)
        editor.addWidget(self._mask_slot_label)
        editor.addWidget(self._mask_edit, 1)
        # caption | controls, one row per thing the mask is made of
        look = qt.QtWidgets.QGridLayout()
        look.setContentsMargins(0, 0, 0, 0)
        look.setHorizontalSpacing(8)
        look.setVerticalSpacing(6)
        look.setColumnStretch(1, 1)
        rows = (("Text", [(self._mask_font, 3), (self._mask_text, 2), (self._mask_text_opacity, 2),
                          (self._mask_text_color, 0)]),
                ("Bars", [(self._mask_bars, 2), (self._mask_letterbox, 2), (self._mask_top, 0), (self._mask_bottom, 0),
                          (self._mask_bar_color, 0)]),
                ("Counter", [(self._mask_digits, 0)]),
                ("Note", [(self._mask_note, 1)]),
                ("Logo", [(self._mask_logo, 1), (self._mask_logo_browse, 0), (self._mask_logo_brand, 0)]))
        for index, (caption, widgets) in enumerate(rows):
            label = qt.QtWidgets.QLabel(caption)
            label.setObjectName("playblastCaption")
            look.addWidget(label, index, 0)
            line = qt.QtWidgets.QHBoxLayout()
            line.setSpacing(4)
            for widget, stretch in widgets:
                line.addWidget(widget, stretch)
            if caption == "Counter":
                digits = qt.QtWidgets.QLabel("digits")
                digits.setObjectName("playblastHint")
                line.addWidget(digits)
                line.addStretch(1)
            look.addLayout(line, index, 1)

        self._mask_body = qt.QtWidgets.QWidget()
        inner = qt.QtWidgets.QVBoxLayout(self._mask_body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        inner.addWidget(self._mask_presets)
        inner.addWidget(self._mask_preview)
        inner.addLayout(editor)
        inner.addLayout(look)
        inner.addWidget(self._mask_warn)
        box = qt.QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        box.addWidget(self._mask_header)
        box.addWidget(self._mask_body)
        return card

    def _set_mask_open(self, opened: bool, save: bool = True) -> None:
        icons = UiResources().iconManager
        self._mask_body.setVisible(opened)
        self._mask_chevron.set_icon(icons.get_icon("chevron_down" if opened else "chevron_right", sub_folder="actions"))
        # folded, the heading says what the mask is; open, the line stays (empty) so the switch keeps its place
        self._mask_summary.setText("" if opened else getattr(self, "_mask_summary_text", ""))
        if save:
            saved = dict(_plain(self._settings.get("mask") or {}))
            saved["open"] = opened
            self._settings["mask"] = saved

    # ------------------------------------------------------------------ the shot mask

    def _mask_settings(self) -> mask.MaskSettings:
        """The mask as the controls say it."""
        width, height = self._frame_size()
        start, end = self._frames()
        return mask.MaskSettings(
            texts=dict(self._mask_texts),
            aspect=width / height if height else 0.0,
            text_scale=MASK_TEXT.get(self._mask_text.currentText(), 1.0),
            bar_opacity=MASK_BARS.get(self._mask_bars.currentText(), 1.0),
            text_color=self._mask_text_color.rgb(), bar_color=self._mask_bar_color.rgb(),
            font=self._mask_font.currentText(),
            text_opacity=MASK_OPACITY.get(self._mask_text_opacity.currentText(), 1.0),
            letterbox=MASK_LETTERBOX.get(self._mask_letterbox.currentText(), 0.0),
            counter_padding=int(self._mask_digits.currentText() or 4),
            top_bar=self._mask_top.isChecked(), bottom_bar=self._mask_bottom.isChecked(),
            logo=self._mask_logo.text().strip() or str(BRAND_LOGO),
            note=self._mask_note.text(), project=Path(capture.project_folder().rstrip("/\\")).name,
            width=width, height=height, warn_range=self._mask_warn.isChecked(), range_start=start, range_end=end)

    def _mask_look(self) -> dict:
        """What a preset keeps: the texts, the sizes, the colors."""
        return {"texts": dict(self._mask_texts),
                "text": self._mask_text.currentText(), "bars": self._mask_bars.currentText(),
                "text_color": self._mask_text_color.hex(), "bar_color": self._mask_bar_color.hex(),
                "top_bar": self._mask_top.isChecked(), "bottom_bar": self._mask_bottom.isChecked(),
                "font": self._mask_font.currentText(), "text_opacity": self._mask_text_opacity.currentText(),
                "letterbox": self._mask_letterbox.currentText(), "digits": self._mask_digits.currentText()}

    def _apply_mask_look(self, look) -> None:
        texts = look.get("texts") or mask.DEFAULT_TEXTS
        self._mask_texts = {slot: str(texts.get(slot, "")) for slot in mask.SLOTS}
        self._mask_edit.setText(self._mask_texts[self._mask_slot])
        self._set_combo(self._mask_text, look.get("text", "Medium"))
        self._set_combo(self._mask_bars, look.get("bars", "Solid"))
        self._mask_text_color.set_color(str(look.get("text_color", "#ffffff")))
        self._mask_bar_color.set_color(str(look.get("bar_color", "#000000")))
        self._mask_top.set_checked_immediate(bool(look.get("top_bar", True)))
        self._mask_bottom.set_checked_immediate(bool(look.get("bottom_bar", True)))
        font = str(look.get("font", MASK_LOOK_DEFAULTS["font"]))
        if self._mask_font.findText(font) < 0:
            self._mask_font.addItem(font)  # the list of real fonts comes when the panel is shown
        self._set_combo(self._mask_font, font)
        self._set_combo(self._mask_text_opacity, look.get("text_opacity", MASK_LOOK_DEFAULTS["text_opacity"]))
        self._set_combo(self._mask_letterbox, look.get("letterbox", MASK_LOOK_DEFAULTS["letterbox"]))
        self._set_combo(self._mask_digits, look.get("digits", MASK_LOOK_DEFAULTS["digits"]))

    # presets of the mask: the built-in ones until the user saves or removes one, then the config's

    def _mask_preset_list(self) -> list:
        """[(name, look)], in the order shown."""
        # asked of the stored data: reading a key that isn't there gives an empty node, not an error
        if "mask_presets" in self._config.data:
            try:
                return [(str(entry["name"]), _plain(entry["look"])) for entry in self._config["mask_presets"]]
            except (KeyError, TypeError, ValueError):
                pass
        return [(name, dict(look)) for name, look in MASK_PRESETS.items()]

    def _store_mask_presets(self, presets: list) -> None:
        self._config["mask_presets"] = [{"name": name, "look": look} for name, look in presets]
        self._show_mask_presets()

    def _show_mask_presets(self) -> None:
        presets = self._mask_preset_list()
        self._mask_presets.set_chips([(name, name, "") for name, _look in presets],
                                     removable={name for name, _look in presets})
        current = self._mask_look()
        self._mask_presets.set_marked([name for name, look in presets
                                       if dict(MASK_LOOK_DEFAULTS, **look) == current])

    def _on_mask_preset(self, name: str) -> None:
        look = dict(self._mask_preset_list()).get(name)
        if look is None:
            return
        self._loading = True
        self._apply_mask_look(look)
        self._loading = False
        self._on_mask_changed()

    def _on_mask_preset_saved(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        presets = [(old, look) for old, look in self._mask_preset_list() if old != name]
        self._store_mask_presets(presets + [(name, self._mask_look())])

    def _on_mask_preset_removed(self, name: str) -> None:
        self._store_mask_presets([(old, look) for old, look in self._mask_preset_list() if old != name])

    def _save_mask(self) -> None:
        self._settings["mask"] = dict(self._mask_look(), shown=self._mask_on.isChecked(),
                                      note=self._mask_note.text(), warn=self._mask_warn.isChecked(),
                                      logo=self._mask_logo.text().strip(),
                                      open=self._mask_body.isVisibleTo(self._mask_body.parentWidget()))
        self._show_mask_presets()  # the one that matches what is on screen is outlined
        self._refresh_mask_preview()
        self._mark_presets()

    # the six texts: picked in the sketch, written in the one field

    def _select_mask_slot(self, slot: str) -> None:
        if slot not in self._mask_texts:
            return
        self._mask_slot = slot
        self._mask_slot_label.setText(MASK_PLACES[slot])
        self._mask_edit.setText(self._mask_texts[slot])
        self._mask_preview.set_current(slot)
        self._mask_edit.setFocus()

    def _on_mask_edit(self, *_args) -> None:
        self._mask_texts[self._mask_slot] = self._mask_edit.text()
        self._on_mask_changed()

    def _set_mask_text(self, slot: str, text: str) -> None:
        """Writes a slot's text (as if typed)."""
        self._mask_texts[slot] = text
        if slot == self._mask_slot:
            self._mask_edit.setText(text)
        self._on_mask_changed()

    def _refresh_mask_preview(self) -> None:
        """The sketch and the folded card's one line, from what the controls say now."""
        settings = self._mask_settings()
        try:
            values = mask.token_values(self._camera_name(), settings)
        except Exception:
            values = {}
        self._mask_preview.set_look(
            texts=dict(self._mask_texts), values=values, text_color=self._mask_text_color.hex(),
            bar_color=self._mask_bar_color.hex(), bar_opacity=settings.bar_opacity,
            text_opacity=settings.text_opacity, top_bar=settings.top_bar, bottom_bar=settings.bottom_bar,
            font=settings.font, aspect=settings.aspect or 16 / 9, letterbox=settings.letterbox, logo=settings.logo)
        filled = sum(1 for text in self._mask_texts.values() if text.strip())
        current = self._mask_look()
        preset = next((name for name, look in self._mask_preset_list()
                       if dict(MASK_LOOK_DEFAULTS, **look) == current), "")
        self._mask_summary_text = " · ".join(part for part in (preset, f"{filled} of 6 slots", settings.font) if part)
        folded = not self._mask_body.isVisibleTo(self._mask_body.parentWidget())
        self._mask_summary.setText(self._mask_summary_text if folded else "")

    def _load_fonts(self) -> None:
        """The fonts Maya's viewport can draw, into the list (once; asked of Maya, so not in the constructor)."""
        if self._mask_font.count() > 3:
            return
        current = self._mask_font.currentText()
        names = mask.fonts()
        if current and current not in names:
            names.append(current)
        self._loading = True
        self._mask_font.clear()
        self._mask_font.addItems(names)
        self._set_combo(self._mask_font, current or "Consolas")
        self._loading = False

    def _sync_mask(self) -> None:
        """Makes the viewport match the switch: a new or reopened scene has lost the mask, and the
        frame it frames follows the size chosen above."""
        if self._busy:
            return
        try:
            if self._mask_on.isChecked():
                settings = self._mask_settings()
                # refresh() runs on every pointer enter: ~20 setAttr + a viewport redraw only when
                # something changed, or the scene lost the mask (a new / reopened scene)
                if settings != self._mask_applied or not mask.is_shown():
                    mask.show(settings)
                    self._mask_applied = settings
            elif mask.is_shown():
                mask.hide()
                self._mask_applied = None
        except mask.MaskError as error:
            self._mask_on.set_checked_immediate(False)
            self._save_mask()
            self._say(str(error), "error")

    def _on_mask_toggled(self, *_args) -> None:
        if not self._loading:
            self._save_mask()
            self._sync_mask()

    def _on_mask_changed(self, *_args) -> None:
        if not self._loading:
            self._save_mask()
            if self._mask_on.isChecked():
                self._sync_mask()

    def _on_mask_logo_browse(self) -> None:
        current = self._mask_logo.text().strip() or str(BRAND_LOGO)
        file, _filter = qt.QtWidgets.QFileDialog.getOpenFileName(
            self, "The logo", str(Path(current).parent), "Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if file:
            self._mask_logo.setText(file)
            self._on_mask_changed()

    def _on_mask_logo_brand(self) -> None:
        self._mask_logo.setText("")
        self._on_mask_changed()
