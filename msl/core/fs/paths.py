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


class Paths:
    # 1. Корректно вычисляем корень проекта
    ROOT_DIR = Path(__file__).resolve().parents[3]

    # 2. Переменные класса объявляем через корень класса
    msl    = ROOT_DIR / 'msl'
    core   = ROOT_DIR / 'msl' / 'core'
    config = ROOT_DIR / 'msl' / 'config'
    tools  = ROOT_DIR / 'msl' / 'tools'
    logs   = ROOT_DIR / 'msl' / 'logs'

    @staticmethod
    def make_dir(path: str | Path) -> Path:
        """Создает папку и всю цепочку родителей."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def make_file(path: str | Path) -> Path:
        """Создает файл и родительские папки, если их нет."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    @staticmethod
    def delete(path: str | Path) -> bool:
        """Безопасно удаляет файл или папку со всем содержимым."""
        path = Path(path)

        if not path.exists():
            return False

        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)  # Игнорируем ошибки занятых файлов

        return True

    @staticmethod
    def exists(path: str | Path) -> bool:
        """Проверяет существование пути."""
        return Path(path).exists()

    @staticmethod
    def list_dirs(path: str | Path, recursive: bool = True) -> list[Path]:
        """Возвращает список только директорий внутри указанного пути."""
        path = Path(path)

        # Защита от падения, если директории не существует
        if not path.is_dir():
            return []

        generator = path.rglob('*') if recursive else path.iterdir()
        return [p for p in generator if p.is_dir()]

    @staticmethod
    def copy(src: str | Path, dst: str | Path) -> Path:
        """Копирует файл или дерево папок."""
        src, dst = Path(src), Path(dst)
        if src.is_dir():
            return Path(shutil.copytree(src, dst, dirs_exist_ok=True))
        return Path(shutil.copy2(src, dst))

    @staticmethod
    def move(src: str | Path, dst: str | Path) -> Path:
        """Перемещает файл или папку."""
        return Path(shutil.move(str(src), str(dst)))


if __name__ == '__main__':
    # Теперь класс вызывается статически — создавать экземпляр через () не нужно!
    print("Корень проекта:", Paths.ROOT_DIR)
    print("Папка логов:", Paths.logs)

    # Построение динамических путей работает идеально
    manager_path = Paths.core / "config" / "manager.py"
    print("Путь к менеджеру:", manager_path)

    # Пример безопасной работы с методами
    temp_dir_log = Paths.logs / "temp_debug" / "log.log"
    # Paths.make_dir(temp_dir)
    Paths.make_file(temp_dir_log)
    print("Создана папка:", temp_dir_log.exists())

    temp_dir = Paths.logs / "temp_debug"
    Paths.delete(temp_dir)
    print("Папка удалена:", not temp_dir.exists())
