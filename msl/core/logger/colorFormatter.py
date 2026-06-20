import logging
import copy


class ColorFormatter(logging.Formatter):

    COLORS = {
        "INIT"    : "\033[35m",
        "PATH"    : "\033[37m",
        "DEBUG"   : "\033[34m",
        "INFO"    : "\033[32m",
        "WARNING" : "\033[33m",
        "ERROR"   : "\033[31m",
        "CRITICAL": "\033[41m",
        "RESET"   : "\033[0m",
        "NAME"    : "\033[1;37m"
    }

    def format(self, record):

        record           = copy.copy(record)
        color            = self.COLORS.get(record.levelname, "")
        reset            = self.COLORS["RESET"]
        message          = record.getMessage()

        record.name      = (f"{self.COLORS['NAME']}{record.name}{reset}")
        record.levelname = (f"{color}{record.levelname}{reset}")
        record.msg       = (f"{color}{message}{reset}")
        record.args      = ()

        return super().format(record)