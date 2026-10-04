import logging
import sys

logger = logging.getLogger(__name__)


class ModuleSession:
    """Tracks and manages the state of sys.modules within the current process.
    The baseline is taken when the instance is created (in memory), never persisted to disk."""

    def __init__(self, logger=None):
        self._logger = logger or logging.getLogger(__name__)
        self._baseline: set[str] = set(sys.modules.keys())

    def get_new_modules(self) -> list[str]:
        """Modules loaded after the baseline was taken."""
        return [name for name in sys.modules if name not in self._baseline]

    def remove_modules(self, module_names: list[str]) -> list[str]:
        """Unloads modules from sys.modules. Returns the ones actually removed."""
        removed = []
        for name in module_names:
            if name not in sys.modules:
                self._logger.debug(f'Skipping absent module: "{name}"')
                continue
            del sys.modules[name]
            self._logger.debug(f'Removed "{name}"')
            removed.append(name)
        return removed

    def reset(self) -> list[str]:
        """Unloads everything that appeared in sys.modules after the baseline."""
        return self.remove_modules(self.get_new_modules())

    def remove_modules_startswith(self, prefix: str) -> list[str]:
        """Unloads every module whose name starts with prefix (regardless of the baseline)."""
        matched = [name for name in list(sys.modules) if name.startswith(prefix)]
        return self.remove_modules(matched)

    def filter_loaded_modules_path_containing(self, filter_strings: str | list[str], return_module: bool = True) -> list:
        """Modules whose __file__ contains any of filter_strings."""
        if isinstance(filter_strings, str):
            filter_strings = [filter_strings]
        if not isinstance(filter_strings, list):
            self._logger.error(f'Expected "list", got "{type(filter_strings)}"')
            return []

        matched_names = set()
        matched_modules = set()
        for name, module in list(sys.modules.items()):
            file_path = getattr(module, "__file__", None)
            if isinstance(file_path, str) and any(s in file_path for s in filter_strings):
                matched_names.add(name)
                matched_modules.add(module)
        return list(matched_modules) if return_module else list(matched_names)

    @staticmethod
    def prepend_sys_path(new_path: str) -> None:
        """Prepends the path to sys.path if it isn't there yet."""
        if not isinstance(new_path, str):
            raise TypeError("new_path must be a string.")
        if not new_path:
            raise ValueError("new_path cannot be an empty string.")
        if new_path not in sys.path:
            sys.path.insert(0, new_path)


if __name__ == '__main__':
    ModuleSession = ModuleSession()
    print(ModuleSession.get_new_modules())