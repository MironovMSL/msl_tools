import sys
import logging
from logging.handlers import RotatingFileHandler
from msl_tools.msl.core.logger.colorFormatter import ColorFormatter


class MSLLogger(logging.Logger):
    CONSOLE_FORMAT = ("[%(name)s][%(levelname)s] %(message)s")
    # CONSOLE_FORMAT = ("[%(name)s][%(levelname)s][%(lineno)d] %(message)s")
    FILE_FORMAT    = ("[%(asctime)s][%(name)s][%(levelname)s]%(message)s")


    INIT_LEVEL = 15
    PATH_LEVEL = 16

    logging.addLevelName(INIT_LEVEL, "INIT")
    logging.addLevelName(PATH_LEVEL, "PATH")

    LEVEL = {
        "DEBUG"   : logging.DEBUG,
        "INFO"    : logging.INFO,
        "WARNING" : logging.WARNING,
        "ERROR"   : logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }

    def init(self, msg, *args, **kwargs):
        if self.isEnabledFor(self.INIT_LEVEL):
            self.log(self.INIT_LEVEL, msg, *args, **kwargs)

    def path(self, msg, *args, **kwargs):
        if self.isEnabledFor(self.PATH_LEVEL):
            self.log(self.PATH_LEVEL, msg, *args, **kwargs)

    def set_level(self, level):
        self.setLevel(self.LEVEL[level])
        return self

    # -------------------------
    # Console
    # -------------------------

    def has_console(self):
        return any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in self.handlers)

    def add_console(self, colored=True, fmt=None, stream=sys.stdout):

        if self.has_console():
            return

        fmt     = fmt or self.CONSOLE_FORMAT
        handler = logging.StreamHandler(stream)

        if colored:
            handler.setFormatter(ColorFormatter(fmt))
        else:
            handler.setFormatter(logging.Formatter(fmt))

        self.addHandler(handler)

        return handler

    def remove_console(self):

        for handler in list(self.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                self.removeHandler(handler)
                handler.close()

    # -------------------------
    # File logging
    # -------------------------

    def has_file(self, path=None):
        if path is None:
            return any(isinstance(h, logging.FileHandler) for h in self.handlers)
        return any(isinstance(h, logging.FileHandler) and h.baseFilename == path for h in self.handlers)

    def add_file(self, path, level="WARNING", max_mb=5, backup_count=3):

        if self.has_file(path):
            return

        handler = RotatingFileHandler( path, maxBytes=max_mb * 1024 * 1024, backupCount=backup_count, encoding="utf-8")
        handler.setLevel(self.LEVEL[level])
        handler.setFormatter(logging.Formatter(self.FILE_FORMAT))

        self.addHandler(handler)

        return handler

    def remove_file(self, path=None):

        for handler in list(self.handlers):
            if not isinstance(handler, logging.FileHandler):
                continue

            if path is None:
                self.removeHandler(handler)
                handler.close()

            elif handler.baseFilename == path:
                self.removeHandler(handler)
                handler.close()

    # -------------------------
    # State control
    # -------------------------
    def clear_handlers(self):
        for handler in list(self.handlers):
            self.removeHandler(handler)
            handler.close()

    def reset(self):
        self.clear_handlers()
        self.setLevel(self.LEVEL["DEBUG"])
        self.propagate = False
        self.add_console()