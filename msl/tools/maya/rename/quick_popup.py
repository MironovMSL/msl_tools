# tools/maya/rename/quick_popup.py
import html

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.resources import Resources
from msl_tools.msl.tools.maya.rename import rules, scene
from msl_tools.msl.tools.maya.rename.library import NameLibrary
from msl_tools.msl.tools.maya.rename.panel import RenamePanel, TemplateField  # (registers rename.qss)
from msl_tools.msl.ui.theme import StylesheetBuilder
from msl_tools.msl.ui.theme.qss import make_rounded_popup
from msl_tools.msl.ui.ui_resources import UiResources
from msl_tools.msl.ui.windows.maya_window_query import MayaWindowQuery


class QuickRename(qt.QtWidgets.QWidget):
    """A small field at the mouse pointer for a rename without the window (a hotkey: MSLRenameQuick).

    Type the name — the same template as the window's ({#}, {A}, {side}, {type}, with its number,
    side and suffix settings) —, Enter renames the selection and closes it, Esc or a click elsewhere
    closes it. A few lines under the field show "before → after". Up / Down walk the names used
    last. One object selected: the field starts with its name, selected (as F2 in a file manager);
    several: with the name used last.
    """

    PREVIEW_LINES = 4

    def __init__(self, parent=None):
        super().__init__(parent, qt.QtCore.Qt.WindowType.Popup)
        make_rounded_popup(self)
        self.setAttribute(qt.QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setObjectName("quickRename")
        config = Resources().configsMayaMng.get_config(RenamePanel.TOOL_NAME,
                                                       defaults={"settings": dict(RenamePanel.DEFAULTS)})
        self._config = config
        self._settings = config["settings"]
        self.library = NameLibrary(config["library"])
        self._recent = self.library.recent()
        self._recent_index = -1
        self._nodes = scene.nodes(scene.paths(scene.SCOPE_SELECTED)[:RenamePanel.MAX_OBJECTS])

        frame = qt.QtWidgets.QFrame(self)
        frame.setObjectName("quickRenameFrame")
        self._frame = frame
        self._drag_from = None
        # The move cursor only over the frame (not the field): a popup holds the mouse, so a cursor
        # set on the frame would show over the WHOLE screen. Where the pointer is, is looked at.
        self._cursor_timer = qt.QtCore.QTimer(self)
        self._cursor_timer.setInterval(40)
        self._cursor_timer.timeout.connect(self._update_cursor)
        self._cursor_timer.start()
        self._move_cursor = False
        self._title = qt.QtWidgets.QLabel()
        self._title.setObjectName("quickRenameTitle")
        self._field = TemplateField()
        self._field.setObjectName("renameField")
        self._field.set_words([(word, name) for name, words in self.library.categories().items() for word in words]
                              + [(word, "favorite") for word in self.library.favorites()])
        self._field.setMinimumWidth(300)
        self._preview = qt.QtWidgets.QLabel()
        self._preview.setObjectName("quickRenamePreview")
        self._preview.setTextFormat(qt.QtCore.Qt.TextFormat.RichText)
        hint = qt.QtWidgets.QLabel("Enter renames · Esc closes · ↑ ↓ names used last · drag the frame to move it")
        hint.setObjectName("quickRenameHint")
        column = qt.QtWidgets.QVBoxLayout(frame)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(6)
        for widget in (self._title, self._field, self._preview, hint):
            column.addWidget(widget)
        outer = qt.QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        self.setStyleSheet(StylesheetBuilder.build(UiResources().themeManager.current_theme))
        self._title.setText(f"Rename {len(self._nodes)} object{'s' if len(self._nodes) != 1 else ''}"
                            if self._nodes else "Nothing selected")
        if len(self._nodes) == 1:
            self._field.setText(self._nodes[0].name)
        elif self._recent:
            self._field.setText(self._recent[0])
        self._field.selectAll()
        self._field.textChanged.connect(self._update)
        self._field.returnPressed.connect(self._rename)
        self._update()

    @classmethod
    def open(cls) -> "QuickRename":
        """Shows it at the mouse pointer, a child of Maya's main window."""
        popup = cls(MayaWindowQuery.get_maya_main_window())
        popup.adjustSize()
        point = qt.QtGui.QCursor.pos() - qt.QtCore.QPoint(40, 20)
        screen = qt.QtGui.QGuiApplication.screenAt(qt.QtGui.QCursor.pos())
        if screen is not None:
            area = screen.availableGeometry()
            point.setX(max(area.left(), min(point.x(), area.right() - popup.width())))
            point.setY(max(area.top(), min(point.y(), area.bottom() - popup.height())))
        popup.move(point)
        popup.show()
        popup.activateWindow()
        popup._field.setFocus()
        return popup

    # ------------------------------------------------------------------ the names

    def _names(self) -> list:
        template = self._field.text().strip()
        settings = self._settings
        numbering = rules.Numbering(start=int(settings.get("start", 1) or 1), step=int(settings.get("step", 1) or 1),
                                    padding=int(settings.get("padding", 2) or 2),
                                    order=settings.get("order", rules.ORDER_SELECTION),
                                    end_last=bool(settings.get("end_last", False)))
        suffixes = dict(self._config["type_suffixes"]) or dict(rules.DEFAULT_TYPE_SUFFIXES)
        return rules.from_template(self._nodes, template, numbering, rules.Sides.from_settings(settings.get("sides")),
                                   suffixes)

    def _update(self, *_args) -> None:
        template = self._field.text().strip()
        if not self._nodes or not template:
            self._preview.setText("")
            self._preview.setVisible(False)
            self.adjustSize()
            return
        unknown = rules.unknown_tokens(template)
        if unknown:
            self._preview.setText(f"⚠ unknown token {html.escape(unknown[0])} — right click for the ones there are")
            self._preview.setVisible(True)
            return
        changes = rules.plan(self._nodes, self._names())
        lines = []
        for change in changes[:self.PREVIEW_LINES]:
            new = {"same": "unchanged", "locked": f"— {change.note}"}.get(change.state, change.new)
            mark = " ⚠" if change.state in ("clash", "error") else ""
            lines.append(f"{html.escape(change.node.name)} &nbsp;→&nbsp; <b>{html.escape(new)}</b>{mark}")
        if len(changes) > self.PREVIEW_LINES:
            lines.append(f"… and {len(changes) - self.PREVIEW_LINES} more")
        problems = [change for change in changes if change.state in ("clash", "error")]
        if problems:
            lines.append(f"⚠ {html.escape(problems[0].note)}")
        self._preview.setText("<br>".join(lines))
        self._preview.setVisible(True)
        self.adjustSize()

    def _rename(self) -> None:
        template = self._field.text().strip()
        if not template or not self._nodes or rules.unknown_tokens(template):
            if not template or not self._nodes:
                self.close()
            return
        changes = rules.plan(self._nodes, self._names())
        if not any(change.changes for change in changes):
            self.close()
            return
        done = scene.apply(changes)
        renamed = sum(1 for _change, given, error in done if given and not error)
        self.library.remember(template)
        self.close()
        try:
            from maya import cmds
            cmds.inViewMessage(assistMessage=f"Renamed {renamed}", position="topCenter", fade=True,
                               fadeStayTime=900)
        except (ImportError, RuntimeError):
            pass

    # moving: a press anywhere but the field (the labels and the frame pass it here) drags the popup

    def _over_frame(self, global_point) -> bool:
        if not self.frameGeometry().contains(global_point):
            return False
        local = self._field.mapFromGlobal(global_point)
        return not self._field.rect().contains(local)

    def _update_cursor(self) -> None:
        wanted = self._drag_from is not None or self._over_frame(qt.QtGui.QCursor.pos())
        if wanted != self._move_cursor:
            self._move_cursor = wanted
            shape = qt.QtCore.Qt.CursorShape.SizeAllCursor if wanted else qt.QtCore.Qt.CursorShape.ArrowCursor
            self._frame.setCursor(shape)
            self.setCursor(shape)

    def mousePressEvent(self, event) -> None:
        if event.button() == qt.QtCore.Qt.MouseButton.LeftButton and self._over_frame(event.globalPosition().toPoint()):
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & qt.QtCore.Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self._field.setFocus()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == qt.QtCore.Qt.Key.Key_Escape:
            self.close()
            return
        if key in (qt.QtCore.Qt.Key.Key_Up, qt.QtCore.Qt.Key.Key_Down) and self._recent:
            step = 1 if key == qt.QtCore.Qt.Key.Key_Down else -1
            self._recent_index = max(0, min(len(self._recent) - 1, self._recent_index + step))
            self._field.setText(self._recent[self._recent_index])
            return
        super().keyPressEvent(event)
