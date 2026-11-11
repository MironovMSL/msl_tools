"""Plug-ins a Maya's scene asks for and lacks, in the Sessions tab: the count from the link, the menu entry,
the line above the log (missing-plugin lines kept as warnings, not unread errors), and the two requests
(scene_plugins -> the question -> scene_plugins_clean). A fake Maya on a PRIVATE port and token."""
import os
import unittest
from unittest import mock

from msl_tools.msl.core.link import protocol

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.maya_link.server import MayaLinkServer
    from msl_tools.msl.tools.desktop.maya_gate import sessions_control
    from msl_tools.msl.tools.desktop.maya_gate.sessions_tab import SessionsTab
    from tests.ui.test_maya_link_auth import TOKEN, FakeMaya, _free_port, _Qt
except ImportError:  # no PySide6 in this Python
    qt = None
    _Qt = unittest.TestCase

RIG = "E:/branches/Animation/Animal_Animation/Project/D_Shiba_Inu/rigs/Rig_Shiba_01.ma"
LINES = [[protocol.LOG_ERROR, f'file: {RIG} line {11 + index}: RuntimeError: file <maya console> line 1: '
          f'Plug-in, "{name}", was not found on MAYA_PLUG_IN_PATH.']
         for index, name in enumerate(["evoattrib", "ByronsPolyTools", "TurtleForMaya2009"])]


@unittest.skipIf(qt is None, "PySide6 is not installed")
class ScenePlugins(_Qt):
    def setUp(self):
        self.server = MayaLinkServer()
        self.assertTrue(self.server.listen(_free_port(), TOKEN))
        self.server._ping_timer.stop()
        self.addCleanup(self.server.close)
        self.tab = SessionsTab(self.server)
        self.addCleanup(self.tab.deleteLater)
        self.tab.resize(700, 600)
        self.maya = FakeMaya(self.server.port())
        self.addCleanup(self.maya.sock.close)
        nonce = protocol.new_nonce()
        self.maya.send(protocol.event(protocol.HELLO, pid=4242, version="2024", nonce=nonce,
                                      scene="E:/shots/sh010.ma", plugins=3))
        self.assertTrue(self.pump(lambda: (self.maya.poll(), self.maya.received)[1]))
        welcome = self.maya.received.pop(0)["data"]
        self.maya.send(protocol.event(protocol.PROOF, proof=protocol.maya_proof(TOKEN, nonce, welcome["nonce"])))
        self.assertTrue(self.pump(lambda: len(self.server.sessions()) == 1))
        self.session = self.server.sessions()[0]
        self.tab.show()
        self.tab.refresh()

    def request(self, name: str) -> dict:
        def arrived():
            self.maya.poll()
            return any(message.get("name") == name for message in self.maya.received)
        self.assertTrue(self.pump(arrived), f"no {name}")
        message = next(message for message in self.maya.received if message.get("name") == name)
        self.maya.received.remove(message)
        return message

    def reply(self, message: dict, data: dict) -> None:
        self.maya.send({"type": protocol.REPLY, "id": message["id"], "success": True, "data": data})

    def test_the_count_and_the_menu(self):
        self.assertEqual(self.session.plugins, 3)
        self.tab._on_row_menu(self.session.session_id)
        texts = [action.text() for action in self.tab._row_menu.actions()]
        self.assertIn("Clean unknown plug-ins… (3)", texts)
        self.tab._row_menu.close()
        self.maya.send(protocol.event(protocol.SCENE, scene="E:/shots/sh010.ma", modified=True, plugins=0))
        self.assertTrue(self.pump(lambda: self.server.sessions()[0].plugins == 0))
        self.tab._on_row_menu(self.session.session_id)
        self.assertFalse(any("unknown plug-ins" in action.text() for action in self.tab._row_menu.actions()))
        self.tab._row_menu.close()

    def test_missing_plugin_lines_are_warnings_and_one_line_above_the_log(self):
        self.tab.hide()                                      # off screen: errors would count as unread
        self.maya.send(protocol.event(protocol.LOG, entries=LINES + [[protocol.LOG_ERROR, "a real error"]]))
        self.assertTrue(self.pump(lambda: self.tab._missing.get(4242)))
        self.assertTrue(self.pump(lambda: self.server.unread_errors() == 1))
        self.assertEqual(self.tab._problems[4242], [1, 3])
        self.tab.show()
        self.tab._select_session(self.session.session_id)
        self.assertTrue(self.tab._plugins_hint.isVisible())
        text = self.tab._plugins_hint_text.text()
        self.assertIn("3 plug-ins missing, asked for by Rig_Shiba_01.ma", text)
        self.assertTrue(self.tab._hint_clean.isVisible())
        self.assertTrue(self.tab._hint_fix.isVisible())
        self.assertFalse(self.tab._hint_arnold.isVisible())
        opened = []
        with mock.patch.object(SessionsTab, "_fix_in_paths", lambda _self, files, find=True: opened.append((files, find))):
            self.tab._hint_fix.click()
        self.assertEqual(opened, [([RIG], False)])
        self.tab._hint_close.click()
        self.assertFalse(self.tab._plugins_hint.isVisible())

    def test_arnold_left_out_by_boost(self):
        self.session.skipped = ["mtoa", "bifrostGraph"]
        self.maya.send(protocol.event(protocol.LOG, entries=[[protocol.LOG_WARNING,
                                                              "The MtoA plug-in needed for this scene is not loaded."]]))
        self.assertTrue(self.pump(lambda: 4242 in self.tab._arnold_wanted))
        self.tab._select_session(self.session.session_id)
        self.assertTrue(self.tab._hint_arnold.isVisible())
        self.tab._hint_arnold.click()
        load = self.request(protocol.LOAD_PLUGINS)
        self.assertEqual(load["data"]["names"], ["mtoa"])

    def test_the_question_and_the_clean(self):
        asked = []

        def answer(_parent, title, message, details, choices, kind="question", **_extra):
            asked.append((title, message, details, [key for key, _text in choices], kind))
            return "clean"

        with mock.patch.object(sessions_control.ConfirmDialog, "ask", staticmethod(answer)):
            self.tab._on_scene_plugins(self.session.session_id)
            state = self.request(protocol.SCENE_PLUGINS)
            self.reply(state, {"plugins": ["ByronsPolyTools"], "nodes": [{"plugin": "TurtleForMaya2009", "count": 3}],
                               "referenced": [{"file": RIG, "plugins": ["evoattrib"]}]})
            clean = self.request(protocol.SCENE_PLUGINS_CLEAN)
        title, message, details, keys, kind = asked[0]
        self.assertEqual(keys, ["clean", "fix", "cancel"])
        self.assertEqual(kind, "danger")                     # unknown nodes: what they held is lost
        self.assertIn("delete 3 unknown nodes", message)
        self.assertIn("Rig_Shiba_01.ma: evoattrib", details)
        self.reply(clean, {"nodes": 3, "plugins": ["ByronsPolyTools"], "refused": [], "referenced": [],
                           "text": "Clean unknown plug-ins: 3 unknown nodes deleted, 1 plug-in dropped - save the scene"})
        self.assertTrue(self.pump(lambda: "3 unknown nodes deleted" in self.tab._message_label.text()))


if __name__ == "__main__":
    unittest.main()
