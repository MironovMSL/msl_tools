"""ArrowTooltip (ui/widgets/atoms/tooltips): where the bubble goes, how a key text becomes caps,
and the hook that takes a widget's ToolTip event in place of the plain tooltip."""
import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.widgets.atoms.tooltips import ArrowTooltip, attach_tooltip, detach_tooltip
    from msl_tools.msl.ui.widgets.atoms.tooltips import WindowTooltipRouter, install_tooltip_router
    from msl_tools.msl.ui.widgets.atoms.tooltips.arrow_tooltip import key_caps, place
    from msl_tools.msl.ui.widgets.atoms.tooltips.tooltip_router import split_text
except ImportError:  # no PySide6 in this Python
    qt = None

SCREEN = (0, 0, 1000, 800)


def _place(target, size=(200, 60), prefer="below"):
    return place(target, size, SCREEN, gap=3, tail=6, edge=6, tail_margin=13, prefer=prefer)


@unittest.skipIf(qt is None, "PySide6 is not installed")
class PlaceTest(unittest.TestCase):
    def test_below_and_centred_when_it_fits(self):
        x, y, side, tail_x = _place((400, 100, 40, 20))
        self.assertEqual(side, "below")
        self.assertEqual(y, 100 + 20 + 3 + 6)
        self.assertEqual(x, 420 - 100)
        self.assertEqual(tail_x, 100)

    def test_above_near_the_bottom_of_the_screen(self):
        x, y, side, _tail = _place((400, 760, 40, 20))
        self.assertEqual(side, "above")
        self.assertEqual(y, 760 - 3 - 6 - 60)

    def test_kept_inside_the_screen_with_the_tail_on_the_target(self):
        x, _y, _below, tail_x = _place((960, 100, 16, 20))
        self.assertEqual(x, 1000 - 6 - 200)
        self.assertEqual(tail_x, 968 - x)

    def test_the_tail_stays_off_the_corners(self):
        _x, _y, _below, tail_x = _place((0, 100, 4, 20))
        self.assertEqual(tail_x, 13)

    def test_beside_a_tile_and_to_its_left_at_the_screen_end(self):
        x, y, side, tail = _place((0, 300, 76, 50), prefer="right")
        self.assertEqual((side, x), ("right", 76 + 3 + 6))
        self.assertEqual(tail, 325 - y)
        x, _y, side, _tail = _place((900, 300, 76, 50), prefer="right")
        self.assertEqual((side, x), ("left", 900 - 3 - 6 - 200))

    def test_key_caps(self):
        self.assertEqual(key_caps("Ctrl+Shift+F"), ["Ctrl", "Shift", "F"])
        self.assertEqual(key_caps("Ctrl++"), ["Ctrl", "+"])
        self.assertEqual(key_caps("+"), ["+"])
        self.assertEqual(key_caps(" F2 "), ["F2"])
        self.assertEqual(key_caps(""), [])


@unittest.skipIf(qt is None, "PySide6 is not installed")
class HookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def setUp(self):
        self.window = qt.QtWidgets.QWidget()
        layout = qt.QtWidgets.QHBoxLayout(self.window)
        self.first = qt.QtWidgets.QPushButton("first")
        self.second = qt.QtWidgets.QPushButton("second")
        layout.addWidget(self.first)
        layout.addWidget(self.second)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def _help(self, widget) -> bool:
        event = qt.QtGui.QHelpEvent(qt.QtCore.QEvent.Type.ToolTip, qt.QtCore.QPoint(2, 2),
                                    widget.mapToGlobal(qt.QtCore.QPoint(2, 2)))
        return qt.QtWidgets.QApplication.sendEvent(widget, event)

    def test_the_tooltip_event_shows_ours_and_leave_hides_it(self):
        attach_tooltip(self.first, "Make unique", "Repeated names get numbers", "Ctrl+U")
        self.assertEqual(self.first.toolTip(), "Make unique\nRepeated names get numbers")
        self.assertTrue(self._help(self.first))
        tip = ArrowTooltip.shared(self.first, create=False)
        self.assertIsNotNone(tip)
        self.assertIs(tip.target(), self.first)
        self.assertGreater(tip.width(), 2 * tip.SHADOW)
        qt.QtWidgets.QApplication.sendEvent(self.first, qt.QtCore.QEvent(qt.QtCore.QEvent.Type.Leave))
        self.assertFalse(tip.isVisible())
        self.assertTrue(tip.is_warm())

    def test_one_tooltip_per_window_moves_to_the_next_widget(self):
        attach_tooltip(self.first, "One")
        attach_tooltip(self.second, "Two")
        self._help(self.first)
        tip = ArrowTooltip.shared(self.first, create=False)
        qt.QtWidgets.QApplication.sendEvent(self.first, qt.QtCore.QEvent(qt.QtCore.QEvent.Type.Leave))
        qt.QtWidgets.QApplication.sendEvent(self.second, qt.QtCore.QEvent(qt.QtCore.QEvent.Type.Enter))
        self.assertIs(ArrowTooltip.shared(self.second, create=False), tip)
        self.assertIs(tip.target(), self.second)  # warm: at once, no second wait

    def test_a_longer_description_makes_a_taller_bubble(self):
        tip = ArrowTooltip.shared(self.first)
        tip.show_for(self.first, "Title", "", animate=False)
        short = tip.height()
        tip.show_for(self.first, "Title", "word " * 80, animate=False)
        self.assertGreater(tip.height(), short)
        self.assertLessEqual(tip.width(), tip.MAX_TEXT + 2 * (tip.PAD_X + tip.SHADOW) + 2)

    def test_a_provider_is_asked_each_time_and_none_shows_nothing(self):
        answers = [None]
        attach_tooltip(self.first, provider=lambda: answers[0])
        self.assertTrue(self._help(self.first))  # the plain tooltip is still taken
        self.assertIsNone(ArrowTooltip.shared(self.first, create=False))
        answers[0] = ("Clicked", "3 times", "")
        self._help(self.first)
        self.assertTrue(ArrowTooltip.shared(self.first, create=False).isVisible())

    def test_detach_gives_the_event_back(self):
        attach_tooltip(self.first, "One")
        detach_tooltip(self.first)
        self.app.processEvents()
        tip = ArrowTooltip.shared(self.first, create=False)
        self._help(self.first)
        self.assertTrue(tip is None or not tip.isVisible())


@unittest.skipIf(qt is None, "PySide6 is not installed")
class SplitTextTest(unittest.TestCase):
    def test_a_short_line_is_a_title(self):
        self.assertEqual(split_text("Copy"), ("Copy", "", ""))

    def test_a_long_sentence_is_a_description(self):
        sentence = "Put back the copy of Maya's auto-load list stored before the last boosted launch"
        self.assertEqual(split_text(sentence), ("", sentence, ""))

    def test_several_lines_title_and_the_rest(self):
        self.assertEqual(split_text("Maya 2025\nAuto-loaded by: Dev\n  two"),
                         ("Maya 2025", "Auto-loaded by: Dev\n  two", ""))

    def test_a_key_in_brackets(self):
        self.assertEqual(split_text("Run this code in the selected Maya (Ctrl+Enter)"),
                         ("Run this code in the selected Maya", "", "Ctrl+Enter"))
        self.assertEqual(split_text("Find (Ctrl + F)\nin the list"), ("Find", "in the list", "Ctrl+F"))
        self.assertEqual(split_text("Frames (1-120)"), ("Frames (1-120)", "", ""))

    def test_a_sentence_is_never_a_title(self):
        self.assertEqual(split_text("Auto key when Maya starts."), ("", "Auto key when Maya starts.", ""))
        self.assertEqual(split_text("Problems: warnings.\nAll: everything."),
                         ("", "Problems: warnings.\nAll: everything.", ""))
        self.assertEqual(split_text("Copy selected to another environment..."), ("Copy selected to another environment...", "", ""))

    def test_empty(self):
        self.assertEqual(split_text("  "), ("", "", ""))


@unittest.skipIf(qt is None, "PySide6 is not installed")
class RouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])
        cls.router = install_tooltip_router(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.removeEventFilter(cls.router)
        cls.router.setParent(None)

    def setUp(self):
        self.window = qt.QtWidgets.QWidget()
        self.layout = qt.QtWidgets.QVBoxLayout(self.window)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()

    def _show(self):
        self.window.show()
        self.app.processEvents()

    def _help(self, widget, pos=qt.QtCore.QPoint(3, 3) if qt else None) -> bool:
        event = qt.QtGui.QHelpEvent(qt.QtCore.QEvent.Type.ToolTip, pos, widget.mapToGlobal(pos))
        return qt.QtWidgets.QApplication.sendEvent(widget, event)

    def _tip(self):
        return self.window.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME)

    def test_a_plain_tooltip_becomes_ours(self):
        button = qt.QtWidgets.QPushButton("x")
        button.setToolTip("Run this code in the selected Maya (Ctrl+Enter)")
        self.layout.addWidget(button)
        self._show()
        self.assertTrue(self._help(button))
        tip = self._tip()
        self.assertTrue(tip.isVisible())
        self.assertEqual((tip._title, tip._caps), ("Run this code in the selected Maya", ["Ctrl", "Enter"]))
        qt.QtWidgets.QApplication.sendEvent(button, qt.QtCore.QEvent(qt.QtCore.QEvent.Type.Leave))
        self.assertFalse(tip.isVisible())

    def test_a_widget_without_one_passes_it_to_its_parent(self):
        holder = qt.QtWidgets.QFrame()
        holder.setToolTip("The holder")
        label = qt.QtWidgets.QLabel("inside", holder)
        self.layout.addWidget(holder)
        self._show()
        self._help(label)
        self.assertEqual(self._tip()._title, "The holder")

    def test_a_row_of_a_list(self):
        view = qt.QtWidgets.QListWidget()
        item = qt.QtWidgets.QListWidgetItem("row")
        item.setToolTip("Row tip")
        view.addItem(item)
        self.layout.addWidget(view)
        self._show()
        point = view.visualItemRect(item).center()
        self.assertTrue(self._help(view.viewport(), point))
        self.assertEqual(self._tip()._title, "Row tip")

    def test_a_tab(self):
        tabs = qt.QtWidgets.QTabWidget()
        tabs.addTab(qt.QtWidgets.QWidget(), "Render")
        tabs.setTabToolTip(0, "Scenes rendered one after another")
        self.layout.addWidget(tabs)
        self._show()
        bar = tabs.tabBar()
        self._help(bar, bar.tabRect(0).center())
        self.assertEqual(self._tip()._title, "Scenes rendered one after another")

    def test_a_hooked_widget_keeps_its_own(self):
        button = qt.QtWidgets.QPushButton("x")
        attach_tooltip(button, "Own title", "own text")
        self.layout.addWidget(button)
        self._show()
        self._help(button)
        self.assertEqual(self._tip()._title, "Own title")

    def test_a_message_goes_away_by_itself(self):
        self._show()
        tip = ArrowTooltip.shared(self.window)
        tip.show_message("Copied 3 to Stable", seconds=0.05)
        self.assertTrue(tip.isVisible())
        qt.QtTest.QTest.qWait(150) if hasattr(qt, "QtTest") else self._wait(0.15)
        self.assertFalse(tip.isVisible())

    def _wait(self, seconds):
        import time
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)


@unittest.skipIf(qt is None, "PySide6 is not installed")
class WindowRouterTest(unittest.TestCase):
    """The per-window form (our windows inside Maya): the window and what lives under it get
    our bubble, a window of someone else's (Maya's) keeps the plain tooltip."""

    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])
        # another test class may have left the application-wide router: none may be on here
        for child in cls.app.children():
            if type(child).__name__ == "TooltipRouter":
                cls.app.removeEventFilter(child)

    def setUp(self):
        self.ours = qt.QtWidgets.QWidget()
        self.layout = qt.QtWidgets.QVBoxLayout(self.ours)
        self.router = install_tooltip_router(self.ours)
        self.theirs = qt.QtWidgets.QWidget()
        qt.QtWidgets.QVBoxLayout(self.theirs)

    def tearDown(self):
        for window in (self.ours, self.theirs):
            window.close()
            window.deleteLater()
        self.app.processEvents()

    def _help(self, widget, pos=qt.QtCore.QPoint(3, 3) if qt else None) -> bool:
        event = qt.QtGui.QHelpEvent(qt.QtCore.QEvent.Type.ToolTip, pos, widget.mapToGlobal(pos))
        return qt.QtWidgets.QApplication.sendEvent(widget, event)

    def _show(self):
        self.ours.show()
        self.theirs.show()
        self.app.processEvents()

    def test_once_per_window_and_a_window_router(self):
        self.assertIs(install_tooltip_router(self.ours), self.router)
        self.assertIsInstance(self.router, WindowTooltipRouter)
        self.assertNotIn(self.router, [child for child in self.app.children()])

    def test_a_widget_added_later_is_ours_and_a_foreign_window_is_not(self):
        holder = qt.QtWidgets.QFrame()          # built apart, with a child, then put in
        button = qt.QtWidgets.QPushButton("x", holder)
        button.setToolTip("Make unique (Ctrl+U)")
        self.layout.addWidget(holder)
        foreign = qt.QtWidgets.QPushButton("y")
        foreign.setToolTip("Maya's own")
        self.theirs.layout().addWidget(foreign)
        self._show()
        self.assertTrue(self._help(button))
        tip = self.ours.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME)
        self.assertEqual((tip._title, tip._caps), ("Make unique", ["Ctrl", "U"]))
        self._help(foreign)
        self.assertIsNone(self.theirs.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME))

    def test_a_menu_of_the_window_and_a_row_of_its_list(self):
        view = qt.QtWidgets.QListWidget()
        item = qt.QtWidgets.QListWidgetItem("row")
        item.setToolTip("Row tip")
        view.addItem(item)
        self.layout.addWidget(view)
        menu = qt.QtWidgets.QMenu(view)          # made with a parent: in the window's tree
        menu.setToolTipsVisible(True)
        action = menu.addAction("Lock")
        action.setToolTip("Lock it\nNothing can rename it then.")
        self._show()
        self.assertTrue(self._help(view.viewport(), view.visualItemRect(item).center()))
        self.assertEqual(self.ours.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME)._title, "Row tip")
        menu.popup(qt.QtCore.QPoint(10, 10))
        self.app.processEvents()
        self.assertTrue(self._help(menu, menu.actionGeometry(action).center()))
        tip = menu.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME)
        self.assertEqual((tip._title, tip._text), ("Lock it", "Nothing can rename it then."))
        menu.close()

    def test_a_hooked_widget_and_an_empty_one(self):
        hooked = qt.QtWidgets.QPushButton("h")
        attach_tooltip(hooked, "Own title", "own text")
        plain = qt.QtWidgets.QPushButton("p")
        self.layout.addWidget(hooked)
        self.layout.addWidget(plain)
        self._show()
        self._help(hooked)
        self.assertEqual(self.ours.findChild(ArrowTooltip, ArrowTooltip.OBJECT_NAME)._title, "Own title")
        self.assertFalse(self.router.show(plain, qt.QtCore.QPoint(1, 1)))


if __name__ == "__main__":
    unittest.main()
