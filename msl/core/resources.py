from msl_tools.msl.core.pattern.singleton import SingletonMeta
from msl_tools.msl.core.logger.manager import LoggerManager
from msl_tools.msl.core.config.manager import ConfigManager
from msl_tools.msl.core.fs.manager import FileSystemManager
from msl_tools.msl.core.version.manager import VersionManager
from msl_tools.msl.core.network.network_client import NetworkClient
from msl_tools.msl.core.theme import ThemeRegistry


CORE_CONFIG_DEFAULTS = {
    "theme": {
        "name": "light",
    }
}

class Resources(metaclass=SingletonMeta):

    def __init__(self):
        #TODO create default config 'core' where I can request any value, after I see how many parameters I need.
        releases_url       = "https://api.github.com/repos/MironovMSL/msl_tools/releases"
        latest_release_url = "https://api.github.com/repos/MironovMSL/msl_tools/releases/latest"
        self.releasesPageUrl = "https://github.com/MironovMSL/msl_tools/releases"  # for "open in browser" links
        # A release's source archive ({tag} = "v1.2.3") - what the hub's one-click update downloads.
        self.releaseArchiveUrl = "https://github.com/MironovMSL/msl_tools/archive/refs/tags/{tag}.zip"


        self.fsManager        = FileSystemManager()

        self.logs             = LoggerManager(self.fsManager.logs)
        self.logsMaya         = LoggerManager(self.fsManager.logsMaya)
        self.logsDesktopHub   = LoggerManager(self.fsManager.logsDesktop)

        self.configsCoreMng   = ConfigManager(self.fsManager.configs, logger=self.logs.get("configsCoreMng", to_file=False))
        self.coreConfig       = self.configsCoreMng.get_config("core", defaults=CORE_CONFIG_DEFAULTS)

        self.configsMayaMng   = ConfigManager(self.fsManager.configsMaya, logger=self.logs.get("configsMayaTools", to_file=False))

        self.configsDesktopHubMng= ConfigManager(self.fsManager.configsDesktop, logger=self.logs.get("configsDesktopHub", to_file=False) )

        self.networkClient    = NetworkClient(logger=self.logs.get("NetworkClient", to_file=False))
        self.versionManager   = VersionManager(releases_url, latest_release_url, self.networkClient, self.fsManager.msl,
                                               logger=self.logs.get("VersionManager", to_file=False))
        self.themeRegistry    = ThemeRegistry(self.fsManager.themes, logger=self.logs.get("ThemeRegistry", to_file=False))


if __name__ == "__main__":

    RES1 = Resources()
    RES2 = Resources()

    if id(RES1) == id(RES2):
        print("Singleton works, both variables contain the same instance.")
    else:
        print("Singleton failed, variables contain different instances.")

    renam_con = RES1.configsMaya.get_config("rename", ext=".json")
    renam_con["test"]["test"] = "test"

    modeling_cnf = RES1.configsMaya.get_config("modeling", ext=".ini")
    modeling_cnf["startup"]["window_geometry"] = 6

    # Повторный запрос того же tool_name с тем же ext -> вернёт закэшированный, ОК
    same = RES1.configsMaya.get_config("rename", ext=".json")
    print(same is renam_con)  # True

    # Попытка запросить "rename" как .ini -> теперь падает с понятной ошибкой,
    # а не молча возвращает JsonConfig
    RES1.configsMaya.get_config("rename", ext=".ini")

    print(RES1.versionManager.check_for_update(RES1.fsManager.msl))