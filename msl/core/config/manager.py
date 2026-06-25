import os
from msl_tools.msl.core.config.ini_config import IniConfig
from msl_tools.msl.core.config.json_config import JsonConfig
from msl_tools.msl.core.paths import Paths
from typing import Union, Any
from PySide6 import QtCore
from msl_tools.msl.core.logger.manager import LoggerManager
from msl_tools.msl.core.resources import Resources


class ConfigManager:
    """A single point of control for all MSL tool configurations"""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Кэш активных конфигураторов: { "tool_name": Config_Instance }
        self._instances: dict[str, Union[JsonConfig, IniConfig]] = {}

    def __repr__(self) -> str:
        return repr("class ConfigManager")

    def get_config(self, tool_name: str, ext: str = ".json") -> Union[JsonConfig, IniConfig]:
        """
        Returns the tool configurator.
        :param tool_name: Tool name (folder/file name)
        :param ext: File extension ('.json' or '.ini')
        """
        if tool_name not in self._instances:
            ext = ext.lower()
            if not ext.startswith("."):
                ext = f".{ext}"

            # Формируем красивую структуру: base_dir / tool_name / config.ext
            tool_dir = self.base_dir / tool_name
            tool_dir.mkdir(parents=True, exist_ok=True)
            config_path = str(tool_dir / f"config{ext}")
            print(config_path)

            # Фабрика: выбираем класс на основе расширения
            if ext == ".json":
                Logger.info(f"[ConfigManager] Loading JSON config for '{tool_name}'")
                self._instances[tool_name] = JsonConfig(config_path)
            elif ext == ".ini":
                Logger.info(f"[ConfigManager] Loading INI config for '{tool_name}'")
                Logger.pathL(f"[Resources] {'Base root':.<17}: {tool_name}")
                self._instances[tool_name] = IniConfig(config_path)
            else:
                raise ValueError(f"Unsupported config extension: {ext}. Use '.json' or '.ini'")

        return self._instances[tool_name]



if __name__ == "__main__":
    res = Resources()


    renam_con = ConfigManager(res.paths.config).get_config("rename", ext=".json")
    modeling_cnf  = ConfigManager(res.paths.config).get_config("modeling", ext=".ini")
    modeling_cnf["startup", "window_geometry"] = "5"


