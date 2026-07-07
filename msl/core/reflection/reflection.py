import importlib
import inspect
import logging

logger = logging.getLogger(__name__)


class Reflection:
    """Низкоуровневые утилиты интроспекции и динамической загрузки Python-объектов.
    Не знает ничего о Maya/Qt — годится для использования где угодно, включая ConfigManager/Resources."""

    @classmethod
    def import_from_path(cls, path: str):
        """Динамически импортирует модуль или объект по полному пути (e.g. "pkg.module.ClassName")."""
        try:
            module_path, object_name = path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, object_name, None)
        except (ImportError, AttributeError, ValueError, ModuleNotFoundError) as e:
            logger.warning(f'Unable to import "{path}". Issue: {e}')
            return None

    @classmethod
    def get_function_arguments(cls, func, kwargs_as_dict: bool = False):
        """Возвращает (args, kwargs) для переданной функции."""
        signature = inspect.signature(func)
        args, kwargs, kwargs_dict = [], [], {}
        for name, param in signature.parameters.items():
            if param.default is inspect.Parameter.empty:
                args.append(name)
            else:
                kwargs.append(name)
                kwargs_dict[name] = param.default
        return (args, kwargs_dict) if kwargs_as_dict else (args, kwargs)

    @classmethod
    def get_docstring(cls, func, strip: bool = False, strip_new_lines: bool = False) -> str:
        if not callable(func):
            raise ValueError("Input 'func' must be a callable function.")
        docstring = func.__doc__ or ""
        if strip:
            docstring = "\n".join(line.lstrip() for line in docstring.split("\n"))
        if strip_new_lines:
            docstring = docstring.lstrip("\n")
            if docstring.endswith("\n"):
                docstring = docstring[: -len("\n")]
        return docstring

    @classmethod
    def create_object(cls, class_name: str, *args, namespace: dict | None = None,
                       module_path: str | None = None, raise_errors: bool = True, **kwargs):
        """Создаёт инстанс класса по имени.
        namespace: явное пространство имён для поиска (например, вызвать с namespace=globals() из места вызова).
        module_path: путь модуля для динамического импорта (альтернатива namespace)."""
        class_obj = None

        if module_path:
            try:
                module = importlib.import_module(module_path)
                class_obj = getattr(module, class_name, None)
                if class_obj is None:
                    raise AttributeError(f'"{class_name}" not found in module "{module_path}"')
            except (ImportError, AttributeError) as e:
                if raise_errors:
                    raise
                logger.warning(str(e))
                return None
        elif namespace and class_name in namespace:
            class_obj = namespace[class_name]
        else:
            message = f'Unable to create object. No namespace/module_path provided for "{class_name}".'
            if raise_errors:
                raise NameError(message)
            logger.warning(message)
            return None

        if not isinstance(class_obj, type):
            message = f'"{class_name}" is not a class.'
            if raise_errors:
                raise TypeError(message)
            logger.warning(message)
            return None

        try:
            return class_obj(*args, **kwargs)
        except Exception as e:
            message = f'Error creating an instance of "{class_name}": {e}'
            if raise_errors:
                raise
            logger.warning(message)
            return None

    @classmethod
    def execute_code(cls, code: str, *, exec_globals: dict | None = None,
                      raise_errors: bool = False) -> bool:
        """Выполняет строку Python-кода. Возвращает True при успехе."""
        _globals = exec_globals if isinstance(exec_globals, dict) else {}
        try:
            exec(code, _globals)
            return True
        except Exception as e:
            logger.warning(f"Error executing code: {e}")
            if raise_errors:
                raise
            return False