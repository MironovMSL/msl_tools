# tools/desktop/media/name_dialog.py
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.media import names
from msl_tools.msl.ui.widgets.atoms.editors.token_line_edit import TokenLineEdit
from msl_tools.msl.ui.widgets.compositions.chip_bar import ChipBar
from msl_tools.msl.ui.widgets.windows.frameless_dialog import FramelessDialog


class NameTemplateDialog(FramelessDialog):
    """How Media names its results: a template with tokens ({name}, {action},
    {date}, {time}, {n} — core/media/names.py), a few ready ones as chips, and
    a live example of the name it gives.

        template = NameTemplateDialog.ask(parent, current, example_source="shot_010.mov")

    `ask()` returns the template ("" = the classic "<name>_<action>"), or None
    when cancelled.
    """

    def __init__(self, template: str, example: str = "", parent=None):
        super().__init__(title="Names of the results", width=470, height=250, show_minimize_button=False,
                         show_maximize_button=False, show_theme_toggle=False, parent=parent)
        self._result = None
        self._example_name = Path(example).stem if example else "shot_010"
        body = qt.QtWidgets.QWidget()
        column = qt.QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(14, 10, 14, 12)
        column.setSpacing(8)
        self._ready = ChipBar()
        self._ready.set_chips([(text, title, text) for title, text in names.PRESETS.items()])
        self._ready.clicked.connect(lambda text: self._field.setText(text))
        column.addWidget(self._ready)
        self._field = TokenLineEdit(names.TOKENS)
        self._field.setPlaceholderText(names.DEFAULT)
        self._field.setText(template)
        self._field.setToolTip("Right click: put in a token")
        self._field.textChanged.connect(self._sync)
        column.addWidget(self._field)
        self._example = qt.QtWidgets.QLabel()
        self._example.setObjectName("mediaHint")
        self._example.setWordWrap(True)
        column.addWidget(self._example)
        hint = qt.QtWidgets.QLabel("{n} counts up from the highest number of that name in the folder: "
                                   "_v{n} gives v001, v002… Right click in the field for every token.")
        hint.setObjectName("mediaHint")
        hint.setWordWrap(True)
        column.addWidget(hint)
        column.addStretch(1)
        buttons = qt.QtWidgets.QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = qt.QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._use = qt.QtWidgets.QPushButton("Use")
        self._use.setProperty("primary", True)
        self._use.setDefault(True)
        self._use.clicked.connect(self._on_use)
        buttons.addWidget(cancel)
        buttons.addWidget(self._use)
        column.addLayout(buttons)
        self.add_widget(body)
        self._sync()

    @classmethod
    def ask(cls, parent, template: str, example_source: str = ""):
        dialog = cls(template, example_source, parent=parent)
        try:
            dialog.exec()
            return dialog._result
        finally:
            dialog.deleteLater()

    def _template(self) -> str:
        text = self._field.text().strip()
        return "" if text == names.DEFAULT else text

    def _sync(self) -> None:
        template = self._template()
        unknown = names.unknown_tokens(template)
        self._ready.set_marked([text for text in names.PRESETS.values() if text == (template or names.DEFAULT)])
        if unknown:
            self._example.setText("Unknown: " + ", ".join("{" + name + "}" for name in unknown))
        else:
            self._example.setText("For example:  " + names.expand(template, self._example_name, "small", number=1)
                                  + ".mp4")
        self._use.setEnabled(not unknown)

    def _on_use(self) -> None:
        self._result = self._template()
        self.accept()
