# pathlib import Path

# Создание объекта пути (автоматически адаптируется под Windows или Linux/Mac)
# p = Path("docs") / "reports" / "2026" / "budget.xlsx"
#
# print(p.name)      # 'budget.xlsx' (полное имя файла)
# print(p.stem)      # 'budget'      (имя без расширения)
# print(p.suffix)    # '.xlsx'       (только расширение)
# print(p.parent)    # docs/reports/2026 (родительская папка)
# print(p.anchor)    # '/' или 'C:\' (корень диска)
# Use code with caution.Проверки и свойстваpythonp = Path("data/info.txt")
#
# print(p.exists())       # True, если файл или папка существуют
# print(p.is_file())      # True, если это файл
# print(p.is_dir())       # True, если это папка
# print(p.is_absolute())  # True, если путь абсолютный (от корня диска)
# Use code with caution.Создание, удаление и перемещениеpythonp = Path("my_project/src/main.py")
#
# # 1. Создание папок (parents=True создаст всю цепочку, exist_ok=True не выдаст ошибку, если папка есть)
# p.parent.mkdir(parents=True, exist_ok=True)
#
# # 2. Создание пустого файла
# p.touch(exist_ok=True)
#
# # 3. Переименование или перемещение файла
# new_path = p.with_name("app.py") # Меняет только имя в объекте пути: 'my_project/src/app.py'
# p.rename(new_path)                # Физически переименовывает на диске
#
# # 4. Удаление
# # new_path.unlink()               # Удалить файл
# # p.parent.rmdir()                # Удалить пустую папку
# Use code with caution.Чтение и запись файлов (без использования open())pythonp = Path("note.txt")
#
# # Быстрая запись текста (перезапишет файл)
# p.write_text("Привет, мир!", encoding="utf-8")
#
# # Быстрое чтение текста
# content = p.read_text(encoding="utf-8")
# print(content) # 'Привет, мир!'
#
# # Также есть p.read_bytes() и p.write_bytes() для бинарных данных
# Use code with caution.Поиск файлов и обход папокpythonfolder = Path("my_project")
#
# # Собрать все элементы в папке (без захода в подпапки)
# for item in folder.iterdir():
#     print(item)
#
# # Поиск по маске (только в текущей папке)
# for txt_file in folder.glob("*.txt"):
#     print(txt_file)
#
# # Рекурсивный поиск (в текущей папке и всех подпапках)
# for any_py_file in folder.rglob("*.py"):
#     print(any_py_file)

"""
Сlass of paths
"""

from pathlib import Path
import shutil
import sys


class Paths:
    OS_MAC        = "darwin"
    OS_LINUX      = "linux"
    OS_WINDOWS    = "win32"
    KNOWN_SYSTEMS = (OS_WINDOWS, OS_MAC, OS_LINUX)

    ROOT_DIR = Path(__file__).resolve().parents[3]

    msl     = ROOT_DIR / 'msl'
    core    = msl / 'core'
    configs = msl / 'configs'
    tools   = msl / 'tools'
    logs    = msl / 'logs'

    # --- OS detection ---

    @classmethod
    def get_system(cls) -> str:
        return sys.platform

    @classmethod
    def is_windows(cls) -> bool:
        return cls.get_system() == cls.OS_WINDOWS

    @classmethod
    def is_macos(cls) -> bool:
        return cls.get_system() == cls.OS_MAC

    @classmethod
    def is_linux(cls) -> bool:
        return cls.get_system() == cls.OS_LINUX

    # --- generic user dirs (stdlib fallback, без Qt) ---

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
        """Создает папку и всю цепочку родителей."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def make_file(cls, path: str | Path) -> Path:
        """Создает файл и родительские папки, если их нет."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    @classmethod
    def delete(cls, path: str | Path) -> bool:
        """Безопасно удаляет файл или папку со всем содержимым."""
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
        """Возвращает список только директорий внутри указанного пути."""
        path = Path(path)
        if not path.is_dir():
            return []
        generator = path.rglob('*/') if recursive else (p for p in path.iterdir() if p.is_dir())
        return list(generator)

    @classmethod
    def copy(cls, src: str | Path, dst: str | Path) -> Path:
        """Копирует файл или дерево папок и возвращает новый путь."""
        src, dst = Path(src), Path(dst)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        return dst

    @classmethod
    def move(cls, src: str | Path, dst: str | Path) -> Path:
        """Перемещает файл или папку и возвращает новый путь."""
        src, dst = Path(src), Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return dst

from PySide6 import QtCore
class StandardPaths:

    @classmethod
    def get_home_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.HomeLocation)
        return Path(path) if path else None

    @classmethod
    def get_desktop_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DesktopLocation)
        return Path(path) if path else None

    @classmethod
    def get_documents_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(path) if path else None

    @classmethod
    def get_downloads_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DownloadLocation)
        return Path(path) if path else None

    @classmethod
    def get_pictures_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.PicturesLocation)
        return Path(path) if path else None

    @classmethod
    def get_music_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.MusicLocation)
        return Path(path) if path else None

    @classmethod
    def get_movies_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.MoviesLocation)
        return Path(path) if path else None

    @classmethod
    def get_temp_dir(cls) -> Path | None:
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.TempLocation)
        return Path(path) if path else None


if __name__ == '__main__':
    print(Paths.get_system())
    print("Корень проекта:", Paths.ROOT_DIR)
    print("Папка логов:", Paths.logs)

    manager_path = Paths.core / "config" / "manager.py"
    print("Путь к менеджеру:", manager_path)

    temp_file_log = Paths.logs / "temp_debug" / "log.log"
    Paths.make_file(temp_file_log)
    print("Создан файл:", temp_file_log.exists())

    temp_dir = Paths.logs / "temp_debug"
    Paths.delete(temp_dir)
    print("Папка удалена:", not temp_dir.exists())
