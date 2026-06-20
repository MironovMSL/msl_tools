from PySide6 import QtCore
from msl_tools.msl.core.logger import LauncherLogger

class IniConfig(object):
	"""
	Class work with config.ini
	"""

	DEFAULTS: dict[str, dict[str, object]] = {
		"startup": {
			"title"          : "MSL Maya Launcher",
			"window_geometry": "",
			"environment"    : "Dev"
		},
	}


	def __init__(self, config_path: str):

		self.config_path = config_path
		self.config = QtCore.QSettings(self.config_path, QtCore.QSettings.IniFormat)


	def __getitem__(self, key: tuple[str, str, object, type]) -> object:
		"""	config["startup", "show_cache", False, bool] -> вернёт bool	"""
		section, var_name, *rest = key

		default_value = None
		value_type = None

		if len(rest) >= 1:
			default_value = rest[0]
		if len(rest) == 2:
			value_type = rest[1]

		if (section, var_name) not in self:
			LauncherLogger.debug(f"section: {section}, var_name: {var_name} not exist")

		return self.get_variable(section, var_name, default_value, value_type)

	def __setitem__(self, key: tuple[str, str], value: object) -> None:
		""" config["startup", "title"] = "MSL Launcher" """
		section, var_name = key
		self.set_variable(section, var_name, value)

	def __contains__(self, key: tuple[str, str]) -> bool:
		"""
            if ("startup", "title") in config:
        """
		section, var_name = key
		return self.config.contains(f"{section}/{var_name}")

	def set_variable(self, section: str, var_name: str, value: object) -> None:
		if not section or not var_name:
			raise ValueError("Both section and var_name parameters are required.")

		self.config.beginGroup(section)
		self.config.setValue(var_name, value)
		self.config.endGroup()

		LauncherLogger.info(f"[Save config.ini]{' ' * 5}[{section:.<10}] {var_name:.<15} = {value}")

	def get_variable(self, section: str, var_name: str, default_value: object = None, type: type = str) -> object:
		if not section or not var_name:
			raise ValueError("Both section and var_name parameters are required.")

		self.config.beginGroup(section)
		value = self.config.value(var_name, default_value, type)
		self.config.endGroup()
		return value

	def init_config(self) -> None:
		"""Initialize default configuration if it does not exist."""

		for group, values in self.DEFAULTS.items():
			self.config.beginGroup(group) # start the group
			for key, default in values.items():
				if not self.config.contains(f"{key}"):
					self.config.setValue(key, default)
					LauncherLogger.init(f"[Initialize config.ini]      [{group:.<10}] [{key:.<20}] = [{default}]")

			self.config.endGroup() # End the group

	def get_info_all_keys(self) -> None:
		"""Красиво печатает config.ini"""
		sections: dict[str, list[tuple[str, str]]] = {}

		# группируем ключи по секциям
		for key in self.config.allKeys():
			section, _, var_name = key.partition("/")
			value = self.config.value(key)
			sections.setdefault(section, []).append((var_name, value))

		# выводим по секциям
		for section, items in sections.items():
			LauncherLogger.info(f"[config.ini][{section}]")
			for var_name, value in items:
				LauncherLogger.info(f"{var_name:.<20} = {value}")

	def remove_variable(self, section: str, var_name: str) -> bool:
		if not section or not var_name:
			raise ValueError("Both section and var_name parameters are required.")

		if (section, var_name) not in self:
			LauncherLogger.debug(f"[Remove config.ini] [{section}] {var_name} — the key not found")
			return False

		self.config.beginGroup(section)
		self.config.remove(var_name)
		self.config.endGroup()

		LauncherLogger.info(f"[Remove config.ini]{' ' * 5}[{section:.<10}] {var_name:.<15} removed")
		return True

	def remove_section(self, section: str) -> bool:
		if not section:
			raise ValueError("Section name is required.")

		if not self.config.childGroups() or section not in self.config.childGroups():
			LauncherLogger.debug(f"[Remove config.ini] [{section}] — the section not found")
			return False

		self.config.beginGroup(section)
		self.config.remove("")
		self.config.endGroup()

		LauncherLogger.info(f"[Remove config.ini]{' ' * 5}[{section}] removed")
		return True

	def keys_in_section(self, section: str) -> list[str]:
		if not section:
			raise ValueError("Section name is required.")

		self.config.beginGroup(section)
		keys = list((self.config.childKeys()))
		self.config.endGroup()
		return keys



# import os
# from pathlib import Path
# from typing import Union, Any
# from PySide6 import QtCore
# from MSL_MayaGate.core.logger import LauncherLogger
#
# # Предполагаем, что JsonConfig и _ConfigSectionDict импортированы или описаны выше
# # from your_module import JsonConfig
#
# class _QSettingsSectionProxy:
#     """Прокси-класс для секции QSettings, чтобы получить синтаксис config['section']['key']"""
#     def __init__(self, settings: QtCore.QSettings, section: str):
#         self._settings = settings
#         self._section = section
#
#     def __getitem__(self, key: str) -> Any:
#         self._settings.beginGroup(self._section)
#         # По умолчанию возвращаем строку, если тип не важен, либо можно доработать
#         val = self._settings.value(key, "")
#         self._settings.endGroup()
#         return val
#
#     def __setitem__(self, key: str, value: Any) -> None:
#         self._settings.beginGroup(self._section)
#         self._settings.setValue(key, value)
#         self._settings.endGroup()
#         LauncherLogger.info(f"[Save QSettings]{' ' * 5}[{self._section:.<10}] [{key:.<15}] = [{value}]")
#
#     def __delitem__(self, key: str) -> None:
#         self._settings.beginGroup(self._section)
#         self._settings.remove(key)
#         self._settings.endGroup()
#
#
# class IniConfig:
#     """Обновленный класс для INI (QSettings), работающий аналогично JsonConfig"""
#     def __init__(self, file_path: str):
#         self.path = file_path
#         self.config = QtCore.QSettings(self.path, QtCore.QSettings.IniFormat)
#
#     def __getitem__(self, section: str) -> _QSettingsSectionProxy:
#         return _QSettingsSectionProxy(self.config, section)
#
#     def __delitem__(self, section: str) -> None:
#         self.config.beginGroup(section)
#         self.config.remove("")  # Удаляет всю секцию
#         self.config.endGroup()
#         LauncherLogger.info(f"[Remove IniConfig] Section [{section}] removed")
#
#     def get(self, section: str, key: str, default: Any = None) -> Any:
#         self.config.beginGroup(section)
#         val = self.config.value(key, default)
#         self.config.endGroup()
#         return val