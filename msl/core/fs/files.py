import logging
from pathlib import Path


class Files:
    """Фабрика File-объектов с общим логгером (DI, как остальные core-классы)."""

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)

    def __call__(self, path: str | Path, encoding: str = 'utf-8') -> 'File':
        return File(path, encoding=encoding, logger=self._logger)


class File:
    """Работа с содержимым конкретного файла. Никаких исключений наружу —
    ошибки логируются, методы возвращают False/None/""/[]/0 на неудаче."""

    def __init__(self, path: str | Path, encoding: str = 'utf-8',
                 logger: logging.Logger | None = None) -> None:
        self.path = Path(path)
        self.encoding = encoding
        self._logger = logger or logging.getLogger(__name__)

    def _ensure_dir_exists(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to create directory for "{self.path}". Issue: {e}')
            return False

    def _open(self, mode: str):
        """Открывает файл. Может кинуть исключение — вызывающие методы этого класса
        всегда оборачивают вызов в try/except, наружу класса это не протекает."""
        if mode in ("w", "a") and not self._ensure_dir_exists():
            raise OSError(f'Unable to ensure parent directory for "{self.path}"')
        return self.path.open(mode, encoding=self.encoding)

    # --- СВОЙСТВА (PROPERTIES) ---

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size if self.path.exists() else 0
        except Exception as e:
            self._logger.warning(f'Unable to get size of "{self.path}". Issue: {e}')
            return 0

    @property
    def exists(self) -> bool:
        try:
            return self.path.exists()
        except Exception as e:
            self._logger.warning(f'Unable to check existence of "{self.path}". Issue: {e}')
            return False

    @property
    def is_empty(self) -> bool:
        return self.exists and self.size == 0

    @property
    def line_count(self) -> int:
        if not self.exists:
            return 0
        try:
            with self._open('r') as f:
                return sum(1 for _ in f)
        except Exception as e:
            self._logger.warning(f'Unable to count lines in "{self.path}". Issue: {e}')
            return 0

    # --- МЕТОДЫ ЧТЕНИЯ И ЗАПИСИ ---

    def read(self) -> str:
        if not self.exists:
            return ""
        try:
            return self.path.read_text(encoding=self.encoding)
        except Exception as e:
            self._logger.warning(f'Unable to read "{self.path}". Issue: {e}')
            return ""

    def read_lines(self) -> list[str]:
        if not self.exists:
            return []
        try:
            return self.path.read_text(encoding=self.encoding).splitlines()
        except Exception as e:
            self._logger.warning(f'Unable to read lines from "{self.path}". Issue: {e}')
            return []

    def write(self, content: str) -> bool:
        try:
            with self._open('w') as f:
                f.write(content)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to write to "{self.path}". Issue: {e}')
            return False

    def write_line(self, line: str) -> bool:
        try:
            with self._open('w') as f:
                f.write(line.rstrip('\n') + '\n')
            return True
        except Exception as e:
            self._logger.warning(f'Unable to write line to "{self.path}". Issue: {e}')
            return False

    def write_lines(self, lines: list[str]) -> bool:
        try:
            with self._open('w') as f:
                f.writelines(line.rstrip('\n') + '\n' for line in lines)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to write lines to "{self.path}". Issue: {e}')
            return False

    def clear(self) -> bool:
        if not self.exists:
            return False
        try:
            self.path.write_text("", encoding=self.encoding)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to clear "{self.path}". Issue: {e}')
            return False

    # --- МЕТОДЫ МОДИФИКАЦИИ ---

    def append(self, content: str) -> bool:
        try:
            with self._open('a') as f:
                f.write(content)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to append to "{self.path}". Issue: {e}')
            return False

    def append_line(self, line: str) -> bool:
        try:
            with self._open('a') as f:
                f.write(line.rstrip("\n") + "\n")
            return True
        except Exception as e:
            self._logger.warning(f'Unable to append line to "{self.path}". Issue: {e}')
            return False

    def contains(self, text: str) -> bool:
        if not self.exists:
            return False
        try:
            with self._open('r') as f:
                return any(text in line for line in f)
        except Exception as e:
            self._logger.warning(f'Unable to search in "{self.path}". Issue: {e}')
            return False

    def contains_exact_line(self, exact_line: str) -> bool:
        if not self.exists:
            return False
        target = exact_line.rstrip('\n')
        try:
            with self._open('r') as f:
                return any(line.rstrip('\n') == target for line in f)
        except Exception as e:
            self._logger.warning(f'Unable to search in "{self.path}". Issue: {e}')
            return False

    def replace(self, old: str, new: str) -> bool:
        if not self.exists:
            return False

        temp_path = self.path.with_suffix(self.path.suffix + '.tmp')
        changed = False
        try:
            with self._open('r') as f_in, temp_path.open('w', encoding=self.encoding) as f_out:
                for line in f_in:
                    if old in line:
                        line = line.replace(old, new)
                        changed = True
                    f_out.write(line)

            if changed:
                temp_path.replace(self.path)
            else:
                temp_path.unlink()
            return changed
        except Exception as e:
            self._logger.warning(f'Unable to replace content in "{self.path}". Issue: {e}')
            temp_path.unlink(missing_ok=True)
            return False

    def add_line(self, line: str) -> bool:
        cleaned_line = line.rstrip('\n')
        if self.contains_exact_line(cleaned_line):
            return False
        try:
            has_content = self.size > 0
            with self._open("a") as f:
                if has_content:
                    f.write("\n")
                f.write(cleaned_line)
            return True
        except Exception as e:
            self._logger.warning(f'Unable to add line to "{self.path}". Issue: {e}')
            return False

    def remove_line(self, line: str) -> bool:
        if not self.exists:
            return False

        cleaned_line = line.rstrip('\n')
        temp_path = self.path.with_suffix(self.path.suffix + '.tmp')
        removed = False
        try:
            with self._open('r') as f_in, temp_path.open('w', encoding=self.encoding) as f_out:
                for line_from_file in f_in:
                    if line_from_file.rstrip('\n') == cleaned_line and not removed:
                        removed = True
                        continue
                    f_out.write(line_from_file)

            if removed:
                temp_path.replace(self.path)
            else:
                temp_path.unlink()
            return removed
        except Exception as e:
            self._logger.warning(f'Unable to remove line from "{self.path}". Issue: {e}')
            temp_path.unlink(missing_ok=True)
            return False


if __name__ == '__main__':
    # Создаем объект файла один раз
    py_file = File("system2.py")

    # Работаем с ним через методы и свойства
    py_file.write("Initialization...\n")
    py_file.append_line("User logged in")
    py_file.append_line("Database connected")
    py_file.append_line("import msl")
    py_file.append_line("msl.bootstrap()")

    # Свойства вызываются без круглых скобок ()
    print(f"Размер: {py_file.size} байт")
    print(f"Строк: {py_file.line_count}")

    if py_file.contains("Database"):
        print("Лог содержит информацию о БД")

    print("чтение линий",py_file.read_lines())

    FILES = Files()

    FILES("system.log").write("Initaaqwefqwefaaaaa")

    text = FILES("system.log").read()

    FILES("system.log").append_line("User logged in")