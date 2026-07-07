from collections import namedtuple
import re


class Version:
    """Чистая работа с семантическими версиями. Без I/O, без исключений наружу (кроме parse — там осмысленно)."""

    SemanticVersion = namedtuple("SemanticVersion", ["major", "minor", "patch"])

    BIGGER = 1
    SMALLER = -1
    EQUAL = 0

    _PATTERN_WITH_METADATA = (
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )
    _PATTERN_STRICT = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"

    @classmethod
    def is_valid(cls, version_str: str, metadata_ok: bool = True) -> bool:
        pattern = cls._PATTERN_WITH_METADATA if metadata_ok else cls._PATTERN_STRICT
        return bool(re.match(pattern, str(version_str)))

    @classmethod
    def parse(cls, version_string: str, as_tuple: bool = False):
        """Извлекает major.minor.patch из строки версии. Игнорирует суффиксы (e.g. "v1.2.3-dev" -> "1.2.3")."""
        try:
            digits_only = re.sub(r"[^\d.]", "", version_string)
            major, minor, patch = map(int, digits_only.split(".")[:3])
        except (ValueError, AttributeError):
            raise ValueError(f'Invalid version format: "{version_string}". Expected semantic versioning: "1.2.3".')
        if as_tuple:
            return cls.SemanticVersion(major=major, minor=minor, patch=patch)
        return f"{major}.{minor}.{patch}"

    @classmethod
    def compare(cls, version_a: str, version_b: str) -> int:
        """-1 если A старше B, 0 если равны, 1 если A новее B."""
        a = cls.parse(version_a, as_tuple=True)
        b = cls.parse(version_b, as_tuple=True)
        if a > b:  # namedtuple сравнивается лексикографически: (major, minor, patch)
            return cls.BIGGER
        if a < b:
            return cls.SMALLER
        return cls.EQUAL