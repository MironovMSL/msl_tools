import logging
from pathlib import Path
from typing import Optional, Union

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

        # Логгер приходит извне (DI), а не создаётся здесь самостоятельно —
        # это разрывает потенциальный циклический импорт с Resources,
        # который сам создаёт и ConfigManager, и LoggerManager.
        # Если логгер не передали -- используем "немой" стандартный logging,
        # чтобы модуль оставался рабочим и вне контекста Resources.
        self.logger = logger or logging.getLogger(__name__)

        # Кэш активных конфигураторов: { (tool_name, ext): Config_Instance }
        self._instances: dict[tuple[str, str], Union[JsonConfig, IniConfig]] = {}

    def __repr__(self) -> str:
        return f"ConfigManager('{self.base_dir}')"

    def get_config(self, tool_name: str, ext: str = ".json") -> Union[JsonConfig, IniConfig]:
        """
        Returns the tool configurator.

        Один tool_name может одновременно иметь и .json, и .ini конфиг —
        это два независимых файла (tool_dir/config.json, tool_dir/config.ini)
        и два независимых закэшированных объекта.

        :param tool_name: Tool name (folder name)
        :param ext: File extension ('.json' or '.ini')
        :raises ValueError: if ext is unsupported.
        """
        ext = ext.lower()
        if not ext.startswith("."):
            ext = f".{ext}"

        if ext not in _EXT_TO_CLASS:
            raise ValueError(f"Unsupported config extension: {ext}. Use '.json' or '.ini'")

        cache_key = (tool_name, ext)

        if cache_key in self._instances:
            return self._instances[cache_key]

        config_cls = _EXT_TO_CLASS[ext]

        tool_dir = self.base_dir / tool_name
        tool_dir.mkdir(parents=True, exist_ok=True)
        config_path = str(tool_dir / f"config{ext}")

        self.logger.info("Loading %s config for '%s' -> %s", config_cls.__name__, tool_name, config_path)

        self._instances[cache_key] = config_cls(config_path)
        return self._instances[cache_key]


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
    print(renam_ini is renam_con)      # False — разные объекты
    print(type(renam_ini).__name__)    # IniConfig
    print(type(renam_con).__name__)    # JsonConfig