# tools/desktop/maya_gate/hotkeys_store.py
"""The keys Maya Gate gives our Maya commands, per environment - Qt-free.

Kept in the page's config branch `hotkeys`: {"<env>": {"MSLRename": "Ctrl+Alt+R", ...}, "_release": {"<env>":
[commands that run again when their key is let go]}}; a launch hands
an environment's keys to Maya (core/link/hotkey_keys.to_environment), where tools/maya/hotkey_set.py puts
them into the hotkey set "MSL".

What a Maya of the environment already uses each key for (Maya's own keys, the user's set - animBot...)
is known only from a running Maya: the last answer is kept per environment in
`<base_dir>/hotkeys/seen_<env>.json`, so the tab can name a clash while no Maya runs.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from msl_tools.msl.core.fs.safe_json import JsonUnavailable, read_json_object, write_json_atomic
from msl_tools.msl.core.link import hotkey_keys


class HotkeyStore:
    """An environment's keys in the config node; what Maya was seen using in small files beside it.

    `known`: the command names that may have a key (hotkey_catalog.names()) - anything else read from the
    config or a file is left out.
    """

    def __init__(self, config, base_dir: str | Path, known):
        self._config = config        # the page's `hotkeys` node
        self._folder = Path(base_dir) / "hotkeys"
        self._known = set(known)
        self.last_read_release: set = set()   # the release commands of the file read_file() read last

    # --- the keys ---------------------------------------------------------------------------------

    def keys(self, environment: str) -> dict:
        stored = self._config.get(environment) if hasattr(self._config, "get") else None
        return hotkey_keys.cleaned(dict(stored) if stored is not None else {}, self._known)

    def _store(self, environment: str, keys: dict) -> None:
        self._config[environment] = hotkey_keys.cleaned(keys, self._known)

    RELEASE_KEY = "_release"   # not an environment's name: keys(env) never reads it

    def release(self, environment: str) -> set:
        """Commands of `environment` that run again when their key is let go ("hold to see")."""
        node = self._config.get(self.RELEASE_KEY) if hasattr(self._config, "get") else None
        names = node.get(environment) if node is not None and hasattr(node, "get") else None
        return {str(name) for name in (list(names) if names is not None else []) if str(name) in self._known}

    def set_release(self, environment: str, names) -> None:
        stored = {}
        node = self._config.get(self.RELEASE_KEY) if hasattr(self._config, "get") else None
        if node is not None:
            stored = {key: list(value) for key, value in dict(node).items()}
        stored[environment] = sorted(name for name in names if name in self._known)
        self._config[self.RELEASE_KEY] = stored

    def set_release_of(self, environment: str, name: str, on: bool) -> None:
        names = self.release(environment)
        names = names | {name} if on else names - {name}
        self.set_release(environment, names)

    def set_key(self, environment: str, name: str, text: str) -> list:
        """Gives `name` the key `text` ("" = none). Another command of the environment that had that key loses
        it - one key, one command. Returns the commands it was taken from."""
        keys = self.keys(environment)
        text = hotkey_keys.normalize(text)
        taken = []
        if text:
            taken = [other for other, other_text in keys.items() if other_text == text and other != name]
            for other in taken:
                del keys[other]
            keys[name] = text
        else:
            keys.pop(name, None)
        self._store(environment, keys)
        return taken

    def replace(self, environment: str, keys: dict) -> None:
        self._store(environment, keys)

    def clear(self, environment: str, names=None) -> dict:
        """Takes the keys of `names` (every one when None) away; returns what was there, for an undo."""
        before = self.keys(environment)
        self._store(environment, {} if names is None else {name: text for name, text in before.items()
                                                            if name not in names})
        return before

    def copy_to(self, source: str, target: str, names=None, replace: bool = True) -> tuple:
        """`source`'s keys of `names` (all when None) into `target`. Returns ([copied], [skipped])."""
        result, copied, skipped = hotkey_keys.copied(self.keys(source), self.keys(target), names, replace)
        self._store(target, result)
        released = self.release(source)
        self.set_release(target, (self.release(target) - set(copied)) | (released & set(copied)))
        return copied, skipped

    def conflicts_in(self, target: str, keys: dict) -> list:
        """Commands of `target` that would lose their key if `keys` were copied in."""
        current = self.keys(target)
        return sorted(other for name, text in keys.items() for other, other_text in current.items()
                      if other_text == text and other != name)

    # --- files ------------------------------------------------------------------------------------

    def export_file(self, path: str | Path, environment: str, names=None) -> int:
        keys = {name: text for name, text in self.keys(environment).items() if names is None or name in names}
        write_json_atomic(Path(path), hotkey_keys.export_data(keys, environment, self.release(environment)))
        return len(keys)

    def read_file(self, path: str | Path) -> dict:
        """The keys of an exported file (ValueError: not one of ours; JsonUnavailable / OSError: can't read).
        A file that isn't JSON is NOT moved aside - it isn't ours."""
        import json
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except ValueError:
            raise ValueError("this is not a file of MSL hotkeys")
        self.last_read_release = hotkey_keys.import_release(data, self._known)
        return hotkey_keys.import_data(data, self._known)

    # --- what a Maya of the environment uses each key for ---------------------------------------------

    def _seen_path(self, environment: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", environment).strip("_") or "default"
        return self._folder / ("seen_%s.json" % safe)

    def seen(self, environment: str) -> dict:
        """{"version", "time", "base", "current", "bindings": {key text: {"command", "label", "from"}}} as a
        Maya of `environment` last answered - {} when none ever did. "from" = "maya" (Maya's own key) or
        "set" (the user's set changed it: animBot & co.)."""
        try:
            data = read_json_object(self._seen_path(environment))
        except JsonUnavailable:
            return {}
        return data if isinstance(data.get("bindings"), dict) else {}

    def save_seen(self, environment: str, state: dict, version: str = "") -> dict:
        """Keeps a Maya's hotkeys_state answer for `environment`; returns what was kept."""
        bindings = {}
        for text, binding in (state.get("bindings") or {}).items():
            normalized = hotkey_keys.normalize(text)
            if normalized and isinstance(binding, dict):
                bindings[normalized] = {"command": str(binding.get("command") or ""),
                                        "label": str(binding.get("label") or ""),
                                        "from": "set" if binding.get("from") == "set" else "maya"}
        kept = {"version": str(version), "time": time.time(), "base": str(state.get("base") or ""),
                "current": str(state.get("current") or ""), "bindings": bindings}
        try:
            write_json_atomic(self._seen_path(environment), kept)
        except OSError:
            pass   # shown this time anyway
        return kept
