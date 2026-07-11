from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.core.logger.manager import LoggerManager
from msl_tools.msl.core.config.manager import ConfigManager
from msl_tools.msl.core.network.network_client import NetworkClient
from msl_tools.msl.core.fs.paths import Paths
from msl_tools.msl.core.fs.files import Files


class Resources(metaclass=SingletonMeta):
    def __init__(self):
        self.paths         = Paths()
        self.files         = Files()
        self.logManager    = LoggerManager(self.paths.logs)
        self.networkClient = NetworkClient()
        self.configManager = ConfigManager(self.paths.configs)





if __name__ == "__main__":

    RES1 = Resources()
    RES2 = Resources()

    if id(RES1) == id(RES2):
        print("Singleton works, both variables contain the same instance.")
    else:
        print("Singleton failed, variables contain different instances.")



    renam_con = RES1.configManager.get_config("rename", ext=".json")
    renam_con["test"]["test"] = "test"

    modeling_cnf = RES1.configManager.get_config("modeling", ext=".ini")
    modeling_cnf["startup"]["window_geometry"] = 6

    # Повторный запрос того же tool_name с тем же ext -> вернёт закэшированный, ОК
    same = RES1.configManager.get_config("rename", ext=".json")
    print(same is renam_con)  # True

    # Попытка запросить "rename" как .ini -> теперь падает с понятной ошибкой,
    # а не молча возвращает JsonConfig
    RES1.configManager.get_config("rename", ext=".ini")