from dataclasses import dataclass
from pathlib import Path
import logging

from msl_tools.msl.core.fs.files import Files
from msl_tools.msl.core.fs.paths import Paths


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

    def __init__(self,
                 config: PackageInstallConfig,
                 logger: logging.Logger | None = None,
                 files: Files | None = None):

        self.config  = config
        self._logger = logger or logging.getLogger(__name__)
        self._files  = files or Files(logger=self._logger)

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

    def remove_entry_line(self, file_path: str | Path, line_to_remove: str, delete_empty_file: bool = True) -> int:
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
            return False  # there was nothing to process - we consider this a failure of the operation

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
        print(preferences)
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

    def check_installation_integrity(self, main_module: str | Path) -> bool:

        if not main_module.is_dir():
            self._logger.warning(f'Missing main module folder: "{main_module}"')
            return False

        module_contents = {p.name for p in main_module.iterdir()}
        missing         = [d for d in self.config.required_dirs if d not in module_contents]

        if missing:
            self._logger.warning(f'Missing required elements: {", ".join(missing)}')
            return False
        return True

    # --- Copy / cleanup ---

    def remove_previous_install(self, target_path: str | Path, clear_prefs: bool = False) -> bool:

        target_path = Path(target_path)
        if not target_path.exists():
            return True  # nothing to delete is not an error

        success = True

        module_path = target_path / self.config.main_module # .../msl module
        if module_path.exists(): # delete module .../msl
            self._logger.debug(f'Removing previous install: "{module_path}"')
            try:
                Paths.delete(module_path)
            except Exception as e:
                self._logger.warning(f'Unable to remove "{module_path}". Issue: {e}')
                success = False

        if clear_prefs:
            configs_path = target_path / "configs"
            if configs_path.exists():
                self._logger.debug(f'Removing previous configs: "{configs_path}"')
                try:
                    Paths.delete(configs_path)
                except Exception as e:
                    self._logger.warning(f'Unable to remove "{configs_path}". Issue: {e}')
                    success = False

            logs_path = target_path / "logs"
            if logs_path.exists():
                self._logger.debug(f'Removing previous logs: "{logs_path}"')
                try:
                    Paths.delete(logs_path)
                except Exception as e:
                    self._logger.warning(f'Unable to remove "{logs_path}". Issue: {e}')
                    success = False

        if target_path.exists() and not any(target_path.iterdir()): # delete package .../msl_tools if it's empty
            try:
                Paths.delete(target_path)
            except Exception as e:
                self._logger.warning(f'Unable to remove empty "{target_path}". Issue: {e}')
                success = False

        return success

    # --- High-level install / uninstall ---

    def install_package(self,
                        source_path: str | Path,
                        target_path: str | Path,
                        clear_prefs:       bool = False) -> bool:
        """Полная установка: удаление старой версии, копирование новой,
        проверка целостности, регистрация entry point во всех userSetup.
        source_path: exemple source path  '...\...\...\...' without \msl_tools
        target_path: exemple any path 'C:\\Users\\s_mironov\\Documents\\maya\\scripts' without \\msl_tools."""



        source_path         = Path(source_path)
        source_package_path = source_path / self.config.package_name  # .../msl_tools
        source_main_path    = source_package_path / self.config.main_module  # .../msl_tools/msl

        target_path         = Path(target_path)
        target_package_path = target_path / self.config.package_name # .../msl_tools
        target_main_path    = target_package_path / self.config.main_module # .../msl_tools/msl

        if not source_package_path.is_dir():
            self._logger.warning(f'Unable to install. Missing source folder: "{source_package_path}".')
            return False

        if not self.remove_previous_install(target_package_path, clear_prefs=clear_prefs):
            self._logger.warning(f'Unable to fully remove previous install at "{target_path}". Aborting.')
            return False

        try:
            Paths.copy(source_main_path, target_main_path)
        except Exception as e:
            self._logger.warning(f'Unable to copy package to "{target_main_path}". Issue: {e}')
            return False

        if not self.check_installation_integrity(target_main_path):
            self._logger.warning(f'Installation integrity check failed for "{target_main_path}".')
            return False

        #TODO need check when I will have entry point loine to install to useSetaup.py
        if not self.add_entry_point_to_all_installs():
            self._logger.warning('Package files installed, but entry point registration failed for one or more installs.')
            return False

        self._logger.debug(f'Package "{self.config.package_name}" installed to "{target_path}".')
        return True

    def uninstall_package(self,
                          target_path: str | Path,
                          clear_prefs: bool = True) -> bool:

        """Полное удаление: снятие entry point из всех userSetup, удаление файлов пакета."""
        target_path = Path(target_path)
        target_package_path = target_path / self.config.package_name # .../msl_tools

        entry_removed = self.remove_entry_point_from_all_installs()
        files_removed = self.remove_previous_install(target_package_path, clear_prefs=clear_prefs)

        if entry_removed and files_removed:
            self._logger.debug(f'Package "{self.config.package_name}" uninstalled from "{target_package_path}".')
        else:
            self._logger.warning(f'Uninstall of "{self.config.package_name}" completed with errors.')

        return entry_removed and files_removed

    def extract_archive(self, archive_path: str | Path, destination: str | Path, remove_archive: bool = False) -> bool:
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
        package_name="msl_tools",
        main_module="msl",
        required_dirs=["core", "tools", "ui", "assets"],
        entry_line='python("import msl; msl.bootstrap()")'
    )

    source_path = Path(r"H:\ProjectsDev\MSL_Others")
    # target_path = r"C:\Users\s_mironov\Documents\maya\scripts"
    target_path = Path(r"H:\ProjectsDev\Temp")


    package_installer = PackageInstaller(config)

    print(package_installer.install_package(source_path, target_path))
    # print(package_installer.uninstall_package(target_path))

    #TODO get_available_preferences  need add path if you have another pref maya path.
    #TODO clear prefs I need create sinle function for clear preferences (configs and log)




