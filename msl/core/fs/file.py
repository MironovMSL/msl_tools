from pathlib import Path
from typing import Generator


class File:
    def __init__(self, path: str | Path, encoding: str = 'utf-8') -> None:
        self.path = Path(path)
        self.encoding = encoding

    def _ensure_dir_exists(self) -> None:
        """Внутренний метод для автоматического создания папок."""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- СВОЙСТВА (PROPERTIES) ---

    @property
    def size(self) -> int:
        """Размер файла в байтах. Если файла нет — возвращает 0."""
        return self.path.stat().st_size if self.path.exists() else 0

    @property
    def exists(self) -> bool:
        """Проверка существования файла."""
        return self.path.exists()

    @property
    def is_empty(self) -> bool:
        """Пустой ли файл."""
        return self.exists and self.size == 0

    @property
    def line_count(self) -> int:
        """Количество строк в файле без загрузки всего файла в память."""
        if not self.exists:
            return 0
        with self.path.open('r', encoding=self.encoding) as f:
            return sum(1 for _ in f)

    # --- МЕТОДЫ ЧТЕНИЯ И ЗАПИСИ ---

    def read(self) -> str:
        """Чтение всего файла в виде строки."""
        if not self.exists:
            return ""
        return self.path.read_text(encoding=self.encoding)

    def read_lines(self) -> list[str]:
        """Чтение всех строк файла в виде списка."""
        if not self.exists:
            return []
        return self.path.read_text(encoding=self.encoding).splitlines()

    def write(self, content: str) -> None:
        """Запись строки в файл с перезаписью контента."""
        self._ensure_dir_exists()
        self.path.write_text(content, encoding=self.encoding)

    def write_lines(self, lines: list[str]) -> None:
        """Запись списка строк в файл."""
        self._ensure_dir_exists()
        with self.path.open('w', encoding=self.encoding) as f:
            for line in lines:
                f.write(line.rstrip('\n') + '\n')

    def clear(self) -> None:
        """Очистить содержимое файла."""
        if self.exists:
            self.path.write_text("", encoding=self.encoding)

    # --- МЕТОДЫ МОДИФИКАЦИИ ---

    def append(self, content: str) -> None:
        """Дописать текст в конец файла."""
        self._ensure_dir_exists()
        with self.path.open('a', encoding=self.encoding) as f:
            f.write(content)

    def append_line(self, line: str) -> None:
        """Дописать строку с автоматическим переносом."""
        self._ensure_dir_exists()
        with self.path.open('a', encoding=self.encoding) as f:
            f.write(line.rstrip('\n') + '\n')

    def contains(self, text: str) -> bool:
        """Потоковая проверка наличия подстроки в файле (безопасно для памяти)."""
        if not self.exists:
            return False
        with self.path.open('r', encoding=self.encoding) as f:
            return any(text in line for line in f)

    def replace(self, old: str, new: str) -> bool:
        """Замена подстроки в файле. Возвращает True, если замена успешна."""
        if not self.exists:
            return False
        content = self.read()
        if old in content:
            self.write(content.replace(old, new))
            return True
        return False

    def add_line(self, line: str) -> bool:
        """Добавить уникальную строку, если её еще нет в файле."""
        self._ensure_dir_exists()
        cleaned_line = line.rstrip('\n')

        if self.contains(cleaned_line):
            return False

        has_content = self.size > 0
        with self.path.open("a", encoding=self.encoding) as f:
            if has_content:
                f.write("\n")
            f.write(cleaned_line)
        return True

    def remove_line(self, line: str) -> bool:
        """Удалить строку из файла. Возвращает True, если строка была найдена."""
        if not self.exists:
            return False

        lines = self.read_lines()
        cleaned_line = line.rstrip('\n')

        if cleaned_line in lines:
            lines.remove(cleaned_line)
            self.write_lines(lines)
            return True
        return False


if __name__ == '__main__':
    # Создаем объект файла один раз
    log_file = File("system.log")

    # Работаем с ним через методы и свойства
    log_file.write("Initialization...")
    log_file.append_line("User logged in")
    log_file.append_line("Database connected")

    # Свойства вызываются без круглых скобок ()
    print(f"Размер: {log_file.size} байт")
    print(f"Строк: {log_file.line_count}")

    if log_file.contains("Database"):
        print("Лог содержит информацию о БД")