"""core/installer/runtime_bootstrap.py + setup_express_launcher.bat: the Python range
the hub's Qt supports. PySide6 6.8 has no wheels for Python 3.14 — pip would fail
with "no matching distribution" on python.org's default download."""
import contextlib
import io
import re
import unittest
from pathlib import Path
from unittest import mock

from msl_tools.msl.core.installer import runtime_bootstrap as bootstrap

REPO = Path(__file__).resolve().parents[2]


class SupportedPython(unittest.TestCase):
    def run_main(self, version: tuple) -> tuple[int, str]:
        output = io.StringIO()
        with mock.patch.object(bootstrap.sys, "version_info", version + (0, "final", 0)), \
                mock.patch.object(bootstrap, "ensure", side_effect=AssertionError("must not install")), \
                contextlib.redirect_stdout(output):
            return bootstrap.main(["--run", "x.py"]), output.getvalue()

    def test_too_new_is_refused_with_a_clear_message(self):
        code, text = self.run_main((3, 14))
        self.assertEqual(code, 1)
        self.assertIn("too new", text)
        self.assertIn("3.13", text)

    def test_too_old_is_refused(self):
        code, text = self.run_main((3, 9))
        self.assertEqual(code, 1)
        self.assertIn("3.10", text)

    def test_the_bat_names_the_same_range(self):
        bat = (REPO / "setup_express_launcher.bat").read_text(encoding="ascii")
        low, high = re.search(r"\((\d+), (\d+)\) <= sys\.version_info\[:2\] <= \((\d+), (\d+)\)", bat).group(1, 2), \
            re.search(r"<= \((\d+), (\d+)\) else 1", bat).group(1, 2)
        self.assertEqual(tuple(map(int, low)), bootstrap.MINIMUM_PYTHON)
        self.assertEqual(tuple(map(int, high)), bootstrap.NEWEST_PYTHON)
        newest = "%d.%d" % bootstrap.NEWEST_PYTHON
        self.assertIn(f"for %%V in ({newest} ", bat)  # the launcher tries the newest supported one first

    def test_the_bat_stays_crlf_ascii(self):
        raw = (REPO / "setup_express_launcher.bat").read_bytes()
        self.assertTrue(raw.isascii())
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))


if __name__ == "__main__":
    unittest.main()
