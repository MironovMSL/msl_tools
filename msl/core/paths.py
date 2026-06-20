"""
Сlass of paths
"""

from pathlib import Path

class Paths(object):
    def __init__(self):
        self.core      = Path(__file__).resolve().parent
        self.msl       = self.core.parent
        self.msl_tools = self.msl.parent
        self.config    = self.msl / 'config'
        self.tools     = self.msl / 'tools'


if __name__ == '__main__':
    paths = Paths()
    print(paths.msl_tools)
    print(paths.msl)
    print(paths.core)
    print(paths.config)
    print(paths.tools)

