from pathlib import Path


class Files:
    def __call__(self, path: str | Path, encoding: str = 'utf-8') -> 'File':
        return File(path, encoding)


class File:
    def __init__(self, path: str | Path, encoding: str = 'utf-8') -> None:
        self.path = Path(path)
        self.encoding = encoding

    def _ensure_dir_exists(self) -> None:
        """Внутренний метод для автоматического создания папок."""
        if self.path.parent != Path('.'):
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self, mode: str):
        """Единый метод открытия файла с гарантией существования директории."""
        self._ensure_dir_exists()
        return self.path.open(mode, encoding=self.encoding)

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
        with self._open('r') as f:
            return sum(1 for _ in f)

    # --- МЕТОДЫ ЧТЕНИЯ И ЗАПИСИ ---

    def read(self) -> str:
        """Чтение всего файла в виде строки."""
        if not self.exists:
            return ""
        return self.path.read_text(encoding=self.encoding)

    def read_lines(self) -> list[str]:
        """Чтение всех строк файла в виде списка (без символов \n в конце)."""
        if not self.exists:
            return []
        return self.path.read_text(encoding=self.encoding).splitlines()

    def write(self, content: str) -> None:
        """Перезаписать файл текстом как есть."""
        with self._open('w') as f:
            f.write(content)

    def write_line(self, line: str) -> None:
        """Перезаписать файл одной строкой с символом конца строки."""
        with self._open('w') as f:
            f.write(line.rstrip('\n') + '\n')

    def write_lines(self, lines: list[str]) -> None:
        """Записать список строк в файл."""
        with self._open('w') as f:
            # Использование генератора эффективнее, чем конкатенация огромной строки в памяти
            f.writelines(line.rstrip('\n') + '\n' for line in lines)

    def clear(self) -> None:
        """Очистить содержимое файла."""
        if self.exists:
            self.path.write_text("", encoding=self.encoding)

    # --- МЕТОДЫ МОДИФИКАЦИИ ---

    def append(self, content: str) -> None:
        """Дописать текст в конец файла."""
        with self._open('a') as f:
            f.write(content)

    def append_line(self, line: str) -> None:
        """Дописать строку с переносом в конец файла."""
        with self._open('a') as f:
            f.write(line.rstrip("\n") + "\n")

    def contains(self, text: str) -> bool:
        """Потоковая проверка наличия подстроки в файле (безопасно для памяти)."""
        if not self.exists:
            return False
        with self._open('r') as f:
            return any(text in line for line in f)

    def contains_exact_line(self, exact_line: str) -> bool:
        """Проверка наличия точного совпадения строки (без учета \n)."""
        if not self.exists:
            return False
        target = exact_line.rstrip('\n')
        with self._open('r') as f:
            return any(line.rstrip('\n') == target for line in f)

    def replace(self, old: str, new: str) -> bool:
        """Безопасная замена подстроки через временный файл."""
        if not self.exists:
            return False

        temp_path = self.path.with_suffix('.tmp')
        changed = False

        with self._open('r') as f_in, temp_path.open('w', encoding=self.encoding) as f_out:
            for line in f_in:
                if old in line:
                    line = line.replace(old, new)
                    changed = True
                f_out.write(line)

        if changed:
            temp_path.replace(self.path)
        else:
            temp_path.unlink()  # Удаляем временный файл, если изменений не было

        return changed

    def add_line(self, line: str) -> bool:
        """Добавить уникальную строку, если такой строки ЕЩЕ НЕТ в файле."""
        cleaned_line = line.rstrip('\n')

        # Исправлено: проверяем точное совпадение строки, а не подстроку
        if self.contains_exact_line(cleaned_line):
            return False

        has_content = self.size > 0
        with self._open("a") as f:
            if has_content:
                f.write("\n")
            f.write(cleaned_line)
        return True

    def remove_line(self, line: str) -> bool:
        """Удалить строку из файла (безопасно для памяти)."""
        if not self.exists:
            return False

        cleaned_line = line.rstrip('\n')
        temp_path = self.path.with_suffix('.tmp')
        removed = False

        with self._open('r') as f_in, temp_path.open('w', encoding=self.encoding) as f_out:
            for line_from_file in f_in:
                if line_from_file.rstrip('\n') == cleaned_line and not removed:
                    removed = True
                    continue  # Пропускаем удаляемую строку
                f_out.write(line_from_file)

        if removed:
            temp_path.replace(self.path)
        else:
            temp_path.unlink()

        return removed


if __name__ == '__main__':
    # Создаем объект файла один раз
    log_file = File("system2.log")

    # Работаем с ним через методы и свойства
    log_file.write("Initialization...\n")
    log_file.append_line("User logged in")
    log_file.append_line("Database connected")

    # Свойства вызываются без круглых скобок ()
    print(f"Размер: {log_file.size} байт")
    print(f"Строк: {log_file.line_count}")

    if log_file.contains("Database"):
        print("Лог содержит информацию о БД")

    FILES = Files()

    FILES("system.log").write("Initaaqwefqwefaaaaa")

    text = FILES("system.log").read()

    FILES("system.log").append_line("User logged in")