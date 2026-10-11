# tools/maya/controls/panel_common.py
"""What the parts of the Controls panel share: the fixed choices and sizes (no Qt, no Maya)."""

ALL = "All"
OFFSET_MODES = ("None", "Groups", "Matrix")
DRIVES = ("None", "Shape", "Constrain", "Matrix")
SHAPES_FILTER = "MSL control shapes (*.json)"
EDITOR_HEIGHT = 456
THUMB = 38
CELL = THUMB + 8
FAVORITE_ROWS, LIBRARY_ROWS = 1, 3         # how tall the grid is: your shapes (one row that
                                            # scrolls sideways) / the whole library
STAR = 13                                  # the star in a tile's corner (and the spot that takes its click)
# the shapes a fresh install starts with as favorites — the ones every rig uses
FIRST_FAVORITES = ("circle", "square", "cube", "sphere", "diamond", "arrow", "double_arrow", "four_arrows",
                   "pin", "locator", "cross", "root")
