"""
Unit tests of msl_tools - stdlib unittest only, so they run with any
Python 3.10+ and nothing to install:

    python -m unittest discover -s tests -t .

(from the repository root). Tests never touch the user's configs/ or
logs/: everything they write goes into a temporary folder.
"""
import sys
from pathlib import Path

# The repository folder IS the package msl_tools: its parent must be importable.
_PARENT = str(Path(__file__).resolve().parents[2])
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
