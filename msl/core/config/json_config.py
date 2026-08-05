import copy

from collections.abc import MutableMapping, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Optional
from msl_tools.msl.core.config.storage import JsonStorage


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merges two dictionaries.
    Values from override always have priority.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (isinstance(value, dict)and isinstance(result.get(key), dict)):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigNode(MutableMapping):
    """
    Node in configuration tree.
    Features:
        • lazy nested dict creation, deferred until an actual write occurs
        • parent/root awareness
        • automatic dirty propagation
        • dict-like API
    """

    __slots__ = ("_data", "_parent", "_root", "_key", "_attached")

    def __init__(self, root: "JsonConfig", parent: Optional["ConfigNode"], data: dict[str, Any],
                 key: Optional[str] = None, attached: bool = True) -> None:

        self._root                 = root
        self._parent               = parent
        self._key                  = key
        self._attached             = attached
        self._data: dict[str, Any] = {}

        for k, v in data.items():
            self._data[k] = self._wrap(v)

    def _wrap(self, value: Any) -> Any:
        if isinstance(value, dict):
            # Values coming from real data (loaded/assigned) are attached immediately.
            return ConfigNode(root=self._root, parent=self, data=value, attached=True)
        return value

    def _unwrap(self, value: Any) -> Any:
        if isinstance(value, ConfigNode):
            return value.to_dict()
        return value

    def _ensure_attached(self) -> None:
        """
        Materializes this node (and its whole detached ancestor chain) into the tree.
        Called only on the write path, never on read - reading must stay side-effect free.
        """
        if self._attached:
            return
        if self._parent is not None:
            self._parent._ensure_attached()
            self._parent._data[self._key] = self
        self._attached = True

    def _mark_dirty(self) -> None:
        """
        Notify root that config was changed.
        """
        if self._root:
            self._root.mark_dirty()

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            # Return a detached placeholder: supports chained writes like
            # node["a"]["b"]["c"] = value without polluting the tree on plain reads.
            return ConfigNode(root=self._root, parent=self, data={}, key=key, attached=False)
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._ensure_attached()
        self._data[key] = self._wrap(value)
        self._mark_dirty()

    def __delitem__(self, key: str) -> None:
        self._ensure_attached()
        del self._data[key]
        self._mark_dirty()

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    # --------------------------------------------------
    # ORDER OPERATIONS
    # --------------------------------------------------

    def move_key_left(self, key: str) -> Optional[int]:
        keys = list(self._data.keys())

        if key not in keys:
            return None

        i = keys.index(key)
        if i == 0:
            return 0

        keys[i - 1], keys[i] = keys[i], keys[i - 1]
        self._rebuild(keys)

        return i - 1

    def move_key_right(self, key: str) -> Optional[int]:
        keys = list(self._data.keys())

        if key not in keys:
            return None

        i = keys.index(key)
        if i == len(keys) - 1:
            return i

        keys[i + 1], keys[i] = keys[i], keys[i + 1]
        self._rebuild(keys)

        return i + 1

    def reorder_keys(self, new_order: list[str]) -> None:
        if set(new_order) != set(self._data.keys()):
            raise ValueError("Key mismatch in reorder_keys")
        self._rebuild(new_order)

    def _rebuild(self, new_order: list[str]) -> None:
        self._ensure_attached()

        new_data = {}
        for k in new_order:
            new_data[k] = self._data[k]

        self._data = new_data
        self._mark_dirty()

    # --------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in self._data.items():
            if isinstance(v, ConfigNode):
                result[k] = v.to_dict()
            else:
                result[k] = v
        return result

    def __repr__(self) -> str:
        return f"ConfigNode({self.to_dict()})"


class JsonConfig:
    """
    Root configuration object.

    Responsible for:
        • lifecycle (load/save/reload)
        • dirty tracking
        • batching
        • root node access
    """

    def __init__(self, path: str, storage: Optional[JsonStorage] = None, defaults: Optional[dict[str, Any]] = None, autosave: bool = True) -> None:

        self.path     = path
        self.storage  = storage or JsonStorage()
        self.defaults = copy.deepcopy(defaults or {})

        self.autosave = autosave

        self._dirty: bool                = False
        self._batch_level: int           = 0
        self._root: Optional[ConfigNode] = None

        self.load()

    def load(self) -> None:
        """
        Load config from storage and merge with defaults.
        If defaults introduced data that isn't present on disk yet (including
        the case where the file doesn't exist at all), persist immediately
        instead of waiting for the first explicit write.
        """
        loaded = self.storage.read(self.path) or {}
        data   = deep_merge(self.defaults, loaded)

        self._root  = ConfigNode(root=self, parent=None, data=data, attached=True)
        self._dirty = (data != loaded)

        if self.autosave and self._dirty:
            self.save()

    def reload(self) -> None:
        """
        Reload config from disk.
        """
        self.load()

    def mark_dirty(self) -> None:
        """
        Called by ConfigNode when something changes.
        """
        self._dirty = True
        if self.autosave and self._batch_level == 0:
            self.save()

    def save(self) -> None:
        """
        Persist config to storage.
        """
        if not self._dirty:
            return
        if self._root is None:
            return

        self.storage.write(self.path, self._root.to_dict())
        self._dirty = False

    def batch(self):
        return BatchContext(self)

    def __getitem__(self, key: str) -> Any:
        if self._root is None:
            raise RuntimeError("Config not loaded")
        return self._root[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if self._root is None:
            raise RuntimeError("Config not loaded")
        self._root[key] = value

    def __delitem__(self, key: str) -> None:
        if self._root is None:
            raise RuntimeError("Config not loaded")
        del self._root[key]

    @property
    def data(self) -> dict[str, Any]:
        """
        Full config snapshot (copy).
        """
        if self._root is None:
            return {}
        return self._root.to_dict()

    def __repr__(self) -> str:
        return f"JsonConfig(path={self.path}, data={self.data})"


class BatchContext(AbstractContextManager):
    """
    Groups multiple changes into one save operation.
    """
    def __init__(self, config: JsonConfig) -> None:
        self._config = config

    def __enter__(self) -> JsonConfig:
        self._config._batch_level += 1
        return self._config

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._config._batch_level -= 1

        # last batch finished
        if (self._config._batch_level == 0 and self._config.autosave and self._config._dirty and exc is None):
            self._config.save()
        return False



if __name__ == "__main__":
    defaults = {
        "Dev": {},
        "Stable": {}
    }

    config = JsonConfig(path="config.json", defaults=defaults, storage=JsonStorage())

    config["Dev"]["Maya"]["2025"]["PATH"] = "C:/maya"
    config["Dev"]["Maya"]["2025"]["PLUGINS"] = ["a", "b", "c"]
    config["Dev"]["Maya"]["2025"]["test"] = ["a", "test"]

    node_2025 = config["Dev"]["Maya"]["2025"]
    node_2025.move_key_left("PLUGINS")
    node_2025.reorder_keys(["test", "PLUGINS", "PATH"])

    del node_2025["test"]

    with config.batch():
        config["Dev"]["A"] = 1
        config["Dev"]["B"] = 2
        config["Dev"]["C"] = 3

    print("Final Data Structure:")
    print(config.data)

    # Read-only access must not pollute the tree:
    _ = config["Dev"]["DoesNotExist"]["AlsoMissing"]
    assert "DoesNotExist" not in config["Dev"]
    print("Read-only probe did not create phantom keys - OK")