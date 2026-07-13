# core/version/local_version.py
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalVersionReader:
    """Читает __version__ из __init__.py по произвольному пути. Только чтение, без состояния."""

    @classmethod
    def get_version(cls, module_path: str | Path) -> str | None:
        """module_path — папка, содержащая __init__.py с переменной __version__.
        Может быть как корнем всего пакета, так и папкой отдельного инструмента."""
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