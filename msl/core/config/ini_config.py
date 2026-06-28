from typing import Any
from contextlib import contextmanager
from PySide6 import QtCore


@contextmanager
def settings_group(settings: QtCore.QSettings, group: str):
    settings.beginGroup(group)
    try:
        yield
    finally:
        settings.endGroup()


class IniSection:
    """Прокси для секции config['startup']"""

    def __init__(self, settings: QtCore.QSettings, section: str):
        self._settings = settings
        self._section = section

    def __getitem__(self, key: str) -> Any:
        with settings_group(self._settings, self._section):
            return self._settings.value(key)

    def __setitem__(self, key: str, value: Any) -> None:
        with settings_group(self._settings, self._section):
            self._settings.setValue(key, value)

    def __delitem__(self, key: str) -> None:
        with settings_group(self._settings, self._section):
            self._settings.remove(key)

    def __contains__(self, key: str) -> bool:
        return self._settings.contains(f"{self._section}/{key}")

    def __iter__(self):
        with settings_group(self._settings, self._section):
            keys = self._settings.childKeys()

        return iter(keys)

    def __len__(self) -> int:
        with settings_group(self._settings, self._section):
            return len(self._settings.childKeys())

    def get(
        self,
        key: str,
        default: Any = None,
        value_type: type | None = None
    ) -> Any:
        with settings_group(self._settings, self._section):

            if not self._settings.contains(key):
                self._settings.setValue(key, default)

            if value_type is None:
                return self._settings.value(key, default)

            return self._settings.value(key, defaultValue=default, type=value_type)

    def setdefault(self, key: str, default: Any) -> Any:
        if key not in self:
            self[key] = default

        return self[key]

    def keys(self) -> list[str]:
        with settings_group(self._settings, self._section):
            return list(self._settings.childKeys())

    def values(self) -> list[Any]:
        with settings_group(self._settings, self._section):
            return [
                self._settings.value(key)
                for key in self._settings.childKeys()
            ]

    def items(self) -> list[tuple[str, Any]]:
        with settings_group(self._settings, self._section):
            return [
                (key, self._settings.value(key))
                for key in self._settings.childKeys()
            ]

    def clear(self) -> None:
        with settings_group(self._settings, self._section):
            self._settings.remove("")

    def exists(self, key: str) -> bool:
        return key in self

    def __repr__(self) -> str:
        return f"IniSection('{self._section}')"


class IniConfig:

    def __init__(self, path: str):
        self.path = path
        self.settings = QtCore.QSettings(path,QtCore.QSettings.IniFormat)

    def __getitem__(self, section: str) -> IniSection:
        return IniSection(self.settings, section)

    def __contains__(self, section: str) -> bool:
        return section in self.sections()

    def __delitem__(self, section: str) -> None:
        with settings_group(self.settings, section):
            self.settings.remove("")

    def __iter__(self):
        return iter(self.sections())

    def __len__(self) -> int:
        return len(self.sections())

    def sections(self) -> list[str]:
        return self.settings.childGroups()

    def has_section(self, section: str) -> bool:
        return section in self

    def remove_section(self, section: str) -> bool:
        if section not in self:
            return False

        del self[section]
        return True

    def clear(self) -> None:
        self.settings.clear()

    def sync(self) -> None:
        self.settings.sync()

    def init_defaults(self, default: dict[str, dict[str, Any]]) -> None:
        for section, values in default.items():

            for key, value in values.items():

                if key not in self[section]:
                    self[section][key] = value

    def dump(self) -> dict[str, dict[str, Any]]:
        result = {}

        for section in self.sections():
            result[section] = dict(self[section].items())

        return result

    def print_info(self) -> None:

        for section in self.sections():

            print(f"[{section}]")

            for key, value in self[section].items():
                print(f"  {key:<20} = {value}")

    def __repr__(self) -> str:
        return f"IniConfig('{self.path}')"



if __name__ == "__main__":
    config = IniConfig("test.ini")
    DEFAULTS: dict[str, dict[str, Any]] = {
        "startup": {
            "init": True,
            "title": "MSL Maya Launcher",
            "window_geometry": "",
            "environment": "Dev",
        }
    }


    config["startup"]["title"] = "MSL Launcher"

    title = config["startup"]["title"]
    print(title)

    env = config["startup"].get("environment","Dev", str)
    print(env)

    width = config["window"].get("width",1200, int)
    print(width)
    visible = config["window"].get("visible",True,bool)
    sections = config.sections()
    print("sections",sections)

    print(visible)
    if "init" not in config["startup"]:
        print("title not exists, run get init")
        config.init_defaults(DEFAULTS)

    for key, value in config["startup"].items():
    	print(key, value)
    #
    # del config["startup"]["title"]
    #
    # del config["startup"]