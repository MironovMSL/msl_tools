import logging
from pathlib import Path
from typing import Optional, Union

from msl_tools.msl.core.logger.mslLogger import MSLLogger

DEFAULT_NAME = "msl-tools"


class LoggerManager:
    """
    Единая точка получения логгеров для инструментов MSL.

    Структура файлов на диске (по аналогии с ConfigManager):
        base_dir / tool_name / log.log

    Пример:
        logs = LoggerManager(Paths.logs)
        log  = logs.get("rename")     # -> logs/rename/log.log + консоль
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Кэш активных логгеров: { "tool_name": MSLLogger_instance }
        self._cache: dict[str, MSLLogger] = {}

    def __repr__(self) -> str:
        return f"LoggerManager('{self.base_dir}')"

    def get(self,
        name: str          = DEFAULT_NAME,
        colored: bool      = False,
        fmt: Optional[str] = None,
        level: str         = "DEBUG",
        to_file: bool      = True,
        file_level: str    = "WARNING",
        ) -> MSLLogger:
        """
        Возвращает логгер по имени. При первом обращении создаёт консольный
        (и, опционально, файловый) хендлер. Повторные вызовы с тем же name
        просто возвращают закэшированный логгер — параметры повторно не
        применяются (см. предупреждение ниже).

        :param name: имя логгера / инструмента; также используется как имя
                     папки для лог-файла (base_dir / name / log.log)
        :param colored: цветной вывод в консоль
        :param fmt: кастомный формат консоли (None -> MSLLogger.CONSOLE_FORMAT)
        :param level: уровень логгера
        :param to_file: писать ли в файл base_dir/name/log.log
        :param file_level: минимальный уровень для файла
        """
        if name in self._cache:
            return self._cache[name]

        logger = self._create_logger(name)
        logger.setLevel(level)
        logger.propagate = False
        logger.add_console(colored=colored, fmt=fmt)

        if to_file:
            log_dir = self.base_dir / name
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "log.log"
            logger.add_file(str(log_path), level=file_level)

        self._cache[name] = logger
        return logger

    @staticmethod
    def _create_logger(name: str) -> MSLLogger:
        """
        Создаёт логгер класса MSLLogger, временно подменяя logger class
        только на момент создания -- чтобы не влиять на logging глобально
        для остального процесса (например, сторонних библиотек внутри Maya).
        """
        prev_cls = logging.getLoggerClass()
        try:
            logging.setLoggerClass(MSLLogger)
            return logging.getLogger(name)
        finally:
            logging.setLoggerClass(prev_cls)


if __name__ == "__main__":
    from msl_tools.msl.core.fs.paths import Paths
    from msl_tools.msl.core.logger.prettyLogger import PrettyLogger

    logs = LoggerManager(Paths.logs)

    log = logs.get("rename", level="DEBUG")
    log.init("init")
    log.debug("debug")
    log.info("info")
    log.warning("warning")
    log.error("error")
    log.path(r"C:\Project\character.mb")

    # Повторный вызов с тем же name -> тот же объект, файл уже подключён
    same_log = logs.get("rename")
    print(same_log is log)  # True

    pretty_log = logs.get("Pretty", fmt="%(message)s", to_file=False)
    pretty = PrettyLogger(pretty_log)
    pretty.header("Loading Config")
    pretty.separator()
    pretty.banner("banner")