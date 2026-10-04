# pathlib import Path

# Creating a path object (adapts to Windows or Linux/Mac automatically)
# p = Path("docs") / "reports" / "2026" / "budget.xlsx"
#
# print(p.name)      # 'budget.xlsx' (full file name)
# print(p.stem)      # 'budget'      (name without extension)
# print(p.suffix)    # '.xlsx'       (extension only)
# print(p.parent)    # docs/reports/2026 (parent folder)
# print(p.anchor)    # '/' or 'C:\' (drive root)
# Use code with caution.Checks and propertiespythonp = Path("data/info.txt")
#
# print(p.exists())       # True if the file or folder exists
# print(p.is_file())      # True if it is a file
# print(p.is_dir())       # True if it is a folder
# print(p.is_absolute())  # True if the path is absolute (from the drive root)
# Use code with caution.Creating, deleting and movingpythonp = Path("my_project/src/main.py")
#
# # 1. Creating folders (parents=True creates the whole chain, exist_ok=True raises no error if the folder exists)
# p.parent.mkdir(parents=True, exist_ok=True)
#
# # 2. Creating an empty file
# p.touch(exist_ok=True)
#
# # 3. Renaming or moving a file
# new_path = p.with_name("app.py") # Changes only the name in the path object: 'my_project/src/app.py'
# p.rename(new_path)                # Actually renames it on disk
#
# # 4. Deleting
# # new_path.unlink()               # Delete a file
# # p.parent.rmdir()                # Delete an empty folder
# Use code with caution.Reading and writing files (without open())pythonp = Path("note.txt")
#
# # Quick text write (overwrites the file)
# p.write_text("Hello, world!", encoding="utf-8")
#
# # Quick text read
# content = p.read_text(encoding="utf-8")
# print(content) # 'Hello, world!'
#
# # There are also p.read_bytes() and p.write_bytes() for binary data
# Use code with caution.Finding files and walking folderspythonfolder = Path("my_project")
#
# # Collect every item in the folder (without going into subfolders)
# for item in folder.iterdir():
#     print(item)
#
# # Search by pattern (in the current folder only)
# for txt_file in folder.glob("*.txt"):
#     print(txt_file)
#
# # Recursive search (in the current folder and all subfolders)
# for any_py_file in folder.rglob("*.py"):
#     print(any_py_file)

"""
Class of paths
"""

from pathlib import Path
import shutil


class Paths:
    # --- generic user dirs (stdlib fallback, no Qt) ---

    @classmethod
    def get_home_dir(cls) -> Path:
        return Path.home()

    @classmethod
    def get_desktop_dir(cls) -> Path:
        return cls.get_home_dir() / "Desktop"

    @classmethod
    def get_temp_dir(cls) -> Path:
        import tempfile
        return Path(tempfile.gettempdir())

    # --- filesystem operations ---

    @classmethod
    def make_dir(cls, path: str | Path) -> Path:
        """Creates the folder and its whole chain of parents."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def make_file(cls, path: str | Path) -> Path:
        """Creates the file and any missing parent folders."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    @classmethod
    def delete(cls, path: str | Path) -> bool:
        """Safely deletes a file, or a folder with everything in it."""
        path = Path(path)
        if not path.exists():
            return False
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            return True
        except Exception:
            return False

    @classmethod
    def exists(cls, path: str | Path) -> bool:
        return Path(path).exists()

    @classmethod
    def list_dirs(cls, path: str | Path, recursive: bool = True) -> list[Path]:
        """Returns only the directories inside the given path."""
        path = Path(path)
        if not path.is_dir():
            return []
        generator = path.rglob('*/') if recursive else (p for p in path.iterdir() if p.is_dir())
        return list(generator)

    @classmethod
    def copy(cls, src: str | Path, dst: str | Path) -> Path:
        """Copies a file or a folder tree and returns the new path."""
        src, dst = Path(src), Path(dst)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return dst

    @classmethod
    def move(cls, src: str | Path, dst: str | Path) -> Path:
        """Moves a file or folder and returns the new path."""
        src, dst = Path(src), Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst

    @classmethod
    def extract(cls, archive_path: str | Path, destination: str | Path) -> bool:
        """Unpacks a zip/tar archive into the given folder."""
        archive_path, destination = Path(archive_path), Path(destination)
        if not archive_path.is_file():
            return False
        try:
            destination.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(archive_path), str(destination))
            return True
        except Exception:
            return False




if __name__ == '__main__':
    # Demo of Paths' own helpers. OS detection lives in SystemInfo; the project's
    # folders (root, logs, core, ...) live on FileSystemManager, not here.
    from msl_tools.msl.core.fs.system_info import SystemInfo

    print("System:", SystemInfo.get_system())
    print("Home:", Paths.get_home_dir())
    print("Temp:", Paths.get_temp_dir())

    temp_dir = Paths.get_temp_dir() / "msl_paths_demo"
    temp_file = temp_dir / "log.log"
    Paths.make_file(temp_file)
    print("File created:", temp_file.exists())

    Paths.delete(temp_dir)
    print("Folder deleted:", not temp_dir.exists())
