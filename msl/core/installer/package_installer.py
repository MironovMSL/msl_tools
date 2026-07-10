from dataclasses import dataclass
from pathlib import Path
import logging

from msl_tools.msl.core.fs.files import Files


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

    def __init__(self, config: PackageInstallConfig, *,
                 logger: logging.Logger | None = None,
                 files: Files | None = None):
        self.config = config
        self._logger = logger or logging.getLogger(__name__)
        self._files = files or Files(logger=self._logger)

    # --- Entry point management (userSetup.mel) ---

    def add_entry_line(self, file_path: str | Path, create_missing_file: bool = True) -> bool:
        file_path = Path(file_path)
        entry = self.config.entry_line
        file = self._files(file_path)

        if not file.exists:
            # Сохраняем текущее поведение: не создаём вложенные директории молча
            if not create_missing_file or not file_path.parent.is_dir():
                self._logger.warning(f'Unable to add entry line. Missing file: "{file_path}".')
                return False
            return file.write(entry + "\n")

        lines = file.read_lines()
        if any(line.startswith(entry) for line in lines):
            return True  # уже присутствует, идемпотентно

        lines.append(entry)
        return file.write_lines(lines)

    def remove_entry_line(self, file_path: str | Path, line_to_remove: str,
                           delete_empty_file: bool = True) -> int:
        file = self._files(file_path)
        if not file.exists:
            self._logger.warning(f'Unable to remove entry line. Missing file: "{file_path}".')
            return 0

        lines = file.read_lines()
        remaining = [line for line in lines if not line.startswith(line_to_remove)]
        removed_count = len(lines) - len(remaining)

        if removed_count > 0:
            file.write_lines(remaining)

        if delete_empty_file and not any(line.strip() for line in remaining):
            try:
                file.path.unlink(missing_ok=True)
            except Exception as e:
                self._logger.debug(f"Unable to delete empty file. Issue: {e}")

        return removed_count

        # --- Entry point management (userSetup.mel) ---

    def add_entry_point_to_all_installs(self) -> bool:
        """Возвращает True, только если entry point успешно добавлен во ВСЕ найденные userSetup."""
        paths = self._generate_user_setup_paths(only_existing=False)
        if not paths:
            return False  # нечего было обрабатывать — считаем это неуспехом операции

        return all(self.add_entry_line(path) for path in paths)

    def remove_entry_point_from_all_installs(self) -> bool:
        """Возвращает True, если ни один userSetup не вызвал ошибку при обработке."""
        paths = self._generate_user_setup_paths(only_existing=True)
        if not paths:
            return True  # нет установленных userSetup — удалять нечего, это не ошибка

        success = True
        for path in paths:
            try:
                self.remove_entry_line(path, self.config.entry_line)
            except Exception as e:
                self._logger.warning(f'Unexpected failure removing entry line from "{path}". Issue: {e}')
                success = False
        return success


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

    def remove_previous_install(self, target_path: str | Path, clear_prefs: bool = False) -> bool:
        from msl_tools.msl.core.fs.paths import Paths
        target_path = Path(target_path)
        if not target_path.exists():
            return True  # нечего удалять — это не ошибка

        success = True

        module_path = target_path / self.config.main_module
        if module_path.exists():
            self._logger.debug(f'Removing previous install: "{module_path}"')
            try:
                Paths.delete(module_path)
            except Exception as e:
                self._logger.warning(f'Unable to remove "{module_path}". Issue: {e}')
                success = False

        if clear_prefs:
            prefs_path = target_path / f"{self.config.main_module}_prefs"  # уточнить фактическое имя папки префов
            if prefs_path.exists():
                self._logger.debug(f'Removing previous preferences: "{prefs_path}"')
                try:
                    Paths.delete(prefs_path)
                except Exception as e:
                    self._logger.warning(f'Unable to remove "{prefs_path}". Issue: {e}')
                    success = False

        if target_path.exists() and not any(target_path.iterdir()):
            try:
                Paths.delete(target_path)
            except Exception as e:
                self._logger.warning(f'Unable to remove empty "{target_path}". Issue: {e}')
                success = False

        return success

    # --- High-level install / uninstall ---

    def install_package(self, source_path: str | Path, target_path: str | Path,
                         clear_prefs: bool = False) -> bool:
        """Полная установка: удаление старой версии, копирование новой,
        проверка целостности, регистрация entry point во всех userSetup."""
        from msl_tools.msl.core.fs.paths import Paths

        source_path = Path(source_path)
        target_path = Path(target_path)

        if not source_path.is_dir():
            self._logger.warning(f'Unable to install. Missing source folder: "{source_path}".')
            return False

        if not self.remove_previous_install(target_path, clear_prefs=clear_prefs):
            self._logger.warning(f'Unable to fully remove previous install at "{target_path}". Aborting.')
            return False

        try:
            Paths.copy(source_path, target_path)
        except Exception as e:
            self._logger.warning(f'Unable to copy package to "{target_path}". Issue: {e}')
            return False

        if not self.check_installation_integrity(target_path):
            self._logger.warning(f'Installation integrity check failed for "{target_path}".')
            return False

        if not self.add_entry_point_to_all_installs():
            self._logger.warning('Package files installed, but entry point registration failed for one or more installs.')
            return False

        self._logger.debug(f'Package "{self.config.package_name}" installed to "{target_path}".')
        return True

    def uninstall_package(self, target_path: str | Path, clear_prefs: bool = False) -> bool:
        """Полное удаление: снятие entry point из всех userSetup, удаление файлов пакета."""
        entry_removed = self.remove_entry_point_from_all_installs()
        files_removed = self.remove_previous_install(target_path, clear_prefs=clear_prefs)

        if entry_removed and files_removed:
            self._logger.debug(f'Package "{self.config.package_name}" uninstalled from "{target_path}".')
        else:
            self._logger.warning(f'Uninstall of "{self.config.package_name}" completed with errors.')

        return entry_removed and files_removed

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

    def extract_archive(self, archive_path: str | Path, destination: str | Path,
                        remove_archive: bool = False) -> bool:
        """Распаковывает скачанный с GitHub архив пакета в целевую папку.
        Разворачивает единственный корневой каталог архива (например, "msl_tools-main")
        напрямую в destination, а не оставляет его вложенным."""
        from msl_tools.msl.core.fs.paths import Paths
        import tempfile

        archive_path = Path(archive_path)
        destination = Path(destination)

        if not archive_path.is_file():
            self._logger.warning(f'Unable to extract archive. Missing file: "{archive_path}".')
            return False

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            if not Paths.extract(archive_path, tmp_dir):
                self._logger.warning(f'Unable to unpack archive: "{archive_path}".')
                return False

            extracted_items = list(tmp_dir.iterdir())
            # GitHub оборачивает содержимое в один корневой каталог — разворачиваем его
            source_root = extracted_items[0] if len(extracted_items) == 1 and extracted_items[0].is_dir() else tmp_dir

            for item in source_root.iterdir():
                target = destination / item.name
                if target.exists() and not Paths.delete(target):
                    self._logger.warning(f'Unable to overwrite existing item: "{target}".')
                    return False
                Paths.copy(item, target)

        if remove_archive:
            Paths.delete(archive_path)

        return True


if __name__ == "__main__":
    from msl_tools.msl.core.fs.paths import Paths

    config = PackageInstallConfig(
        package_name="msl-tools",
        main_module="msl",
        required_dirs=["core", "tools", "ui"],
        entry_line='python("import msl; msl.bootstrap()")'
    )
    package_installer = PackageInstaller(config)
    local_version = package_installer.get_local_version(Paths.ROOT_DIR)
    print(local_version)