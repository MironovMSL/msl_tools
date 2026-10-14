"""core/link/scene_rate.py: frame rates as Maya names them, and the rate a .ma file was saved at."""
import os
import shutil
import tempfile
import unittest

from msl_tools.msl.core.link import scene_rate


class Rates(unittest.TestCase):
    def test_names(self):
        self.assertEqual((scene_rate.unit_for("30"), scene_rate.unit_for("24"), scene_rate.unit_for("29")),
                         ("ntsc", "film", ""))
        self.assertEqual((scene_rate.describe("film"), scene_rate.describe("23.976fps"), scene_rate.describe("odd")),
                         ("24 fps", "23.976 fps", "odd"))

    def test_a_ma_files_rate_is_read_from_its_head(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        scene = os.path.join(folder, "shot.ma")
        with open(scene, "w", encoding="utf-8") as handle:
            handle.write('//Maya ASCII 2024 scene\nrequires maya "2024";\n'
                         'currentUnit -l centimeter -a degree -t film;\ncreateNode transform -n "a";\n')
        self.assertEqual(scene_rate.file_unit(scene), "film")
        quoted = os.path.join(folder, "quoted.ma")
        with open(quoted, "w", encoding="utf-8") as handle:
            handle.write('currentUnit -l "centimeter" -a "degree" -t "ntsc";\n')
        self.assertEqual(scene_rate.file_unit(quoted), "ntsc")
        self.assertEqual(scene_rate.file_unit(os.path.join(folder, "missing.ma")), "")
        self.assertEqual(scene_rate.file_unit(os.path.join(folder, "binary.mb")), "")   # not read


if __name__ == "__main__":
    unittest.main()
