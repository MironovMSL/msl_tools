"""
DEV-ONLY userSetup.py for msl_tools.

Copy to (or append into) your existing file:
    Documents/maya/2025/scripts/userSetup.py

MSL_PARENT_DIR is the folder that CONTAINS the "msl_tools" repo folder (that is what makes
"import msl_tools.msl..." work).
"""

import sys

MSL_PARENT_DIR = r"H:\ProjectsDev\MSL_Others"

# try/except: a failure in msl_tools must never break the rest of the user's startup.
try:
    if MSL_PARENT_DIR not in sys.path:
        sys.path.insert(0, MSL_PARENT_DIR)
    from msl_tools.msl.startup import bootstrap
    bootstrap()
except Exception as e:
    print(f"MSL: startup failed: {e}")