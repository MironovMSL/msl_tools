# core/version/local_version.py
import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalVersionReader:
    """Reads the __version__ string from an __init__.py file at any given path.

    The file is READ, never run: it may come from a downloaded archive or a
    folder the user picked, and whatever code it holds must not run inside
    the hub just to learn a version. Its top-level assignments of plain
    values are read (ast.literal_eval); `__version__` itself, or — as
    msl/__init__.py builds it — `__version_tuple__` + `__version_suffix__`.

    This is a stateless, read-only utility class.
    """

    @classmethod
    def get_version(cls, module_path: str | Path) -> str | None:
        """Extracts the __version__ variable from the __init__.py inside the target directory.

        The provided path can point to either the root directory of the entire
        package or a specific sub-tool folder.

        Args:
            module_path (str | Path): The directory path containing the __init__.py file.

        Returns:
            str | None: The version string if found, or None if the file is missing,
                        the variable is undefined, or an error occurs.
        """

        init_path = Path(module_path) / "__init__.py"
        if not init_path.exists():
            logger.debug(f'No __init__.py found at "{init_path}".')
            return None
        try:
            values = cls._literal_assignments(init_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, SyntaxError) as e:
            logger.warning(f'Unable to read version from "{init_path}". Issue: {e}')
            return None
        version = cls._version_from(values)
        if version is None:
            logger.warning(f'"__version__" not found in "{init_path}".')
        return version

    @staticmethod
    def _literal_assignments(source: str) -> dict:
        """name -> value of every top-level `name = <literal>` in `source`."""
        values = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    values[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:  # not a plain value (an expression, a call): skipped
                    continue
        return values

    @staticmethod
    def _version_from(values: dict) -> str | None:
        version = values.get("__version__")
        if isinstance(version, str):
            return version
        numbers = values.get("__version_tuple__")
        if isinstance(numbers, tuple) and numbers and all(isinstance(n, int) for n in numbers):
            suffix = values.get("__version_suffix__", "")
            return ".".join(str(n) for n in numbers) + (suffix if isinstance(suffix, str) else "")
        return None
