"""tools/maya/launch_report.py: the link token is never printed (the report gets pasted into chats)."""
import unittest

from msl_tools.msl.tools.maya import launch_report
from msl_tools.msl.tools.maya.hub_link import TOKEN_VARIABLE


class TokenIsHidden(unittest.TestCase):
    def test_same_name_as_the_link_uses(self):
        self.assertIn(TOKEN_VARIABLE, launch_report._HIDDEN_VARIABLES)

    def test_token_value_not_in_the_lines(self):
        for full in (True, False):
            lines = launch_report._variable_lines(TOKEN_VARIABLE, "s3cr3t-token", full=full)
            self.assertEqual(lines, [f"  {TOKEN_VARIABLE} = (hidden)"])

    def test_other_variables_still_shown(self):
        self.assertEqual(launch_report._variable_lines("MSL_GATE_ENVIRONMENT", "Dev", full=False),
                         ["  MSL_GATE_ENVIRONMENT = Dev"])


if __name__ == "__main__":
    unittest.main()
