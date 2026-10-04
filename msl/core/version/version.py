from collections import namedtuple
import re


class Version:
    """Semantic versions, pure: no I/O, nothing raised except by parse()."""

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
    # The FIRST major.minor.patch: "1.2.3", "v1.2.3", "MSL Tools v1.2.3", "1.2.3-rc1", "1.2.3.4" (-> 1.2.3).
    _FIRST_VERSION = re.compile(r"(?<![\d.])(\d+)\.(\d+)\.(\d+)(?!\d)")

    @classmethod
    def is_valid(cls, version_str: str, metadata_ok: bool = True) -> bool:
        pattern = cls._PATTERN_WITH_METADATA if metadata_ok else cls._PATTERN_STRICT
        return bool(re.match(pattern, str(version_str)))

    @classmethod
    def parse(cls, version_string: str, as_tuple: bool = False):
        """major.minor.patch of a version string; what stands before and after
        it is ignored ("v1.2.3-rc1" -> "1.2.3").

        The three numbers are taken as they stand — never pieced together
        from digits elsewhere in the string (that once read "v0.2.0-rc1"
        as 0.2.1).

        Raises:
            ValueError: no major.minor.patch in the string.
        """
        match = cls._FIRST_VERSION.search(version_string) if isinstance(version_string, str) else None
        if match is None:
            raise ValueError(f'Invalid version format: "{version_string}". Expected semantic versioning: "1.2.3".')
        major, minor, patch = (int(number) for number in match.groups())
        if as_tuple:
            return cls.SemanticVersion(major=major, minor=minor, patch=patch)
        return f"{major}.{minor}.{patch}"

    @classmethod
    def compare(cls, version_a: str, version_b: str) -> int:
        """1 if A is newer than B, -1 if older, 0 if the same (suffixes ignored)."""
        a = cls.parse(version_a, as_tuple=True)
        b = cls.parse(version_b, as_tuple=True)
        if a > b:  # a namedtuple compares field by field: (major, minor, patch)
            return cls.BIGGER
        if a < b:
            return cls.SMALLER
        return cls.EQUAL