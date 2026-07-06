from pathlib import Path


class QtPaths:
    """Пути через нативные платформенные API (реестр Windows, XDG на Linux и т.д.)
    Требует PySide6. Импорт лениво внутри каждого метода, чтобы модуль fs/
    оставался пригодным для использования без Qt (mayapy, тесты и т.д.)."""

    @classmethod
    def get_home_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.HomeLocation)
        return Path(path) if path else None

    @classmethod
    def get_desktop_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DesktopLocation)
        return Path(path) if path else None

    @classmethod
    def get_documents_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(path) if path else None

    @classmethod
    def get_downloads_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.DownloadLocation)
        return Path(path) if path else None

    @classmethod
    def get_pictures_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.PicturesLocation)
        return Path(path) if path else None

    @classmethod
    def get_music_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.MusicLocation)
        return Path(path) if path else None

    @classmethod
    def get_movies_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.MoviesLocation)
        return Path(path) if path else None

    @classmethod
    def get_temp_dir(cls) -> Path | None:
        from PySide6 import QtCore
        path = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.StandardLocation.TempLocation)
        return Path(path) if path else None

if __name__ == '__main__':

    print(QtPaths.get_home_dir())
    print(QtPaths.get_desktop_dir())
    print(QtPaths.get_documents_dir())
    print(QtPaths.get_downloads_dir())
    print(QtPaths.get_pictures_dir())
    print(QtPaths.get_music_dir())
    print(QtPaths.get_movies_dir())
    print(QtPaths.get_temp_dir())