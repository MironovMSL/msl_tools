from dataclasses import dataclass
from pathlib import Path
import logging


@dataclass(frozen=True)
class PackageInstallConfig:
    package_name: str              # "msl_tools" — для отображения/логов
    main_module: str                # "msl" — имя импортируемого пакета
    required_dirs: list[str]        # ["core", "tools", "ui"] — код, который обязан быть внутри main_module
    entry_line: str                  # 'python("import msl; msl.bootstrap()");'
    user_setup_filename: str = "userSetup.py"
    legacy_entry_line: str | None = None


class PackageInstaller:
    """Установка/удаление пакета из системы: entry point в userSetup, копирование файлов, проверка целостности.
    Не знает о UI — используется installer-инструментом, который решает, когда вызывать эти методы."""

    def __init__(self, config: PackageInstallConfig, *, logger: logging.Logger | None = None):
        self.config = config
        self._logger = logger or logging.getLogger(__name__)

    # --- Entry point management (userSetup.mel) ---

    def add_entry_line(self, file_path: str | Path, create_missing_file: bool = True) -> bool:
        file_path = Path(file_path)
        entry = self.config.entry_line

        if not file_path.exists():
            if not create_missing_file or not file_path.parent.is_dir():
                self._logger.warning(f'Unable to add entry line. Missing file: "{file_path}".')
                return False
            file_path.write_text(entry + "\n", encoding="utf-8")
            return True

        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if any(line.startswith(entry) for line in lines):
            return True  # уже присутствует, идемпотентно

        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(entry + "\n")
        file_path.write_text("".join(lines), encoding="utf-8")
        return True

    def remove_entry_line(self, file_path: str | Path, line_to_remove: str,
                           delete_empty_file: bool = True) -> int:
        file_path = Path(file_path)
        if not file_path.exists():
            self._logger.warning(f'Unable to remove entry line. Missing file: "{file_path}".')
            return 0

        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        remaining = [line for line in lines if not line.startswith(line_to_remove)]
        removed_count = len(lines) - len(remaining)

        if removed_count > 0:
            file_path.write_text("".join(remaining), encoding="utf-8")

        if delete_empty_file and "".join(remaining).strip() == "":
            try:
                file_path.unlink(missing_ok=True)
            except Exception as e:
                self._logger.debug(f"Unable to delete empty file. Issue: {e}")

        return removed_count

    def add_entry_point_to_all_installs(self) -> None:
        for user_setup_path in self._generate_user_setup_paths(only_existing=False):
            self.add_entry_line(user_setup_path)

    def remove_entry_point_from_all_installs(self) -> None:
        for user_setup_path in self._generate_user_setup_paths(only_existing=True):
            self.remove_entry_line(user_setup_path, self.config.entry_line)

    def _generate_user_setup_paths(self, only_existing: bool = False) -> list[Path]:
        from msl_tools.msl.core.fs.maya_paths import MayaPaths
        preferences = MayaPaths.get_available_preferences(use_maya_commands=True)
        if not preferences:
            self._logger.warning("Unable to generate userSetup paths. No Maya preferences found.")
            return []

        result = []
        for version, prefs_dir in preferences.items():
            scripts_dir = prefs_dir / "scripts"
            if not scripts_dir.is_dir():
                continue
            user_setup_path = scripts_dir / self.config.user_setup_filename
            if only_existing and not user_setup_path.exists():
                continue
            result.append(user_setup_path)
        return result

    # --- Integrity check ---

    def check_installation_integrity(self, package_target_folder: str | Path) -> bool:
        package_target_folder = Path(package_target_folder)
        if not package_target_folder.is_dir():
            return False

        module_dir = package_target_folder / self.config.main_module
        if not module_dir.is_dir():
            self._logger.warning(f'Missing main module folder: "{module_dir}"')
            return False

        module_contents = {p.name for p in module_dir.iterdir()}
        missing = [d for d in self.config.required_dirs if d not in module_contents]
        if missing:
            self._logger.warning(f'Missing required elements: {", ".join(missing)}')
            return False
        return True

    # --- Copy / cleanup ---

    def remove_previous_install(self, target_path: str | Path, clear_prefs: bool = False) -> None:
        from msl_tools.msl.core.fs.paths import Paths
        target_path = Path(target_path)
        if not target_path.exists():
            return

        module_path = target_path / self.config.main_module
        if module_path.exists():
            self._logger.debug(f'Removing previous install: "{module_path}"')
            Paths.delete(module_path)

        if clear_prefs:
            prefs_path = target_path / f"{self.config.main_module}_prefs"  # уточнить фактическое имя папки префов
            if prefs_path.exists():
                self._logger.debug(f'Removing previous preferences: "{prefs_path}"')
                Paths.delete(prefs_path)

        if target_path.exists() and not any(target_path.iterdir()):
            Paths.delete(target_path)

    def get_local_version(self, package_root: str | Path) -> str | None:
        """Читает __version__ из __init__.py установленного пакета."""
        import importlib.util
        init_path = Path(package_root) / self.config.main_module / "__init__.py"
        if not init_path.exists():
            self._logger.debug(f'No __init__.py found at "{init_path}".')
            return None
        try:
            spec = importlib.util.spec_from_file_location("msl_version_check", init_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            version = getattr(module, "__version__", None)
            if version is None:
                self._logger.warning(f'"__version__" not found in "{init_path}".')
            return version
        except Exception as e:
            self._logger.warning(f'Unable to read version from "{init_path}". Issue: {e}')
            return None