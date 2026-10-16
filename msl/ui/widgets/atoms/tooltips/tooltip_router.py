# ui/widgets/atoms/tooltips/tooltip_router.py
"""Every tooltip of an application as an ArrowTooltip, without touching the widgets.

    install_tooltip_router(app)     # run_hub: the hub owns its QApplication
    install_tooltip_router(window)  # a window of ours inside Maya: that window only

One event filter on the QApplication takes the ToolTip events Qt sends after the hover delay
and shows the bubble with the text the widget already carries — `setToolTip()` stays the way
to give a widget a tooltip. Covered: plain widgets (Qt's own rule kept: a widget without a
tooltip passes the event on to its parent), rows / cells of item views (ToolTipRole), tabs
(`setTabToolTip`) and menu items (`setToolTipsVisible(True)` + `QAction.setToolTip`). The text
is split by `split_text()`: a short first line is the bold title, the rest the description, and
a key in brackets at the end of the first line ("Run (Ctrl+Enter)") becomes key caps.

Widgets hooked with attach_tooltip() keep their own content (the router steps aside).

Inside Maya the QApplication is Maya's: a filter on it would see (and slow) every event of
Maya and turn Maya's own tooltips into ours. There the router is given a WINDOW
(`WindowTooltipRouter`): it filters that window and each widget under it - in the QObject
tree, so its menus, combo lists and completer popups (made with a parent) are covered, while
Maya's widgets never reach it. Widgets added later are taken as they come (ChildAdded).
"""
import re
from typing import Optional

import msl_tools.msl.ui.qt_bindings as qt

from .arrow_tooltip import ArrowTooltip, _hook_of

TITLE_MAX = 48      # a lone line up to this long reads as a title
HEAD_MAX = 72       # the first of several lines up to this long is the title

_KEY = re.compile(r"\s*\(((?:Ctrl|Shift|Alt|Win|Esc|Enter|Return|Tab|Space|Del|Delete|Backspace|Home|End|"
                  r"PgUp|PgDn|F\d{1,2})(?:\s*\+\s*[^\s()+]+)*)\)\s*$")
_RICH = re.compile(r"<(?:html|qt|p|br|b|i|u|span|a|div|table|font|code)\b[^>]*>", re.IGNORECASE)


def split_text(text: str) -> tuple[str, str, str]:
    """A plain tooltip text -> (title, description, key).

    "Copy" -> ("Copy", "", ""); one long sentence -> ("", sentence, ""); several lines with a
    short first one -> (first, the rest, ""); "Run this code (Ctrl+Enter)" -> ("Run this code",
    "", "Ctrl+Enter"). A first line that ends like a sentence ("." ";" ",") is never a title:
    "Auto key when Maya starts." and "Problems: warnings and errors.\\nAll: ..." are text."""
    lines = [line.rstrip() for line in (text or "").strip().splitlines()]
    if not lines:
        return "", "", ""
    first, rest = lines[0].strip(), "\n".join(lines[1:]).strip()
    key = ""
    found = _KEY.search(first)
    if found:
        key = re.sub(r"\s*\+\s*", "+", found.group(1))
        first = first[:found.start()].rstrip()
    sentence = first.endswith((".", ";", ",")) and not first.endswith("...")  # reads on: not a title
    if not rest:
        if not sentence and (len(first) <= TITLE_MAX or key and len(first) <= HEAD_MAX):
            return first, "", key
        return "", first, key
    if len(first) <= HEAD_MAX and not sentence:
        return first, rest, key
    return "", (first + "\n" + rest).strip(), key


def _plain(text: str) -> str:
    """A rich-text tooltip as plain text (the bubble draws plain text)."""
    if text and _RICH.search(text):
        return qt.QtGui.QTextDocumentFragment.fromHtml(text).toPlainText()
    return text or ""


class TooltipRouter(qt.QtCore.QObject):
    """The application's event filter (see the module's docstring)."""

    HIDING = (qt.QtCore.QEvent.Type.Leave, qt.QtCore.QEvent.Type.MouseButtonPress,
              qt.QtCore.QEvent.Type.MouseButtonDblClick, qt.QtCore.QEvent.Type.Wheel,
              qt.QtCore.QEvent.Type.KeyPress, qt.QtCore.QEvent.Type.Hide,
              qt.QtCore.QEvent.Type.WindowDeactivate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target: Optional[qt.QtWidgets.QWidget] = None
        self._rect = qt.QtCore.QRect()
        self._text = ""

    # --- what a widget would show at a point ---------------------------------------

    @staticmethod
    def find(widget: qt.QtWidgets.QWidget, pos: qt.QtCore.QPoint):
        """(text, global rect to point at, side) for a ToolTip event at `pos` (widget
        coordinates), or None when this widget has nothing to say (Qt then asks its parent)."""
        view = widget.parentWidget()
        if isinstance(view, qt.QtWidgets.QAbstractItemView) and widget is view.viewport():
            index = view.indexAt(pos)
            text = index.data(qt.QtCore.Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
            if not text:
                return None
            rect = view.visualRect(index)
            return str(text), qt.QtCore.QRect(widget.mapToGlobal(rect.topLeft()), rect.size()), "below"
        if isinstance(widget, qt.QtWidgets.QTabBar):
            index = widget.tabAt(pos)
            text = widget.tabToolTip(index) if index >= 0 else ""
            if text:
                rect = widget.tabRect(index)
                return text, qt.QtCore.QRect(widget.mapToGlobal(rect.topLeft()), rect.size()), "below"
        if isinstance(widget, qt.QtWidgets.QMenu):
            action = widget.actionAt(pos)
            if action is None or not widget.toolTipsVisible():
                return None
            text = action.toolTip()
            if not text or text == action.text().replace("&", ""):  # Qt's default = the item's text
                return None
            rect = widget.actionGeometry(action)
            return text, qt.QtCore.QRect(widget.mapToGlobal(rect.topLeft()), rect.size()), "right"
        text = widget.toolTip()
        if not text:
            return None
        return text, qt.QtCore.QRect(widget.mapToGlobal(qt.QtCore.QPoint(0, 0)), widget.size()), "below"

    # --- showing / hiding -------------------------------------------------------------

    def show(self, widget: qt.QtWidgets.QWidget, pos: qt.QtCore.QPoint, animate: bool = True) -> bool:
        """Shows what `widget` has at `pos`; False if it has nothing (the event goes on)."""
        found = self.find(widget, pos)
        if found is None:
            return False
        text, rect, side = found
        title, description, key = split_text(_plain(text))
        if not (title or description):
            return False
        tip = ArrowTooltip.shared(widget)
        tip.show_at(rect, title, description, key, animate=animate and not tip.is_warm(), side=side)
        self._set_target(widget, rect)
        self._text = text
        return True

    def dismiss(self) -> None:
        target, self._target = self._target, None
        if target is not None:
            try:
                target.destroyed.disconnect(self._on_target_gone)
            except (RuntimeError, TypeError):
                pass
            tip = ArrowTooltip.shared(target, create=False)
            if tip is not None:
                tip.dismiss()

    def _set_target(self, widget: qt.QtWidgets.QWidget, rect: qt.QtCore.QRect) -> None:
        if widget is not self._target:
            self.dismiss_target_only()
            widget.destroyed.connect(self._on_target_gone)
        self._target, self._rect = widget, rect

    def dismiss_target_only(self) -> None:
        """Forgets the old target without hiding: the shared bubble moves to the new one."""
        if self._target is not None:
            try:
                self._target.destroyed.disconnect(self._on_target_gone)
            except (RuntimeError, TypeError):
                pass
            self._target = None

    def _on_target_gone(self, *_args) -> None:
        self._target = None

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == qt.QtCore.QEvent.Type.ToolTip:
            if not isinstance(watched, qt.QtWidgets.QWidget) or isinstance(watched, ArrowTooltip) \
                    or _hook_of(watched) is not None:
                return False
            try:
                return self.show(watched, event.pos())
            except Exception:  # never lose a tooltip to a bug here: Qt's own one shows instead
                return False
        if kind == qt.QtCore.QEvent.Type.Enter and isinstance(watched, qt.QtWidgets.QWidget):
            # Warm: right after one bubble, a widget with a tooltip of its own shows at once.
            if watched.toolTip() and _hook_of(watched) is None and not isinstance(watched, ArrowTooltip):
                tip = ArrowTooltip.shared(watched, create=False)
                if tip is not None and tip.is_warm():
                    self.show(watched, qt.QtCore.QPoint(1, 1), animate=False)
            return False
        if watched is self._target and self._target is not None:
            if kind in self.HIDING:
                self.dismiss()
            elif kind == qt.QtCore.QEvent.Type.MouseMove:
                # Another row / tab / menu item, or a widget whose tooltip follows the pointer
                # (BarStrip): its own tooltip comes after the delay.
                found = None
                if self._rect.contains(qt.QtGui.QCursor.pos()):
                    found = self.find(self._target, event.position().toPoint())
                if found is None or found[0] != self._text:
                    self.dismiss()
        return False


class WindowTooltipRouter(TooltipRouter):
    """The router of ONE window and what lives under it (see the module's docstring): an event
    filter on every widget of the window's QObject tree, never on the QApplication."""

    OBJECT_NAME = "windowTooltipRouter"

    def __init__(self, window: qt.QtWidgets.QWidget):
        super().__init__(window)
        self.setObjectName(self.OBJECT_NAME)
        self.watch(window)

    def watch(self, widget: qt.QtWidgets.QWidget) -> None:
        """Filters `widget` and every widget under it (again is harmless: Qt keeps one)."""
        for each in [widget] + widget.findChildren(qt.QtWidgets.QWidget):
            if not isinstance(each, ArrowTooltip):
                each.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == qt.QtCore.QEvent.Type.ChildAdded:
            try:
                child = event.child()
                if child is not None and child.isWidgetType() and not isinstance(child, ArrowTooltip):
                    self.watch(child)
            except RuntimeError:  # gone already
                pass
            return False
        return super().eventFilter(watched, event)


def install_tooltip_router(target) -> TooltipRouter:
    """Routes the tooltips of `target` through ArrowTooltip (once; returns the router).

    A QApplication (the hub's own): every tooltip of the application. A widget (a window of
    ours inside Maya): that window and what lives under it only - never pass Maya's
    QApplication there."""
    direct = qt.QtCore.Qt.FindChildOption.FindDirectChildrenOnly
    if isinstance(target, qt.QtWidgets.QApplication):
        router = next((child for child in target.children() if type(child) is TooltipRouter), None)
        if router is None:
            router = TooltipRouter(target)
            target.installEventFilter(router)
        return router
    router = target.findChild(WindowTooltipRouter, WindowTooltipRouter.OBJECT_NAME, direct)
    return router if router is not None else WindowTooltipRouter(target)
