"""The assistant's channel into the hub (core/link/assistant.py + ui/maya_link/assistant_server.py):
only a client that knows the channel's own token is served, and only the fixed requests.

Both servers listen on PRIVATE ports with private tokens — never ensure_listening(): a real
Maya (or a real assistant) on this machine would join the test.
"""
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

from msl_tools.msl.core.link import assistant
from msl_tools.msl.core.link import protocol

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import msl_tools.msl.ui.qt_bindings as qt
    from msl_tools.msl.ui.maya_link.assistant_server import AssistantServer
    from msl_tools.msl.ui.maya_link.server import MayaLinkServer
except ImportError:  # no PySide6 in this Python
    qt = None

MAYA_TOKEN = "f00d" * 8
TOKEN = "cafe" * 8


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LogBookTest(unittest.TestCase):
    def test_reading_again_gives_only_what_came_since(self):
        book = assistant.LogBook()
        book.add(7, [("error", "a"), ("warning", "b")])
        entries, last = book.read(7)
        self.assertEqual(([entry["text"] for entry in entries], last), (["a", "b"], 2))
        book.add(7, [("info", "c")])
        entries, last = book.read(7, after=last)
        self.assertEqual(([entry["text"] for entry in entries], last), (["c"], 3))
        self.assertEqual(book.read(7, after=last), ([], 3))

    def test_levels_limit_and_counts(self):
        book = assistant.LogBook()
        book.add(7, [("error", "e1"), ("info", "i"), ("warning", "w"), ("error", "e2")])
        self.assertEqual([entry["text"] for entry in book.read(7, levels=["error"])[0]], ["e1", "e2"])
        self.assertEqual([entry["text"] for entry in book.read(7, limit=2)[0]], ["w", "e2"])  # the newest
        self.assertEqual(book.problems(7), (2, 1))
        self.assertEqual((book.knows(8), book.read(8)), (False, ([], 0)))

    def test_only_the_last_entries_and_mayas_are_kept(self):
        book = assistant.LogBook()
        book.add(1, [("info", str(number)) for number in range(book.PER_MAYA + 5)])
        entries, last = book.read(1, limit=assistant.MAX_READ)
        self.assertEqual((entries[-1]["seq"], last), (book.PER_MAYA + 5, book.PER_MAYA + 5))
        for pid in range(2, book.MAYAS + 2):
            book.add(pid, [("info", "x")])
        self.assertFalse(book.knows(1))  # the one written to longest ago went

    def test_address_of_a_missing_or_broken_file(self):
        self.assertEqual(assistant.read_address(os.path.join(os.path.dirname(__file__), "no_such.json")),
                         (0, "", False))


@unittest.skipIf(qt is None, "PySide6 is not installed")
class Channel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([])

    def setUp(self):
        self.link = MayaLinkServer()
        self.assertTrue(self.link.listen(_free_port(), MAYA_TOKEN))
        self.link._ping_timer.stop()
        self.addCleanup(self.link.close)
        self.server = AssistantServer(self.link)
        self.assertTrue(self.server.listen(_free_port(), TOKEN))
        self.addCleanup(self.server.close)

    def pump(self, until, seconds=3.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if until():
                return True
            time.sleep(0.005)
        return until()

    def ask(self, action, meanwhile=lambda: None):
        """Runs `action` (blocking client calls) on a thread while the hub's event loop turns
        (and `meanwhile` is called: a fake Maya answering)."""
        outcome = {}

        def work():
            try:
                outcome["value"] = action()
            except Exception as error:  # handed to the test's thread
                outcome["error"] = error

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.assertTrue(self.pump(lambda: (meanwhile(), not thread.is_alive())[1], seconds=8.0),
                        "the client never finished")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]

    def client(self, token=TOKEN) -> "assistant.AssistantClient":
        client = assistant.AssistantClient(self.server.port(), token, timeout=3.0)
        self.addCleanup(client.close)
        return client

    def join_maya(self, pid=4242) -> socket.socket:
        """A Maya on the Maya link (the older hello with the token: one message)."""
        maya = socket.create_connection(("127.0.0.1", self.link.port()), timeout=3)
        self.addCleanup(maya.close)
        before = len(self.link.sessions())
        maya.sendall(protocol.encode(protocol.event(protocol.HELLO, pid=pid, version="2025", environment="Dev",
                                                    scene="C:/shots/a.ma", console=True, token=MAYA_TOKEN)))
        self.assertTrue(self.pump(lambda: len(self.link.sessions()) == before + 1))
        return maya

    def test_sessions_and_their_log(self):
        maya = self.join_maya()
        maya.sendall(protocol.encode(protocol.event(protocol.LOG, entries=[["error", "boom"], ["warning", "hm"]])))
        self.assertTrue(self.pump(lambda: self.server.log.knows(4242)))
        client = self.client()
        sessions = self.ask(lambda: client.request(assistant.SESSIONS))["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual((sessions[0]["pid"], sessions[0]["environment"], sessions[0]["scene"],
                          sessions[0]["console"], sessions[0]["errors"], sessions[0]["warnings"]),
                         (4242, "Dev", "C:/shots/a.ma", True, 1, 1))
        self.assertEqual(self.server.clients(), 1)
        log = self.ask(lambda: client.request(assistant.READ_LOG, pid=4242))
        self.assertEqual(([entry["text"] for entry in log["entries"]], log["last"], log["known"]),
                         (["boom", "hm"], 2, True))
        log = self.ask(lambda: client.request(assistant.READ_LOG, pid=4242, after=log["last"]))
        self.assertEqual(log["entries"], [])
        self.assertFalse(self.ask(lambda: client.request(assistant.READ_LOG, pid=1))["known"])

    def test_the_maya_token_does_not_open_it(self):
        client = self.client(token=MAYA_TOKEN)
        with self.assertRaises(assistant.AssistantError):
            self.ask(lambda: client.request(assistant.SESSIONS))
        self.assertEqual(self.server.clients(), 0)

    def test_an_unknown_request_is_refused(self):
        client = self.client()
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: client.request("quit_maya", pid=1))
        self.assertIn("quit_maya", str(raised.exception))

    def test_code_is_refused_while_the_user_has_not_allowed_it(self):
        maya = self.join_maya()
        maya.setblocking(False)
        client = self.client()
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="1 + 1"))
        self.assertIn("switched off", str(raised.exception))
        self.pump(lambda: False, seconds=0.2)
        with self.assertRaises(BlockingIOError):
            maya.recv(65536)   # nothing was passed on to Maya

    def test_a_request_without_the_handshake_is_dropped(self):
        raw = socket.create_connection(("127.0.0.1", self.server.port()), timeout=3)
        self.addCleanup(raw.close)
        raw.sendall(protocol.encode(protocol.request(assistant.SESSIONS, 1)))
        raw.settimeout(0.05)

        def closed() -> bool:
            try:
                return raw.recv(1024) == b""
            except socket.timeout:
                return False
            except OSError:
                return True

        self.assertTrue(self.pump(closed))

    def test_a_hello_that_is_not_an_assistants_is_dropped(self):
        raw = socket.create_connection(("127.0.0.1", self.server.port()), timeout=3)
        self.addCleanup(raw.close)
        raw.sendall(protocol.encode(protocol.event(protocol.HELLO, pid=1, nonce=protocol.new_nonce())))
        raw.settimeout(0.05)

        def closed() -> bool:
            try:
                return raw.recv(1024) == b""
            except socket.timeout:
                return False
            except OSError:
                return True

        self.assertTrue(self.pump(closed))

    def test_the_client_finds_the_hub_again_after_it_was_away(self):
        client = self.client()
        port = self.server.port()
        self.assertEqual(self.ask(lambda: client.request(assistant.SESSIONS))["sessions"], [])
        self.server.close()
        self.pump(lambda: False, seconds=0.1)
        self.assertTrue(self.server.listen(port, TOKEN))
        self.assertEqual(self.ask(lambda: client.request(assistant.SESSIONS))["sessions"], [])

    def answering(self, maya: socket.socket, seen: list, **result):
        """A `meanwhile` for ask(): the fake Maya answers each RUN_PYTHON it gets with `result`."""
        maya.setblocking(False)
        decoder = protocol.FrameDecoder()

        def step():
            try:
                data = maya.recv(65536)
            except (BlockingIOError, InterruptedError):
                return
            for message in decoder.feed(data):
                if message.get("name") == protocol.RUN_PYTHON:
                    seen.append(message["data"]["code"])
                    maya.sendall(protocol.encode(protocol.reply(message["id"], **result)))
        return step

    def test_allowed_code_goes_to_maya_once_and_its_answer_comes_back(self):
        maya = self.join_maya()
        self.server._code_allowed = True   # the user's switch (set_code_allowed would write the hub's config)
        started, finished, seen = [], [], []
        self.server.code_started.connect(lambda pid, code: started.append((pid, code)))
        self.server.code_finished.connect(lambda pid, reply: finished.append((pid, reply["success"])))
        client = self.client()
        answer = self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="1 + 1"),
                          self.answering(maya, seen, output="hi\n", result="2", traceback=""))
        self.assertEqual(answer, {"output": "hi\n", "result": "2", "traceback": ""})
        self.assertEqual((seen, started, finished), (["1 + 1"], [(4242, "1 + 1")], [(4242, True)]))
        self.assertEqual(self.server.running(), set())
        self.assertTrue(self.ask(lambda: client.request(assistant.SESSIONS))["sessions"][0]["runs_code"])

    def test_code_that_saves_is_put_to_the_user_first(self):
        maya = self.join_maya()
        self.server._code_allowed = True
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.server.set_journal(folder)
        asked, verdict, seen = [], [False], []

        def confirm(session, code, reasons, answer):
            asked.append((session.pid, reasons))
            answer(verdict[0])

        self.server.set_confirmer(confirm)
        client = self.client()
        answering = self.answering(maya, seen, output="", result="None", traceback="")
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242,
                                            code="cmds.file(save=True)"), answering)
        self.assertIn("did not allow", str(raised.exception))
        self.assertIn("saves the scene", str(raised.exception))
        self.assertEqual((asked, seen, self.server.running()), ([(4242, ["saves the scene"])], [], set()))
        verdict[0] = True
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="cmds.file(save=True)"),
                 answering)
        self.assertEqual(seen, ["cmds.file(save=True)"])
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="cmds.ls()"), answering)
        self.assertEqual(len(asked), 2)   # plain code is not asked about
        self.server.set_confirmer(confirm)
        self.server._confirms = False     # the user switched the questions off
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="cmds.file(save=True)"),
                 answering)
        self.assertEqual(len(asked), 2)
        with open(self.server.journal_file(), encoding="utf-8") as handle:
            journal = handle.read()
        self.assertIn("the user REFUSED code that saves the scene", journal)
        self.assertIn("the user ALLOWED code that saves the scene", journal)
        self.assertEqual(journal.count("  ran Python  |  Maya 2025 \u00b7 Dev \u00b7 pid 4242 \u00b7 C:/shots/a.ma"), 3)
        self.assertIn("cmds.ls()\n--- outcome\n# Result: None", journal)

    def test_opening_scenes_may_go_without_the_question(self):
        maya = self.join_maya()
        self.server._code_allowed = True
        asked, seen = [], []
        self.server.set_confirmer(lambda session, code, reasons, answer: (asked.append(reasons), answer(True)))
        client = self.client()
        answering = self.answering(maya, seen, output="", result="None", traceback="")
        new_scene = "cmds.file(new=True, force=True)"
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code=new_scene), answering)
        self.assertEqual(len(asked), 1)                            # asked, as always
        self.server.set_scenes_free(True)                          # "open / new scenes without asking"
        self.assertTrue(self.server.scenes_free())
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code=new_scene), answering)
        self.assertEqual(len(asked), 1)                            # went without the question
        self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242,
                                        code=new_scene + "\ncmds.file(save=True)"), answering)
        self.assertEqual(asked[-1], ["saves the scene"])           # saving still is asked about
        self.assertEqual(len(seen), 3)

    def test_it_may_only_look_where_the_user_said_so(self):
        maya = self.join_maya()
        self.server._code_allowed = True
        client, seen = self.client(), []
        answering = self.answering(maya, seen, output="", result="1", traceback="")

        def refused() -> str:
            with self.assertRaises(assistant.AssistantError) as raised:
                self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="1"), answering)
            return str(raised.exception)

        self.server._off_environments = {"Dev"}   # (set_environment_allowed would write the hub's config)
        self.assertIn("only look at Mayas of the environment", refused())
        self.assertFalse(self.ask(lambda: client.request(assistant.SESSIONS))["sessions"][0]["runs_code"])
        with self.assertRaises(assistant.AssistantError):   # nor reload / close there
            self.ask(lambda: client.request(assistant.RELOAD_CODE, again=False, pid=4242), answering)
        self.assertEqual(self.ask(lambda: client.request(assistant.READ_LOG, pid=4242))["known"], True)   # it still looks
        self.server._off_environments = set()
        self.server._denied = {4242}              # this one Maya, from its row's menu
        self.assertIn("closed this Maya", refused())
        self.server._denied = set()
        self.assertEqual(self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="1"),
                                  answering)["result"], "1")
        self.assertEqual(seen, ["1"])

    def test_a_detached_run_answers_with_a_job_and_keeps_its_outcome(self):
        maya = self.join_maya()
        self.server._code_allowed = True
        client, seen = self.client(), []
        self.assertEqual(self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, pid=4242, code="slow()",
                                                         detach=True, seconds=2000)), {"job": 1})
        standing = self.ask(lambda: client.request(assistant.JOB, job=1))
        self.assertEqual((standing["done"], standing["pid"]), (False, 4242))
        self.assertEqual(self.server.running(), {4242})
        answer = self.answering(maya, seen, output="done\n", result="7", traceback="")
        self.assertTrue(self.pump(lambda: (answer(), not self.server.running())[1]))
        outcome = self.ask(lambda: client.request(assistant.JOB, job=1))
        self.assertEqual((outcome["done"], outcome["output"], outcome["result"], seen), (True, "done\n", "7", ["slow()"]))
        with self.assertRaises(assistant.AssistantError):
            self.ask(lambda: client.request(assistant.JOB, job=99))

    def test_code_is_refused_for_a_maya_without_the_console_or_unknown_or_busy_with_it(self):
        maya = socket.create_connection(("127.0.0.1", self.link.port()), timeout=3)
        self.addCleanup(maya.close)
        maya.sendall(protocol.encode(protocol.event(protocol.HELLO, pid=77, version="2025", token=MAYA_TOKEN)))
        self.assertTrue(self.pump(lambda: len(self.link.sessions()) == 1))
        self.server._code_allowed = True
        client = self.client()

        def refused(**data) -> str:
            with self.assertRaises(assistant.AssistantError) as raised:
                self.ask(lambda: client.request(assistant.RUN_PYTHON, again=False, **data))
            return str(raised.exception)

        self.assertIn("takes no code", refused(pid=77, code="1"))
        self.assertIn("no connected Maya", refused(pid=5, code="1"))
        self.join_maya(pid=4242)
        self.assertIn("No code", refused(pid=4242, code="  "))
        self.server._running.add(4242)
        self.assertIn("previous code", refused(pid=4242, code="1"))

    def test_the_run_tool_end_to_end(self):
        from msl_tools.msl.run_maya_mcp import MayaTools
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        config = os.path.join(folder, "config.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"port": self.server.port(), "token": TOKEN, "enabled": True}, handle)
        tools = MayaTools(config)
        maya = self.join_maya()
        with self.assertRaises(assistant.AssistantError):   # not allowed yet
            self.ask(lambda: tools.run_python(code="1 + 1"))
        self.server._code_allowed = True
        seen = []
        text = self.ask(lambda: tools.run_python(code="print('hi'); 1 + 1"),
                        self.answering(maya, seen, output="hi\n", result="2", traceback=""))
        self.assertEqual((text, seen), ("hi\n# Result: 2", ["print('hi'); 1 + 1"]))
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: tools.run_python(code="boom"),
                     self.answering(maya, seen, output="", result="", traceback="NameError: boom"))
        self.assertIn("NameError: boom", str(raised.exception))
        self.assertIn("[runs code]", self.ask(tools.sessions))

    def test_the_report_is_passed_on_and_reload_needs_the_code_switch(self):
        maya = self.join_maya()
        maya.setblocking(False)
        decoder, asked = protocol.FrameDecoder(), []

        def answer():
            try:
                data = maya.recv(65536)
            except (BlockingIOError, InterruptedError):
                return
            for message in decoder.feed(data):
                asked.append((message["name"], message["data"]))
                result = {"text": "the report"} if message["name"] == protocol.LAUNCH_REPORT else {"modules": 12}
                maya.sendall(protocol.encode(protocol.reply(message["id"], **result)))

        client = self.client()
        self.assertEqual(self.ask(lambda: client.request(assistant.LAUNCH_REPORT, pid=4242, extra="x"), answer),
                         {"text": "the report"})
        self.assertEqual(asked, [(protocol.LAUNCH_REPORT, {})])   # nothing of the assistant's goes with it
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: client.request(assistant.RELOAD_CODE, again=False, pid=4242), answer)
        self.assertIn("switched off", str(raised.exception))
        self.assertEqual(len(asked), 1)
        self.server._code_allowed = True
        self.assertEqual(self.ask(lambda: client.request(assistant.RELOAD_CODE, again=False, pid=4242), answer),
                         {"modules": 12})
        with self.assertRaises(assistant.AssistantError):
            self.ask(lambda: client.request(assistant.LAUNCH_REPORT, pid=1))

    def test_a_maya_is_started_only_when_allowed_and_only_what_the_hub_has(self):
        asked = []

        def launch(version, environment, scene):
            asked.append((version, environment, scene))
            return "" if scene != "gone.ma" else "That scene isn\u2019t there any more: gone.ma"

        client = self.client()
        installs = mock.patch("msl_tools.msl.core.fs.maya_paths.MayaPaths.get_available_installs",
                              return_value={"2025": None, "2026": None})
        installs.start()
        self.addCleanup(installs.stop)

        def refused(**data) -> str:
            with self.assertRaises(assistant.AssistantError) as raised:
                self.ask(lambda: client.request(assistant.LAUNCH_MAYA, again=False, **data))
            return str(raised.exception)

        self.server._code_allowed = True
        self.assertIn("Maya Gate has not been opened", refused(version="2026", environment="Dev"))
        self.server.set_launcher(launch, ["<default>", "Stable", "Dev"])
        self.server._code_allowed = False
        self.assertIn("switched off", refused(version="2026", environment="Dev"))
        self.server._code_allowed = True
        self.assertIn("isn\u2019t installed", refused(version="2019", environment="Dev"))
        self.assertIn("no environment", refused(version="2026", environment="Prod"))
        self.assertIn("gone.ma", refused(version="2026", environment="Dev", scene="gone.ma"))
        self.assertEqual(asked, [("2026", "Dev", "gone.ma")])   # the refusals above never reached the launcher
        self.assertEqual(self.ask(lambda: client.request(assistant.LAUNCH_MAYA, again=False, version="2025",
                                                         environment="Stable", scene="C:/a.ma")), {"started": True})
        self.assertEqual(asked[-1], ("2025", "Stable", "C:/a.ma"))
        self.assertEqual(self.ask(lambda: client.request(assistant.HUB_INFO)),
                         {"versions": ["2025", "2026"], "environments": ["<default>", "Stable", "Dev"], "tools": []})

    def test_closing_is_the_links_quit_without_save_or_discard(self):
        maya = self.join_maya()
        maya.setblocking(False)
        decoder, asked = protocol.FrameDecoder(), []

        def answer():
            try:
                data = maya.recv(65536)
            except (BlockingIOError, InterruptedError):
                return
            for message in decoder.feed(data):
                asked.append((message["name"], message["data"]))
                maya.sendall(protocol.encode(protocol.reply(message["id"], False, protocol.QUIT_UNSAVED)))

        client = self.client()
        with self.assertRaises(assistant.AssistantError) as raised:   # the switch is off
            self.ask(lambda: client.request(assistant.CLOSE_MAYA, again=False, pid=4242), answer)
        self.assertEqual(asked, [])
        self.server._code_allowed = True
        with self.assertRaises(assistant.AssistantError) as raised:   # Maya's own refusal comes through
            self.ask(lambda: client.request(assistant.CLOSE_MAYA, again=False, pid=4242, discard=True), answer)
        self.assertIn("unsaved changes", str(raised.exception))
        self.assertEqual(asked, [(protocol.QUIT, {})])   # no "discard" of the assistant's goes with it

    def test_a_picture_of_the_hubs_window(self):
        class Window(qt.QtWidgets.QWidget):
            opened = ""

            def tool_ids(self):
                return ["maya_gate", "media"]

            def open_tool(self, tool):
                self.opened = tool

            def current_tool_id(self):
                return self.opened or "maya_gate"

        client = self.client()
        with self.assertRaises(assistant.AssistantError):   # no window was given
            self.ask(lambda: client.request(assistant.HUB_SCREENSHOT))
        window = Window()
        window.resize(320, 200)
        self.server.set_window(window)
        self.server.SCREENSHOT_DELAY_MS = 10
        with self.assertRaises(assistant.AssistantError) as raised:
            self.ask(lambda: client.request(assistant.HUB_SCREENSHOT, tool="nope"))
        self.assertIn("maya_gate, media", str(raised.exception))
        answer = self.ask(lambda: client.request(assistant.HUB_SCREENSHOT, tool="media"))
        self.addCleanup(lambda: os.path.exists(answer["path"]) and os.remove(answer["path"]))
        self.assertEqual((window.opened, answer["tool"], answer["width"], answer["height"]), ("media", "media", 320, 200))
        self.assertTrue(os.path.getsize(answer["path"]) > 0)

    def test_the_mcp_tools_end_to_end(self):
        from msl_tools.msl.run_maya_mcp import MayaTools, build_server
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        config = os.path.join(folder, "config.json")
        tools = MayaTools(config)
        server = build_server(tools)

        def call(name, **arguments):
            message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}
            result = self.ask(lambda: server.handle(message))["result"]
            return result["isError"], result["content"][0]["text"]

        failed, text = call("maya_sessions")   # no config file: the hub never ran / is switched off
        self.assertTrue(failed)
        self.assertIn("switched off", text)
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"port": self.server.port(), "token": TOKEN, "enabled": True}, handle)
        self.assertEqual(call("maya_sessions"), (False, "No Maya is connected to MSL Tools."))
        maya = self.join_maya()
        maya.sendall(protocol.encode(protocol.event(protocol.LOG, entries=[["error", "boom"], ["info", "fine"]])))
        self.assertTrue(self.pump(lambda: self.server.log.knows(4242)))
        failed, text = call("maya_sessions")
        self.assertFalse(failed)
        self.assertIn("pid 4242  Maya 2025  Dev  scene: C:/shots/a.ma", text)
        self.assertIn("errors 1, warnings 0", text)
        failed, text = call("maya_log", problems_only=True)   # one Maya: no pid needed
        self.assertFalse(failed)
        self.assertIn("error    boom", text)
        self.assertNotIn("fine", text)
        self.assertIn("last=2", text)
        self.join_maya(pid=5)
        failed, text = call("maya_log")
        self.assertTrue(failed)
        self.assertIn("Several Mayas", text)
        self.assertEqual(call("maya_log", pid=99)[0], True)

    def test_nobody_listens(self):
        self.server.close()
        client = assistant.AssistantClient(_free_port(), TOKEN, timeout=1.0)
        with self.assertRaises(assistant.AssistantError):
            self.ask(lambda: client.request(assistant.SESSIONS))


if __name__ == "__main__":
    unittest.main()
