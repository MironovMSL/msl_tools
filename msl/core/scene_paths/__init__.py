"""Scene paths: absolute paths inside Maya scenes swapped for environment variables
("E:/branches/Animation/..." -> "$WG_ANIM/..."), so a scene opens on any machine whose
environment sets the variable. Qt-free.

- roots.py: which variables can stand for a folder (from Maya Gate's environments).
- ma_paths.py: finding the paths in a Maya ASCII scene and rewriting them in place, byte for byte.
"""
