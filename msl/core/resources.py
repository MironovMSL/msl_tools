from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.core.paths import Paths


class Resources(metaclass=SingletonMeta):
    def __init__(self):

        self.paths = Paths()


if __name__ == "__main__":

    RES1 = Resources()
    RES2 = Resources()

    if id(RES1) == id(RES2):
        print("Singleton works, both variables contain the same instance.")
    else:
        print("Singleton failed, variables contain different instances.")