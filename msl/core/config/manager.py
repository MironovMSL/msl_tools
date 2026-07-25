import logging
from pathlib import Path
from typing import Optional, Union, Any

from msl_tools.msl.core.config.ini_config import IniConfig
from msl_tools.msl.core.config.json_config import JsonConfig

_EXT_TO_CLASS = {
    ".json": JsonConfig,
    ".ini": IniConfig,
}


class ConfigManager:
    """A single point of control for all MSL tool configurations"""

    def __init__(self, base_dir: Path, logger: Optional[logging.Logger] = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger   = logger or logging.getLogger(__name__)

        self._instances: dict[tuple[str, str], Union[JsonConfig, IniConfig]] = {}  # { (tool_name, ext): Config_Instance }

    def __repr__(self) -> str:
        return f"ConfigManager('{self.base_dir}')"

    def get_config(self,
                   tool_name: str,
                   ext: str = ".json",
                   defaults: Optional[dict[str, Any]] = None
                   ) -> Union[JsonConfig, IniConfig]:
        """
        Returns the tool configurator.

        :param defaults: Дефолтные значения, применяются только при первом
            создании конфига (cache miss). Не перетирают уже существующие
            значения. Формат зависит от бэкенда:
              - JsonConfig: произвольная вложенность
              - IniConfig: ровно два уровня {section: {key: value}}
        """
        ext = ext.lower()
        if not ext.startswith("."):
            ext = f".{ext}"

        if ext not in _EXT_TO_CLASS:
            raise ValueError(f"Unsupported config extension: {ext}. Use '.json' or '.ini'")

        cache_key = (tool_name, ext)

        if cache_key in self._instances:
            if defaults is not None:
                self.logger.debug(
                    f"Config '{tool_name}{ext}' already initialized; "
                    f"ignoring defaults passed on repeat get_config() call."
                )
            return self._instances[cache_key]

        config_cls = _EXT_TO_CLASS[ext]

        tool_dir = self.base_dir / tool_name
        tool_dir.mkdir(parents=True, exist_ok=True)
        config_path = str(tool_dir / f"config{ext}")

        self.logger.info(f"Loading {config_cls.__name__} config for '{tool_name}' -> {config_path}")

        if config_cls is JsonConfig:
            # JsonConfig сам мержит defaults с загруженными данными в load(),
            # причём self.defaults остаётся на инстансе -> будет применяться
            # и при последующих reload() тоже.
            instance = JsonConfig(config_path, defaults=defaults)
        else:
            # IniConfig не принимает defaults в конструкторе -
            # заполняем недостающие ключи явным вызовом сразу после создания.
            instance = IniConfig(config_path)
            if defaults:
                instance.init_defaults(defaults)
                self.logger.info(
                    f"Applied defaults to '{tool_name}' ({config_path}): "
                    f"{sum(len(v) for v in defaults.values())} key(s) checked."
                )

        self._instances[cache_key] = instance
        return instance


if __name__ == "__main__":
    from msl_tools.msl.core.fs.paths import Paths

    config = Paths.configs
    manager = ConfigManager(config)

    renam_con = manager.get_config("rename", ext=".json")
    renam_con["test"]["test"] = "test"

    modeling_cnf = manager.get_config("modeling", ext=".ini")
    modeling_cnf["startup"]["window_geometry"] = 6

    # Повторный запрос той же пары (tool_name, ext) -> вернёт закэшированный, ОК
    same = manager.get_config("rename", ext=".json")
    print(same is renam_con)  # True

    # Теперь это РАЗРЕШЕНО: "rename" одновременно и .json, и .ini —
    # два независимых файла, два независимых объекта
    renam_ini = manager.get_config("rename", ext=".ini")
    renam_ini["test"]["test"] = "test"
    print(renam_ini is renam_con)      # False — разные объекты
    print(type(renam_ini).__name__)    # IniConfig
    print(type(renam_con).__name__)    # JsonConfig