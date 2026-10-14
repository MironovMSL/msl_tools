"""core/link/scene_settings.py: the Scene tab's settings beside the frame rate, and their launch variables."""
import unittest

from msl_tools.msl.core.link import scene_settings, variables


class SceneSettings(unittest.TestCase):
    def test_a_range_in_the_forms_people_type(self):
        for text in ("1-120", "1 120", "1..120", "1–120", " 1 to 120 "):
            self.assertEqual(scene_settings.parse_range(text), (1, 120), text)
        self.assertEqual(scene_settings.parse_range("-10-24.5"), (-10, 24.5))
        for text in ("", "120-1", "5-5", "a-b", "1-", "1,120"):
            self.assertIsNone(scene_settings.parse_range(text), text)
        self.assertEqual(scene_settings.range_text((1, 120)), "1 120")

    def test_only_known_values_are_kept_and_passed(self):
        stored = {"range": "1-48", "units": "m", "up": "z", "speed": "realtime", "tangents": "stepped",
                  "autokey": "on", "fps": "30", "other": "x"}
        self.assertEqual(scene_settings.cleaned(stored),
                         {"range": "1 48", "units": "m", "up": "z", "speed": "realtime", "tangents": "stepped",
                          "autokey": "on"})
        self.assertEqual(scene_settings.cleaned({"units": "km", "up": "x", "range": "48-1"}),
                         dict.fromkeys(scene_settings.KEYS, ""))
        launch = scene_settings.to_environment(stored)
        self.assertEqual(launch, {variables.SCENE_RANGE: "1 48", variables.SCENE_UNITS: "m", variables.SCENE_UP: "z",
                                  variables.SCENE_SPEED: "realtime", variables.SCENE_TANGENTS: "stepped",
                                  variables.SCENE_AUTO_KEY: "on"})
        self.assertEqual(scene_settings.to_environment({}), {})          # "as is": nothing passed
        self.assertEqual(scene_settings.from_environment(launch), scene_settings.cleaned(stored))
        self.assertTrue(all(name in variables.ALL for name in launch))

    def test_said_in_plain_words(self):
        self.assertEqual(scene_settings.describe({"range": "1 48", "up": "z", "tangents": "stepped", "autokey": "off"}),
                         ["range 1–48", "Z up", "stepped keys", "auto key off"])


if __name__ == "__main__":
    unittest.main()
