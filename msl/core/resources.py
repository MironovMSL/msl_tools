from msl_tools import msl
from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.core.logger.manager import LoggerManager
from msl_tools.msl.core.fs.paths import Paths
import logging


class Resources(metaclass=SingletonMeta):
    def __init__(self):

        self.paths      = Paths()
        self.logManager = LoggerManager()




if __name__ == "__main__":

    RES1 = Resources()
    RES2 = Resources()

    if id(RES1) == id(RES2):
        print("Singleton works, both variables contain the same instance.")
    else:
        print("Singleton failed, variables contain different instances.")