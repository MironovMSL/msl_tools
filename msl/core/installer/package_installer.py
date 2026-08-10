from dataclasses import dataclass
from pathlib import Path
import logging

from msl_tools.msl.core.fs.files import Files
from msl_tools.msl.core.fs.paths import Paths


@dataclass(frozen=True)
class PackageInstallConfig:
    """Static configuration describing how a package is installed and
    registered as a Maya startup entry point.

    Attributes:
        package_name: Display / folder name of the package on disk, e.g. "msl_tools".
        main_module: Name of the importable package, e.g. "msl".
        required_dirs: Sub-folders that must exist inside `main_module` for the
            install to be considered valid (used by `check_installation_integrity`).
        entry_line: Plain Python statement written into `userSetup.py`, e.g.
            'import msl; msl.bootstrap()'. Must be valid Python — userSetup.py is
            executed as a regular Python module by Maya, NOT as MEL. Do not wrap
            it in a MEL `python("...")` call.
        user_setup_filename: Target filename inside each Maya "scripts" folder.
            Defaults to "userSetup.py" (Python entry point, not "userSetup.mel").
    """
    package_name: str
    main_module: str
    required_dirs: list[str]
    entry_line: str
    user_setup_filename: str = "userSetup.py"


class PackageInstaller:
    """Installs/uninstalls the package on the local filesystem: copies package
    files, registers/removes the startup entry point in every discovered
    userSetup.py, and verifies installation integrity.

    UI-agnostic — intended to be driven by an installer tool that decides when
    to call these methods. Every public method returns False/[]/0 on failure
    and logs a warning instead of raising, so failures never propagate as
    exceptions to the caller.
    """

    def __init__(self,
                 config: PackageInstallConfig,
                 logger: logging.Logger | None = None,
                 files: Files | None = None):

        self.config  = config
        self._logger = logger or logging.getLogger(__name__)
        self._files  = files or Files(logger=self._logger)

    # --- Entry point management (userSetup.py) ---

    def add_entry_line(self, file_path: str | Path, create_missing_file: bool = True) -> bool:
        """Ensures `config.entry_line` is present in the given userSetup.py.

        Idempotent: if the exact line is already present, this is a no-op
        success. Delegates the actual line matching/writing to `File.add_line`
        so behavior stays consistent with the rest of the codebase (exact-line
        match, not a prefix match).

        Args:
            file_path: Path to the target userSetup.py.
            create_missing_file: If True and the file doesn't exist yet, it will
                be created — but only when its parent directory already exists.
                Parent directories are never created implicitly.

        Returns:
            True if the entry line is present in the file after this call,
            False if the file is missing (and wasn't allowed/able to be created)
            or the write failed.
        """
        file_path = Path(file_path)
        file = self._files(file_path)

        if not file.exists:
            if not create_missing_file or not file_path.parent.is_dir():
                self._logger.warning(f'Unable to add entry line. Missing file: "{file_path}".')
                return False

        added_or_present = file.add_line(self.config.entry_line)
        return added_or_present or file.contains_exact_line(self.config.entry_line)

    def remove_entry_line(self, file_path: str | Path, line_to_remove: str,
                           delete_empty_file: bool = True) -> bool:
        """Removes an exact-match line from the given userSetup.py.

        Args:
            file_path: Path to the target userSetup.py.
            line_to_remove: Exact line content to remove (usually `config.entry_line`).
            delete_empty_file: If True, deletes the file once it becomes empty
                (whitespace-only) after removal.

        Returns:
            True if the line was found and removed, False if the file is
            missing or the line wasn't present.
        """
        file = self._files(file_path)
        if not file.exists:
            self._logger.warning(f'Unable to remove entry line. Missing file: "{file_path}".')
            return False

        removed = file.remove_line(line_to_remove)

        if delete_empty_file and file.is_empty:
            try:
                file.path.unlink(missing_ok=True)
            except Exception as e:
                self._logger.debug(f"Unable to delete empty file. Issue: {e}")

        return removed

    def add_entry_point_to_all_installs(self) -> bool:
        """Adds the entry point to every discovered userSetup.py across all
        installed Maya versions.

        Returns:
            True only if the entry point was successfully added to ALL
            discovered files (and at least one was found).
        """
        paths = self._generate_user_setup_paths(only_existing=False)
        if not paths:
            return False  # nothing to process is treated as a failed operation

        return all(self.add_entry_line(path) for path in paths)

    def remove_entry_point_from_all_installs(self) -> bool:
        """Removes the entry point from every existing userSetup.py across all
        installed Maya versions.

        Returns:
            True if no userSetup.py raised an unexpected error while being
            processed (files that never had the entry point are not an error).
        """
        paths = self._generate_user_setup_paths(only_existing=True)
        if not paths:
            return True  # nothing installed means nothing to remove — not a failure

        success = True
        for path in paths:
            try:
                self.remove_entry_line(path, self.config.entry_line)
            except Exception as e:
                self._logger.warning(f'Unexpected failure removing entry line from "{path}". Issue: {e}')
                success = False
        return success

    def _generate_user_setup_paths(self, only_existing: bool = False) -> list[Path]:
        """Resolves userSetup.py paths across all discovered Maya preference
        folders.

        Args:
            only_existing: If True, only paths to files that already exist on
                disk are returned. If False, paths are returned regardless of
                whether the file exists yet (used when adding an entry point).

        Returns:
            List of candidate/existing userSetup.py paths, one per discovered
            Maya version. Empty list if no Maya preferences were found.
        """
        from msl_tools.msl.core.fs.maya_paths import MayaPaths
        preferences = MayaPaths.get_available_preferences(use_maya_commands=True)
        self._logger.debug(f"Discovered Maya preferences: {preferences}")

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
        """Verifies that an installed main module folder contains all
        `config.required_dirs`.

        Args:
            main_module: Path to the installed main module folder,
                e.g. ".../msl_tools/msl". Accepts str or Path.

        Returns:
            True if the folder exists and contains every required sub-folder,
            False otherwise.
        """
        main_module = Path(main_module)

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
        """Removes a previously installed package from `target_path`.

        Deletes the main module folder (`target_path/config.main_module`), and
        optionally "configs"/"logs" folders alongside it. If `target_path`
        itself becomes empty as a result, it is removed too.

        Args:
            target_path: Package root on the target side, e.g. ".../msl_tools".
            clear_prefs: If True, also removes "configs" and "logs" sub-folders.

        Returns:
            True if everything that existed was removed successfully (a
            missing `target_path` is treated as success — nothing to delete).
        """
        target_path = Path(target_path)
        if not target_path.exists():
            return True  # nothing to delete is not an error

        success = True

        module_path = target_path / self.config.main_module  # .../msl_tools/msl
        if module_path.exists():
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

        if target_path.exists() and not any(target_path.iterdir()):  # delete package root if now empty
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
                         clear_prefs: bool = False) -> bool:
        """Performs a full install: removes any previous install, copies the
        new package files, verifies integrity, and registers the entry point
        in every discovered userSetup.py.

        Args:
            source_path: Parent folder that CONTAINS the package folder, i.e.
                `source_path/config.package_name` must exist
                (e.g. source_path=".../MSL_Others" when the package lives at
                ".../MSL_Others/msl_tools").
            target_path: Parent folder the package should be installed into,
                using the same convention as `source_path`
                (e.g. ".../Documents/maya/scripts").
            clear_prefs: If True, also wipes "configs"/"logs" from a previous
                install before copying the new one.

        Returns:
            True if the package was copied, passed the integrity check, and
            the entry point was registered everywhere. False on any failure
            (see logged warnings for the specific reason).
        """
        source_path         = Path(source_path)
        source_package_path = source_path / self.config.package_name         # .../msl_tools
        source_main_path    = source_package_path / self.config.main_module  # .../msl_tools/msl

        target_path         = Path(target_path)
        target_package_path = target_path / self.config.package_name         # .../msl_tools
        target_main_path    = target_package_path / self.config.main_module  # .../msl_tools/msl

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

        if not self.add_entry_point_to_all_installs():
            self._logger.warning('Package files installed, but entry point registration failed for one or more installs.')
            return False

        self._logger.debug(f'Package "{self.config.package_name}" installed to "{target_path}".')
        return True

    def uninstall_package(self,
                           target_path: str | Path,
                           clear_prefs: bool = True) -> bool:
        """Performs a full uninstall: removes the entry point from every
        userSetup.py and deletes the package files.

        Args:
            target_path: Parent folder the package is installed into, using
                the same convention as `install_package`'s `target_path`.
            clear_prefs: If True, also removes "configs"/"logs" folders.

        Returns:
            True if both the entry point removal and file cleanup succeeded.
        """
        target_path = Path(target_path)
        target_package_path = target_path / self.config.package_name  # .../msl_tools

        entry_removed = self.remove_entry_point_from_all_installs()
        files_removed = self.remove_previous_install(target_package_path, clear_prefs=clear_prefs)

        if entry_removed and files_removed:
            self._logger.debug(f'Package "{self.config.package_name}" uninstalled from "{target_package_path}".')
        else:
            self._logger.warning(f'Uninstall of "{self.config.package_name}" completed with errors.')

        return entry_removed and files_removed

    def extract_archive(self, archive_path: str | Path, destination: str | Path,
                         remove_archive: bool = False) -> bool:
        """Extracts a package archive downloaded from GitHub into `destination`.

        GitHub release/source archives wrap their contents in a single root
        folder (e.g. "msl_tools-main/"); this unwraps that root folder so its
        contents land directly inside `destination` instead of one level
        deeper.

        Args:
            archive_path: Path to the downloaded archive file.
            destination: Folder the archive contents should be extracted into.
            remove_archive: If True, deletes the archive file after a
                successful extraction.

        Returns:
            True if the archive was extracted successfully, False otherwise.
        """
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
            # GitHub wraps contents in a single root folder — unwrap it.
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
    config = PackageInstallConfig(
        package_name="msl_tools",
        main_module="msl",
        required_dirs=["core", "tools", "ui", "assets"],
        entry_line="import msl; msl.bootstrap()",
    )

    source_path = Path(r"H:\ProjectsDev\MSL_Others")
    target_path = Path(r"H:\ProjectsDev\Temp")

    package_installer = PackageInstaller(config)

    print(package_installer.install_package(source_path, target_path))
    # print(package_installer.uninstall_package(target_path))

    # TODO: get_available_preferences — need to support an additional custom
    #       Maya prefs path for machines with a non-standard prefs location.