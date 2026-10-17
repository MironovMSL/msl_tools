"""Maya Gate's Hotkeys: key text <-> Maya's flags, the launch variable, files, the store, the catalog, and the
hotkey set MSL built inside Maya (against a fake maya.cmds that behaves like the measured Maya 2026)."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.link import hotkey_keys, variables
from msl_tools.msl.tools.desktop.maya_gate.hotkeys_store import HotkeyStore
from msl_tools.msl.tools.maya import hotkey_catalog


class KeyText(unittest.TestCase):
    def test_normalized_in_any_order_and_spelling(self):
        for text in ("ctrl+alt+r", "Alt+Ctrl+R", " CONTROL + alt + r ", "ctl+alt+R"):
            self.assertEqual(hotkey_keys.normalize(text), "Ctrl+Alt+R", text)
        self.assertEqual(hotkey_keys.normalize("shift+pgup"), "Shift+PageUp")
        self.assertEqual(hotkey_keys.normalize("Alt+Return"), "Alt+Enter")
        self.assertEqual(hotkey_keys.normalize("Ctrl+Page_Down"), "Ctrl+PageDown")
        self.assertEqual(hotkey_keys.normalize("f5"), "F5")
        self.assertEqual(hotkey_keys.normalize("Ctrl+;"), "Ctrl+;")

    def test_what_is_no_shortcut(self):
        for text in ("", "Ctrl", "Ctrl+", "Ctrl+Ctrl+R", "Ctrl+R+T", "Ctrl+Я", "Ctrl++", "F13", "Win+R", None, 5):
            self.assertEqual(hotkey_keys.normalize(text), "", text)

    def test_caps_and_modifiers(self):
        self.assertEqual(hotkey_keys.parts("alt+shift+x"), ["Alt", "Shift", "X"])
        self.assertEqual(hotkey_keys.parts("nonsense"), [])
        self.assertTrue(hotkey_keys.has_modifier("Ctrl+R"))
        self.assertFalse(hotkey_keys.has_modifier("Shift+R"))

    def test_to_maya_and_back(self):
        self.assertEqual(hotkey_keys.to_maya("Ctrl+Shift+K"), {"keyShortcut": "k", "ctl": True, "alt": False, "sht": True})
        self.assertEqual(hotkey_keys.to_maya("Alt+PageUp"), {"keyShortcut": "Page_Up", "ctl": False, "alt": True, "sht": False})
        self.assertEqual(hotkey_keys.to_maya("Enter")["keyShortcut"], "Return")
        self.assertIsNone(hotkey_keys.to_maya("Ctrl"))
        self.assertEqual(hotkey_keys.from_maya("K", ctl=True), "Ctrl+Shift+K")   # Maya's upper case = Shift
        self.assertEqual(hotkey_keys.from_maya("Page_Down", alt=True, sht=True), "Alt+Shift+PageDown")
        for text in ("Ctrl+Alt+R", "Shift+F12", "Alt+`", "Ctrl+Shift+Backspace", "Space"):
            flags = dict(hotkey_keys.to_maya(text))
            self.assertEqual(hotkey_keys.from_maya(flags.pop("keyShortcut"), **flags), text)

    def test_cleaned_and_clashes(self):
        keys = {"MSLRename": "alt+ctrl+r", "MSLLabels": "bad", "Other": "Ctrl+K", "MSLControls": "Ctrl+Alt+R"}
        self.assertEqual(hotkey_keys.cleaned(keys, known={"MSLRename", "MSLLabels", "MSLControls"}),
                         {"MSLRename": "Ctrl+Alt+R", "MSLControls": "Ctrl+Alt+R"})
        self.assertEqual(hotkey_keys.clashes(keys), {"Ctrl+Alt+R": ["MSLControls", "MSLRename"]})

    def test_copied_takes_a_key_from_the_one_that_had_it(self):
        source = {"A": "Ctrl+1", "B": "Ctrl+2"}
        target = {"C": "Ctrl+1", "D": "Ctrl+9"}
        result, copied, skipped = hotkey_keys.copied(source, target)
        self.assertEqual(result, {"A": "Ctrl+1", "B": "Ctrl+2", "D": "Ctrl+9"})
        self.assertEqual((copied, skipped), (["A", "B"], []))
        result, copied, skipped = hotkey_keys.copied(source, target, names={"A"}, replace=False)
        self.assertEqual((result, copied, skipped), ({"C": "Ctrl+1", "D": "Ctrl+9"}, [], ["A"]))

    def test_free_keys_start_with_the_names_letters(self):
        free = hotkey_keys.free_keys("Rename window", taken={"Ctrl+Alt+R"}, limit=4)
        self.assertEqual(free, ["Alt+Shift+R", "Ctrl+Alt+W", "Ctrl+Alt+E", "Ctrl+Alt+N"])
        self.assertEqual(len(hotkey_keys.free_keys("x", taken=(), limit=12)), 12)
        every = {hotkey_keys.compose(mods, key) for mods in hotkey_keys.FREE_MODIFIERS for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}
        self.assertEqual(hotkey_keys.free_keys("x", taken=every), [])

    def test_the_launch_variable(self):
        launch = hotkey_keys.to_environment({"MSLRename": "alt+ctrl+r", "x": "nope"})
        self.assertEqual(list(launch), [variables.HOTKEYS])
        self.assertIn(variables.HOTKEYS, variables.ALL)
        self.assertEqual(hotkey_keys.from_environment(launch), {"MSLRename": "Ctrl+Alt+R"})
        self.assertEqual(hotkey_keys.to_environment({}), {variables.HOTKEYS: "{}"})   # set, though empty
        self.assertEqual(hotkey_keys.from_environment({variables.HOTKEYS: "{}"}), {})
        self.assertIsNone(hotkey_keys.from_environment({}))                         # not from Maya Gate
        self.assertEqual(hotkey_keys.from_environment({variables.HOTKEYS: "{broken"}), {})

    def test_release_travels_with_the_launch_and_the_file(self):
        launch = hotkey_keys.to_environment({"MSLToggleJoints": "Alt+3"}, release={"MSLToggleJoints", "MSLNoKey"})
        self.assertEqual(launch[variables.HOTKEYS_RELEASE], "MSLToggleJoints")      # only commands with a key
        self.assertEqual(hotkey_keys.release_from_environment(launch), {"MSLToggleJoints"})
        self.assertNotIn(variables.HOTKEYS_RELEASE, hotkey_keys.to_environment({"A": "Alt+3"}))
        data = hotkey_keys.export_data({"MSLToggleJoints": "Alt+3"}, "Dev", {"MSLToggleJoints"})
        self.assertEqual(hotkey_keys.import_release(data), {"MSLToggleJoints"})
        self.assertEqual(hotkey_keys.import_release({"format": "msl_hotkeys", "keys": {}}), set())

    def test_file_data(self):
        data = hotkey_keys.export_data({"MSLRename": "ctrl+alt+r"}, "Dev")
        self.assertEqual(hotkey_keys.import_data(json.loads(json.dumps(data))), {"MSLRename": "Ctrl+Alt+R"})
        for wrong in ({}, {"format": "other", "keys": {}}, [], {"format": "msl_hotkeys", "keys": []}):
            with self.assertRaises(ValueError):
                hotkey_keys.import_data(wrong)


class Catalog(unittest.TestCase):
    def test_every_command_once_with_a_group_and_an_icon(self):
        commands = hotkey_catalog.commands()
        names = [command.name for command in commands]
        self.assertEqual(len(names), len(set(names)))
        icons = FileSystemManager.icons / "actions"
        for command in commands:
            self.assertIn(command.group, hotkey_catalog.GROUPS, command.name)
            self.assertTrue((icons / (command.icon + ".svg")).is_file(), command.icon)
            self.assertTrue(command.label and command.annotation, command.name)
        self.assertTrue(hotkey_catalog.TOGGLES <= set(names))
        self.assertTrue(all(command.toggle == (command.name in hotkey_catalog.TOGGLES) for command in commands))
        self.assertIn("MSLRename", names)
        self.assertIn("MSLResetAttributes", names)

    def test_the_tools_python_names_a_real_function(self):
        package = Path(__file__).resolve().parents[2] / "msl" / "tools" / "maya"
        for command in hotkey_catalog.TOOL_COMMANDS:
            module = command.python.split(" import ")[0].replace("from msl_tools.msl.tools.maya.", "")
            function = command.python.split(" import ")[1].split(";")[0]
            path = package.joinpath(*module.split("."))
            source = (path / "__init__.py") if path.is_dir() else path.with_suffix(".py")
            self.assertIn("def %s(" % function, source.read_text(encoding="utf-8"), command.name)


class Store(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.config = {}
        self.store = HotkeyStore(self.config, self._folder.name, known={"A", "B", "C"})

    def tearDown(self):
        self._folder.cleanup()

    def test_one_key_one_command(self):
        self.assertEqual(self.store.set_key("Dev", "A", "ctrl+1"), [])
        self.assertEqual(self.store.set_key("Dev", "B", "Ctrl+1"), ["A"])
        self.assertEqual(self.store.keys("Dev"), {"B": "Ctrl+1"})
        self.store.set_key("Dev", "B", "")
        self.assertEqual(self.store.keys("Dev"), {})
        self.store.set_key("Dev", "Z", "Ctrl+2")      # not a known command
        self.assertEqual(self.store.keys("Dev"), {})

    def test_copy_clear_and_files(self):
        self.store.replace("Dev", {"A": "Ctrl+1", "B": "Ctrl+2"})
        self.store.replace("Stable", {"C": "Ctrl+1"})
        self.assertEqual(self.store.conflicts_in("Stable", {"A": "Ctrl+1"}), ["C"])
        self.assertEqual(self.store.copy_to("Dev", "Stable", names={"A"}), (["A"], []))
        self.assertEqual(self.store.keys("Stable"), {"A": "Ctrl+1"})
        path = Path(self._folder.name) / "keys.json"
        self.assertEqual(self.store.export_file(path, "Dev"), 2)
        self.assertEqual(self.store.read_file(path), {"A": "Ctrl+1", "B": "Ctrl+2"})
        before = self.store.clear("Dev", names={"A"})
        self.assertEqual((before, self.store.keys("Dev")), ({"A": "Ctrl+1", "B": "Ctrl+2"}, {"B": "Ctrl+2"}))
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.read_file(path)
        self.assertTrue(path.exists())                 # not ours: never moved aside

    def test_release_flags_kept_and_copied(self):
        self.store.replace("Dev", {"A": "Alt+1", "B": "Alt+2"})
        self.store.set_release_of("Dev", "A", True)
        self.assertEqual(self.store.release("Dev"), {"A"})
        self.assertEqual(self.store.keys("Dev"), {"A": "Alt+1", "B": "Alt+2"})      # "_release" isn't a key
        self.store.copy_to("Dev", "Stable")
        self.assertEqual(self.store.release("Stable"), {"A"})
        self.store.set_release_of("Dev", "A", False)
        self.assertEqual(self.store.release("Dev"), set())
        path = Path(self._folder.name) / "r.json"
        self.store.set_release_of("Dev", "B", True)
        self.store.export_file(path, "Dev")
        self.store.read_file(path)
        self.assertEqual(self.store.last_read_release, {"B"})

    def test_what_maya_was_seen_using(self):
        self.assertEqual(self.store.seen("<default>"), {})
        kept = self.store.save_seen("<default>", {"base": "animBot", "current": "MSL", "bindings": {
            "alt+a": {"command": "animBot_delete", "label": "Delete Keys", "from": "set"},
            "Ctrl+Z": {"command": "NameComUndo", "label": "Undo", "from": "maya"}, "bad": {}}}, version="2026")
        self.assertEqual(set(kept["bindings"]), {"Alt+A", "Ctrl+Z"})
        seen = self.store.seen("<default>")
        self.assertEqual((seen["base"], seen["version"], seen["bindings"]["Alt+A"]["from"]), ("animBot", "2026", "set"))
        self.assertTrue((Path(self._folder.name) / "hotkeys" / "seen_default.json").is_file())


class _FakeCmds(types.ModuleType):
    """Hotkey sets as Maya 2026 keeps them (measured): -source copies, deleting the current set falls back
    to Maya_Default, a query of a key gives the Global nameCommand."""

    def __init__(self):
        super().__init__("maya.cmds")
        self.sets = {"Maya_Default": {("z", False, False, False): "NameComUndo"},
                     "animBot": {("z", False, False, False): "NameComUndo",
                                 ("a", False, True, False): "animBot_deleteNameCommand"}}
        self.current = "animBot"
        self.options = {}
        self.runtime = set()
        self.jobs = []
        self.releases = {}

    def hotkeySet(self, name=None, query=False, edit=False, current=False, exists=False, delete=False,
                  source=None, hotkeySetArray=False):
        if query and current:
            return self.current
        if query and exists:
            return name in self.sets
        if query and hotkeySetArray:
            return list(self.sets)
        if edit and delete:
            del self.sets[name]
            self.releases.pop(name, None)
            if self.current == name:
                self.current = "Maya_Default"
            return True
        if edit and current:
            self.current = name
            return name
        self.sets[name] = dict(self.sets[source or "Maya_Default"])
        if current:
            self.current = name
        return name

    def hotkey(self, key=None, query=False, name=None, keyShortcut=None, ctl=False, alt=False, sht=False,
               releaseName=None):
        if query:
            if releaseName:
                return self.releases.get(self.current, {}).get((key, ctl, alt, sht), "")
            return self.sets[self.current].get((key, ctl, alt, sht), "")
        self.sets[self.current][(keyShortcut, ctl, alt, sht)] = name
        if releaseName:
            self.releases.setdefault(self.current, {})[(keyShortcut, ctl, alt, sht)] = releaseName

    def optionVar(self, stringValue=None, query=None, exists=None):
        if stringValue:
            self.options[stringValue[0]] = stringValue[1]
            return None
        if exists:
            return exists in self.options
        return self.options.get(query, 0)

    def nameCommand(self, name, **_kwargs):
        return name

    def runTimeCommand(self, name, query=False, exists=False):
        return name in self.runtime

    def assignCommand(self, index=None, query=False, numElements=False, name=False, annotation=False):
        names = ["animBot_deleteNameCommand", "NameComUndo"]
        if numElements:
            return len(names)
        return names[index - 1] if name else {"animBot_deleteNameCommand": "Delete Keys", "NameComUndo": "Undo"}[names[index - 1]]

    def scriptJob(self, event=None, protected=False, exists=None, kill=None, force=False):
        if exists is not None:
            return exists in self.jobs
        if kill is not None:
            self.jobs.remove(kill)
            return None
        self.jobs.append(len(self.jobs) + 1)
        return self.jobs[-1]


class HotkeySetInMaya(unittest.TestCase):
    def setUp(self):
        self.cmds = _FakeCmds()
        self.cmds.runtime = set(hotkey_catalog.names())
        maya = types.ModuleType("maya")
        maya.cmds = self.cmds
        self._saved = {name: sys.modules.get(name) for name in ("maya", "maya.cmds")}
        sys.modules["maya"], sys.modules["maya.cmds"] = maya, self.cmds
        from msl_tools.msl.tools.maya import hotkey_set
        self.hotkey_set = hotkey_set

    def tearDown(self):
        for name, module in self._saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_built_from_the_users_set_never_changing_it(self):
        report = self.hotkey_set.apply({"MSLRename": "Alt+A", "MSLLabels": "Ctrl+Shift+L", "Nope": "Ctrl+1"})
        self.assertEqual((report["base"], report["current"], report["applied"]), ("animBot", "MSL", 2))
        self.assertEqual(report["clashes"], {"Alt+A": "Delete Keys"})
        self.assertEqual(report["skipped"], ["Nope"])
        msl = self.cmds.sets["MSL"]
        self.assertEqual(msl[("a", False, True, False)], "MSLRenameNameCommand")
        self.assertEqual(msl[("l", True, False, True)], "MSLLabelsNameCommand")
        self.assertEqual(msl[("z", False, False, False)], "NameComUndo")          # the base's keys stay
        self.assertEqual(self.cmds.sets["animBot"][("a", False, True, False)], "animBot_deleteNameCommand")

    def test_rebuilt_on_the_next_start_from_the_remembered_base(self):
        self.hotkey_set.apply({"MSLRename": "Ctrl+1"})
        report = self.hotkey_set.apply({"MSLLabels": "Ctrl+2"})                # Maya is on MSL now
        self.assertEqual(report["base"], "animBot")
        self.assertNotIn(("1", True, False, False), self.cmds.sets["MSL"])     # the old key is gone
        self.hotkey_set._on_quit()
        self.assertEqual(self.cmds.current, "animBot")                          # saved as the one to start with

    def test_no_keys_leaves_the_users_set(self):
        self.hotkey_set.apply({"MSLRename": "Ctrl+1"})
        report = self.hotkey_set.apply({})
        self.assertEqual((report["current"], self.cmds.current), ("animBot", "animBot"))
        self.assertNotIn("MSL", self.cmds.sets)

    def test_state_names_what_the_base_set_does(self):
        self.hotkey_set.apply({"MSLRename": "Ctrl+1"})
        state = self.hotkey_set.state()
        self.assertEqual((state["base"], state["current"]), ("animBot", "MSL"))
        self.assertEqual(state["ours"], {"MSLRename": "Ctrl+1"})
        self.assertEqual(state["bindings"]["Alt+A"], {"command": "animBot_deleteNameCommand", "label": "Delete Keys",
                                                      "from": "set"})
        self.assertEqual(state["bindings"]["Z"]["from"], "maya")
        self.assertEqual(self.cmds.current, "MSL")                              # put back after the scan

    def test_a_toggle_may_run_again_on_release(self):
        self.hotkey_set.apply({"MSLToggleJoints": "Alt+3", "MSLRename": "Alt+4"}, release={"MSLToggleJoints", "MSLRename"})
        releases = self.cmds.releases["MSL"]
        self.assertEqual(releases, {("3", False, True, False): "MSLToggleJointsNameCommand"})   # Rename: no toggle
        self.assertEqual(self.hotkey_set.state()["release"], ["MSLToggleJoints"])

    def test_only_our_commands_run(self):
        with self.assertRaises(ValueError):
            self.hotkey_set.run("DeleteAllHistory")


if __name__ == "__main__":
    unittest.main()
