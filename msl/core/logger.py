# Уровень и сообщение
# %(levelname)s → имя уровня (DEBUG, INFO, WARNING, …).
# %(levelno)s → номер уровня (10, 20, 30, …).
# %(message)s → само сообщение после форматирования.

# Логгер и модуль
# %(name)s → имя логгера (у тебя "Zurbrigg").
# %(module)s → имя модуля без .py.
# %(funcName)s → имя функции, из которой вызван лог.
# %(lineno)d → номер строки вызова.
# %(pathname)s → полный путь к файлу.
# %(filename)s → только имя файла (main.py).

# Время
# %(asctime)s → дата/время (форматируется через datefmt).
# %(created)f → timestamp (time.time()).
# %(msecs)d → миллисекунды.
# %(relativeCreated)d → миллисекунды с момента старта логгера.

# Процесс и поток
# %(process)d → ID процесса.
# %(processName)s → имя процесса.
# %(thread)d → ID потока.
# %(threadName)s → имя потока.

# Базовые цвета текста (foreground)
# 30 → Черный
# 31 → Красный
# 32 → Зеленый
# 33 → Желтый
# 34 → Синий
# 35 → Фиолетовый (magenta)
# 36 → Бирюзовый (cyan)
# 37 → Белый (серый)

# Цвет фона
# 40–47 → фоновые цвета (аналогично тексту).

# Сброс
# \033[0m → сброс стилей (обязательно ставить после текста, иначе дальше всё будет цветное).

# Дополнительные стили
# 0 → сброс (reset).
# 1 → жирный.
# 2 → тусклый.
# 3 → курсив.
# 4 → подчеркивание.
# 5 → мигающий.
# 7 → инверсия (фон ↔ текст).


import logging
import sys
import copy


class Logger(object):
    LOGGER_NAME    = "Mironov"
    FORMAT_DEFAULT = "[%(name)s][%(levelname)s] %(message)s"
    LEVEL_DEFAULT  = logging.DEBUG
    _logger_obj    = None

    INIT_LEVEL = 15
    PATH_LEVEL = 16
    logging.addLevelName(INIT_LEVEL, "INIT")
    logging.addLevelName(PATH_LEVEL, "PATH")

    @classmethod
    def logger_obj(cls):
        if not cls._logger_obj:
            cls._logger_obj = logging.getLogger(cls.LOGGER_NAME)
            cls._logger_obj.setLevel(cls.LEVEL_DEFAULT)
            cls._logger_obj.propagate = False

            stream_handler = logging.StreamHandler(sys.stderr)
            formatter = logging.Formatter(cls.FORMAT_DEFAULT)
            stream_handler.setFormatter(formatter)
            cls._logger_obj.addHandler(stream_handler)

        return cls._logger_obj

    @classmethod
    def set_level(cls, level):
        cls.logger_obj().setLevel(level)


    @classmethod
    def init(cls, msg, *args, **kwargs):
        lg = cls.logger_obj()
        if lg.isEnabledFor(cls.INIT_LEVEL):
            lg.log(cls.INIT_LEVEL, msg, *args, **kwargs)

    @classmethod
    def pathL(cls, msg, *args, **kwargs):
        lg = cls.logger_obj()
        if lg.isEnabledFor(cls.PATH_LEVEL):
            lg.log(cls.PATH_LEVEL, msg, *args, **kwargs)

    @classmethod
    def debug(cls, msg, *args, **kwargs):
        cls.logger_obj().debug(msg, *args, **kwargs)

    @classmethod
    def info(cls, msg, *args, **kwargs):
        cls.logger_obj().info(msg, *args, **kwargs)

    @classmethod
    def warning(cls, msg, *args, **kwargs):
        cls.logger_obj().warning(msg, *args, **kwargs)

    @classmethod
    def error(cls, msg, *args, **kwargs):
        cls.logger_obj().error(msg, *args, **kwargs)

    @classmethod
    def critical(cls, msg, *args, **kwargs):
        cls.logger_obj().critical(msg, *args, **kwargs)

    @classmethod
    def exception(cls, msg, *args, **kwargs):
        cls.logger_obj().exception(msg, *args, **kwargs)

    @classmethod
    def log(cls, level, msg, *args, **kwargs):
        cls.logger_obj().log(level, msg, *args, **kwargs)

    @classmethod
    def write_to_file(cls, path, level=logging.WARNING):
        logger = cls.logger_obj()
        FORMAT_FILE = (
            "[%(asctime)s]"
            "[%(levelname)s]"
            "[%(module)s:%(funcName)s:%(lineno)d] "
            "%(message)s"
        )

        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
                handler.close()

        file_handler = logging.FileHandler(path, encoding='utf-8')
        file_handler.setLevel(level)

        fmt = logging.Formatter(FORMAT_FILE)
        file_handler.setFormatter(fmt)

        logger.addHandler(file_handler)


class ColorLogger(Logger):

    LOGGER_NAME = "mslColor"
    _logger_obj = None

    FORMAT_DEFAULT = "[%(name)s][%(levelname)s] %(message)s"

    COLORS = {
        "INIT"    : "\033[35m",
        "PATH"    : "\033[37m",
        "DEBUG"   : "\033[34m",
        "INFO"    : "\033[32m",
        "WARNING" : "\033[33m",
        "ERROR"   : "\033[31m",
        "CRITICAL": "\033[41m",     # Red background
        "RESET"   : "\033[0m",
        "Black"   : "\033[30m",     # Черный
        "Red"     : "\033[31m",     # Красный
        "Green"   : "\033[32m",     # Зеленый
        "Yellow"  : "\033[33m",     # Желтый
        "Blue"    : "\033[34m",     # Синий
        "Magenta" : "\033[35m",     # Фиолетовый (magenta)
        "Cyan"    : "\033[36m",     # Бирюзовый (cyan)
        "White"   : "\033[1;37m",     # Белый (серый)
    }

    class ColorFormatter(logging.Formatter):

        def format(self, record):
            # Создаем копию записи, чтобы НЕ портить оригинал для файлового логгера
            colored_record = copy.copy(record)

            # ПРАВКА 1: Заменили Logger.COLORS на ColorLogger.COLORS
            color = ColorLogger.COLORS.get(colored_record.levelname, "")
            reset = ColorLogger.COLORS["RESET"]

            # Раскрашиваем только копию для консоли
            colored_record.levelname = f"{color}{colored_record.levelname}{reset}"
            colored_record.msg = f"{color}{colored_record.msg}{reset}"
            colored_record.name = f"{ColorLogger.COLORS['White']}{colored_record.name}{reset}"

            # Форматируем именно копию
            return super().format(colored_record)

    @classmethod
    def logger_obj(cls):
        if not cls._logger_obj:
            cls._logger_obj = logging.getLogger(cls.LOGGER_NAME)
            cls._logger_obj.setLevel(cls.LEVEL_DEFAULT)
            cls._logger_obj.propagate = False

            stream_handler = logging.StreamHandler(sys.stderr)
            # Передаем наш цветной форматер
            stream_handler.setFormatter(cls.ColorFormatter(cls.FORMAT_DEFAULT))
            cls._logger_obj.addHandler(stream_handler)

        return cls._logger_obj


class LauncherLogger(Logger):
    LOGGER_NAME       = "MayaLauncher"
    FORMAT_DEFAULT    = "[%(levelname)s] %(message)s"



if __name__ == "__main__":
    # Logger.set_level = lambda lvl: Logger.logger_obj().setLevel(lvl)
    # Logger.set_level(logging.DEBUG)

    Logger.write_to_file(r"H:\ProjectsDev\MSL_Others\msl_tools\msl\test.log")
    ColorLogger.write_to_file(r"H:\ProjectsDev\MSL_Others\msl_tools\msl\test2.log")

    ColorLogger.debug("debug message")
    ColorLogger.init("init message")
    ColorLogger.info(f"info message")
    ColorLogger.warning("warning message")
    ColorLogger.error("error message")
    ColorLogger.critical("critical message")
    ColorLogger.pathL("path message")
    ColorLogger.log(15,"log message")

    Logger.debug("debug message")
    Logger.info("info message")
    Logger.warning("warning message")

    try:
        a = []
        b = a[0]
    except:
        Logger.exception("exception message")

