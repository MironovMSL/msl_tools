import json
import os
import copy
from typing import Any, Iterator
from msl_tools.msl.core.logger import LauncherLogger
from collections.abc import MutableMapping


class _ConfigSectionDict(MutableMapping):
    """A dict wrapper that automatically calls save() on the parent."""
    def __init__(self, parent: "JsonConfig", section: str):
        self._parent = parent
        self._section = section

    def __getitem__(self, key: str) -> Any:
        d = self._parent.data[self._section]
        if key not in d:
            LauncherLogger.warning(f"[GET key] The key [{key}] does not exist in section [{self._section}].")
            d[key] = ""
            if self._parent.autosave:
                self._parent.save()
        return d[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._parent.data[self._section][key] = value
        LauncherLogger.info(f"[Save JsonConfig.data]{' ' * 5}[{self._section:.<10}] [{key:.<15}] = [{value}]")
        if self._parent.autosave:
            self._parent.save()

    def __delitem__(self, key: str) -> None:
        d = self._parent.data[self._section]
        if key in d:
            del d[key]
            if self._parent.autosave:
                self._parent.save()

        LauncherLogger.info(f"[Remove JsonConfig.data]{' ' * 5}[{self._section:.<10}] [{key:.<15}] key removed")

    def __iter__(self) -> Iterator[str]:
        return iter(self._parent.data[self._section])

    def __len__(self) -> int:
        return len(self._parent.data[self._section])

    def __contains__(self, key: str) -> bool:
        return key in self._parent.data[self._section]

    def __repr__(self) -> str:
        return repr(self._parent.data[self._section])

    def move_key_left(self, key: str) -> int:
        d = self._parent.data[self._section]
        keys = list(d.keys())

        if key not in keys:
            return None

        idx = keys.index(key)
        if idx > 0:
            keys[idx - 1], keys[idx] = keys[idx], keys[idx - 1]
            self._parent.data[self._section] = {k: d[k] for k in keys}
            if self._parent.autosave:
                self._parent.save()
            idx -= 1  # после перемещения индекс изменился

        return idx

    def move_key_right(self, key: str) -> None:
        d = self._parent.data[self._section]
        keys = list(d.keys())

        if key not in keys:
            return None

        idx = keys.index(key)
        if idx < len(keys) - 1:
            keys[idx + 1], keys[idx] = keys[idx], keys[idx + 1]
            self._parent.data[self._section] = {k: d[k] for k in keys}
            if self._parent.autosave:
                self._parent.save()
            idx += 1

        return idx

    def reorder_keys(self, new_order: list[str]) -> None:
        d = self._parent.data[self._section]
        current_keys = set(d.keys())

        if set(new_order) != current_keys:
            raise ValueError("The new_order list does not match the current section keys")

        self._parent.data[self._section] = {k: d[k] for k in new_order}

        if self._parent.autosave:
            self._parent.save()


class JsonConfig:

    DEFAULTS: dict[str, dict[str, Any]] = {
        "Dev"       : {},
        "Stable"    : {},
        "<default>" : {},
        "Additional": {}
    }

    def __init__(self, json_path: str, autosave: bool = True):
        self.path = json_path
        self.autosave = autosave
        self.data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except json.JSONDecodeError:
                LauncherLogger.error(f"Config file {self.path} is corrupted. Restoring defaults.")
                self.data = copy.deepcopy(self.DEFAULTS)
                self.save()
                data = json.dumps(self.data, indent=4, ensure_ascii=False)
                LauncherLogger.init(f"[Initialize json_config.ini] {data}.")
        else:
            self.data = copy.deepcopy(self.DEFAULTS)
            self.save()
            data = json.dumps(self.data, indent=4, ensure_ascii=False)
            LauncherLogger.init(f"[Initialize json_config.ini] {data}.")

    def save(self) -> None:
        LauncherLogger.info(f"[Svae json_config.json] {self.path}.]")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def __getitem__(self, section: str) -> _ConfigSectionDict:
        if section not in self.data:
            LauncherLogger.warning(f"[GET Section] Section [{section}] does not exist. Creating empty.")
            self.data[section] = {}
            if self.autosave:
                self.save()
        return _ConfigSectionDict(self, section)

    def __setitem__(self, section: str, value: dict[str, Any]) -> None:
        if isinstance(value, dict):
            self.data[section] = value
            if self.autosave:
                self.save()
            LauncherLogger.info(f"[Save JsonConfig.data]{' ' * 5}[{section:.<10}] = [{value}]")
        else:
            LauncherLogger.warning(f"[SET Section] Attempt to assign a non-dict value to section [{section}]: {value}")

    def __delitem__(self, section: str) -> None:
        if section in self.data:
            del self.data[section]
            if self.autosave:
                self.save()

        LauncherLogger.info(f"[Remove JsonConfig.data]{' ' * 5}[{section:.<10}] section removed")

    def __repr__(self) -> str:
        return f"JsonConfig({self.path!r}, sections={list(self.data.keys())})"

    def add_section(self, name: str) -> None:
        if name not in self.data:
            self.data[name] = {}
            if self.autosave:
                self.save()

    def remove(self, section: str, key: str) -> None:
        if section in self.data and key in self.data[section]:
            del self.data[section][key]
            if self.autosave:
                self.save()

    def reorder_keys(self, section: str, new_order: list[str]) -> None:
        """Переставить ключи в секции в заданном порядке"""
        if section not in self.data:
            raise KeyError(f"Section '{section}' not found in config")
        old_section = self.data[section]
        self.data[section] = {k: old_section[k] for k in new_order if k in old_section}
        if self.autosave:
            self.save()

    def keys(self):
        return self.data.keys()

    def items(self):
        return self.data.items()

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.data.get(section, {}).get(key, default)

    def setdefault(self, section: str, key: str, default: Any = None) -> Any:
        if section not in self.data:
            self.data[section] = {}
        value = self.data[section].setdefault(key, default)
        if self.autosave:
            self.save()
        return value

    def get_info_all_keys(self) -> None:
        """print config.json"""
        data = json.dumps(self.data, indent=4, ensure_ascii=False)
        LauncherLogger.info(f"[config.json]\n {data}")



if __name__ == "__main__":


    config = JsonConfig("Testsettings.json")
    # set
    config["Dev"]["TEST_PATH"] = "path"

    print(list(config["Dev"].items()))
    for section, v in config.items():
        print(f"[SECTION] {section, v}")
    value = config.get("Dev", "MAYA_APP_DIR11", default="C:/tmp")
    print(value)

    # удаление ключа
    del config["TEST"]
    del config["Dev"]["MAYA_APP_DIR"]

    # добавление новой секции
    config.add_section("Custom")
    config["Custom"]["foo"] = "bar"

    # смена порядка ключей
    keys = list(config["Dev"].keys())
    keys.remove("NEW_PATH")
    keys.insert(0, "NEW_PATH")
    config.reorder_keys("Dev", keys)

    print("До:", config["Dev"])

    config["Dev"].move_key_right("PYTHONPATH")
    print("После move_key_right(PYTHONPATH):", config["Dev"])

    config["Dev"].move_key_left("TEMP")
    print("После move_key_left(TEMP):", config["Dev"])