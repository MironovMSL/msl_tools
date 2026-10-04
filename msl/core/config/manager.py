import logging
from pathlib import Path
from typing import Optional, Any

from msl_tools.msl.core.config.json_config import JsonConfig

_EXT_TO_CLASS = {
    ".json": JsonConfig,
}


class ConfigManager:
    """A single point of control for all MSL tool configurations"""

    def __init__(self, base_dir: Path, logger: Optional[logging.Logger] = None):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.logger   = logger or logging.getLogger(__name__)

        self._instances: dict[tuple[str, str], JsonConfig] = {}  # { (tool_name, ext): Config_Instance }

    def __repr__(self) -> str:
        return f"ConfigManager('{self.base_dir}')"

    def get_config(self,
                   tool_name: str,
                   ext: str = ".json",
                   defaults: Optional[dict[str, Any]] = None
                   ) -> JsonConfig:
        """
        Returns the tool configurator.

        :param defaults: Default values, applied when the config is first
            created in this process (a cache miss); they never overwrite values
            already stored. Any nesting.
        """
        ext = ext.lower()
        if not ext.startswith("."):
            ext = f".{ext}"

        if ext not in _EXT_TO_CLASS:
            raise ValueError(f"Unsupported config extension: {ext}. Use '.json'")

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

        # JsonConfig merges `defaults` into what is stored itself, on load() and every reload().
        instance = JsonConfig(config_path, defaults=defaults)

        self._instances[cache_key] = instance
        return instance
