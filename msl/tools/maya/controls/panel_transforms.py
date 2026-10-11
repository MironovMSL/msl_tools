# tools/maya/controls/panel_transforms.py
"""The Controls panel's TRANSFORMS card (shown from the window's header, hidden until wanted): the
selected objects matched to the LAST selected one, their channels back to rest, frozen, and a place
in the world copied from one object and pasted onto others. Each of Match / Reset / Freeze is a row
of four word buttons — Move, Rotate, Scale, All — so what a click does is read, not guessed.
Methods of ControlsPanel, kept apart by concern; the scene side is transforms.py."""
import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.ui.theme.qss import repolish
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.widgets.compositions.folding_card import FoldingCard

WHAT = (("Move", (True, False, False)), ("Rotate", (False, True, False)), ("Scale", (False, False, True)),
        ("All", (True, True, True)))
ROWS = (("match", "Match", "The selected objects are put where the LAST selected one is — its {what}, in the world"),
        ("reset", "Reset", "{what} of the selected objects back to rest (0, scale 1) — locked and driven "
                           "channels are left"),
        ("freeze", "Freeze", "Freeze Transformations for {what}: what the channels hold is baked into the "
                             "object, the channels read rest"))


class _TransformsMixin:

    _world_place = None      # a place in the world, copied: kept by the CLASS (it outlives a closed window)

    def _transforms_card(self) -> FoldingCard:
        icons = UiResources().iconManager
        card = self._transforms = FoldingCard("TRANSFORMS", icons.get_icon("move", sub_folder="actions"))
        self._transform_buttons = {}
        for key, title, tip in ROWS:
            row = qt.QtWidgets.QHBoxLayout()
            row.setSpacing(3)
            caption = self._caption(title)
            caption.setFixedWidth(46)
            row.addWidget(caption)
            for word, flags in WHAT:
                button = qt.QtWidgets.QPushButton(word)
                button.setObjectName("controlsQuick")
                what = {"Move": "place", "Rotate": "turn", "Scale": "scale", "All": "place, turn and scale"}[word]
                button.setToolTip(tip.format(what=what if key == "match" else word.lower() if word != "All" else
                                             "move, rotate and scale"))
                button.clicked.connect(lambda _checked=False, key=key, flags=flags, word=word:
                                       self._on_transform(key, flags, word))
                self._transform_buttons[(key, word)] = button
                row.addWidget(button)
            row.addStretch(1)
            card.body_layout.addLayout(row)
        self._world_copy = qt.QtWidgets.QPushButton("Copy")
        self._world_copy.setObjectName("controlsQuick")
        self._world_copy.setToolTip("Remember where the selected object stands in the WORLD (its place, turn and "
                                    "scale)")
        self._world_paste = qt.QtWidgets.QPushButton("Paste")
        self._world_paste.setObjectName("controlsQuick")
        self._world_note = self._caption("")
        row = qt.QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        caption = self._caption("World")
        caption.setFixedWidth(46)
        row.addWidget(caption)
        row.addWidget(self._world_copy)
        row.addWidget(self._world_paste)
        row.addSpacing(6)
        row.addWidget(self._world_note, 1)
        card.body_layout.addLayout(row)
        self._world_copy.clicked.connect(self._on_world_copy)
        self._world_paste.clicked.connect(self._on_world_paste)
        self._show_world_place()
        return card

    def _show_world_place(self) -> None:
        place = _TransformsMixin._world_place
        self._world_note.setText(f"from {place['name']}" if place else "")
        self._world_paste.setToolTip(("The selected objects stand in the world exactly as "
                                      f"{place['name']} did when it was copied — whatever they are parented under")
                                     if place else "Copy an object's place first")
        if bool(self._world_paste.property("primary")) != bool(place):
            self._world_paste.setProperty("primary", bool(place))
            repolish(self._world_paste)

    def _transform_nodes(self) -> list:
        from msl_tools.msl.tools.maya.controls import scene
        nodes = scene.selected_transforms()
        if not nodes:
            self._say("Select objects first", "error")
        return nodes

    def _on_transform(self, key: str, flags, word: str) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes = self._transform_nodes()
        if not nodes:
            return
        move, rotate, scale = flags
        what = word.lower() if word != "All" else "move, rotate and scale"
        if key == "match":
            if len(nodes) < 2:
                self._say("Select what to move, then — last — the object to match it to", "error")
                return
            done, left = transforms.match(nodes, move, rotate, scale)
            target = nodes[-1].rpartition("|")[2]
            text = f"{done} matched to {target} ({what})" if done else f"Nothing matched to {target}"
            if left:
                text += f" · left (locked or driven): {', '.join(left[:3])}"
            self._say(text + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")
        elif key == "reset":
            done, left = transforms.reset(nodes, move, rotate, scale)
            self._say((f"{done} channel{'s' if done != 1 else ''} back to rest ({what})" if done else
                       f"{what.capitalize()} is at rest already") +
                      (f" · {left} locked or driven left" if left else "") + (" · Ctrl+Z undoes it" if done else ""),
                      "done" if done else "")
        else:
            done, left = transforms.freeze(nodes, move, rotate, scale)
            text = f"{done} frozen ({what})" if done else "Nothing frozen"
            if left:
                text += f" · not: {left[0]}" + (f" (+{len(left) - 1})" if len(left) > 1 else "")
            self._say(text + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")

    def _on_world_copy(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        nodes = self._transform_nodes()
        if nodes:
            _TransformsMixin._world_place = transforms.world_place(nodes[0])
            self._show_world_place()
            self._say(f"Where {nodes[0].rpartition('|')[2]} stands in the world is copied — select others and "
                      "paste", "done")

    def _on_world_paste(self) -> None:
        from msl_tools.msl.tools.maya.controls import transforms
        place = _TransformsMixin._world_place
        if not place:
            self._say("Nothing copied yet — select an object and Copy first", "error")
            return
        nodes = self._transform_nodes()
        if nodes:
            done, left = transforms.set_world_place(nodes, place)
            text = f"{done} stand{'s' if done == 1 else ''} where {place['name']} stood" if done else "Nothing moved"
            if left:
                text += f" · left (locked or driven): {', '.join(left[:3])}"
            self._say(text + (" · Ctrl+Z undoes it" if done else ""), "done" if done else "error")
