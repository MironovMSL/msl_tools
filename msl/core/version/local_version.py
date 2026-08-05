# core/version/local_version.py
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalVersionReader:
    """Reads the __version__ string from an __init__.py file at any given path.

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
            spec = importlib.util.spec_from_file_location("msl_version_check", init_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            version = getattr(module, "__version__", None)
            if version is None:
                logger.warning(f'"__version__" not found in "{init_path}".')
            return version
        except Exception as e:
            logger.warning(f'Unable to read version from "{init_path}". Issue: {e}')
            return None
