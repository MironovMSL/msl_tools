# --- MSL tools: main menu ---
from msl_tools.msl.startup import bootstrap
bootstrap()

# --- MSL tools: main menu ---
import sys
MSL_PARENT_DIR = r"H:\ProjectsDev\MSL_Others"
if MSL_PARENT_DIR not in sys.path:
    sys.path.insert(0, MSL_PARENT_DIR)
from msl_tools.msl.startup import bootstrap
bootstrap()
