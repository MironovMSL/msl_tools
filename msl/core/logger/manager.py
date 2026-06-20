from msl_tools.msl.core.logger.colorFormatter import ColorFormatter
from msl_tools.msl.core.logger.mslLoger import MSLLogger
from msl_tools.msl.core.logger.prettyLogger import PrettyLogger
import logging
import sys


class LoggerManager:

    _cache = {}
    _initialized = False

    @classmethod
    def get(cls, name="msl-tools",colored=True, fmt=None):
        if not cls._initialized:
            logging.setLoggerClass(MSLLogger)
            cls._initialized = True

        if name not in cls._cache:

            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False
            logger.add_console(colored=colored, fmt=fmt)

            cls._cache[name] = logger

        return cls._cache[name]



if __name__ == "__main__":
    path = r"H:\ProjectsDev\MSL_Others\msl_tools\msl\logger"
    log = LoggerManager.get()
    log.add_file(path + "\log.log", level=logging.DEBUG)
    log.init("init")
    log.debug("debug")
    log.info("info")
    log.warning("warning")
    log.error("error")
    log.path(r"C:\Project\character.mb")
    log.remove_file(path + "\log.log")

    pretty_log = LoggerManager.get("Pretty", fmt="%(message)s")
    pretty = PrettyLogger(pretty_log)
    pretty.header("Loading Config")
    pretty.separator()
    pretty.banner("banner")


