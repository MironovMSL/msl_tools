import logging
from pathlib import Path
from typing import Optional, Union

from msl_tools.msl.core.logger.mslLogger import MSLLogger

DEFAULT_NAME = "msl-tools"


class LoggerManager:
    """
    The single place MSL tools get their loggers from.

    File layout on disk (like ConfigManager's):
        base_dir / tool_name / log.log

    Example:
        logs = LoggerManager(Paths.logs)
        log  = logs.get("rename")     # -> logs/rename/log.log + console
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Cache of active loggers: { "tool_name": MSLLogger_instance }
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
        Returns the logger of that name. The first call creates a console
        (and, optionally, a file) handler. Later calls with the same name
        just return the cached logger — the parameters are not applied
        again (see the warning below).

        :param name: logger / tool name; also used as the name of the
                     log file's folder (base_dir / name / log.log)
        :param colored: colored console output
        :param fmt: custom console format (None -> MSLLogger.CONSOLE_FORMAT)
        :param level: logger level
        :param to_file: whether to write to base_dir/name/log.log
        :param file_level: minimum level for the file
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
        Creates an MSLLogger, swapping the logger class only for the moment
        of creation -- so logging isn't affected globally
        for the rest of the process (e.g. third-party libraries inside Maya).
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

    # A second call with the same name -> the same object, the file is already attached
    same_log = logs.get("rename")
    print(same_log is log)  # True

    pretty_log = logs.get("Pretty", fmt="%(message)s", to_file=False)
    pretty = PrettyLogger(pretty_log)
    pretty.header("Loading Config")
    pretty.separator()
    pretty.banner("banner")