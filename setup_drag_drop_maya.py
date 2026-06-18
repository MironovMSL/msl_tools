"""
Drag and drop this file into the viewport to run the package installer
"""

import sys
import os


def onMayaDroppedPythonFile(*args):
    """
    Runs when file is dropped into the Maya's viewport
    The name of this function is what Maya expects/uses as entry point, so it cannot be changed
    """
    if sys.version_info.major < 3:
        # String formatting for this error should remain compatible to Python 2 to guarantee feedback
        user_version = "{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        error = "Incompatible Python Version. Expected to find 3+. Found version: " + user_version
        error += " For Python 2, use an older version of GT-Tools below 3. (e.g. 2.5.5)\n"
        raise ImportError(error)

    # Initial Feedback
    print("_" * 40)
    print("Initializing Drag-and-Drop Setup...")

    # # Remove existing loaded modules (So it uses the new one)
    # try:
    #     from gt.core.setup import remove_package_loaded_modules
    # except:
    #     from gt.utils.setup_utils import remove_package_loaded_modules  # Temporarily to transition into new pattern
    #
    # removed_modules = remove_package_loaded_modules()
    # if removed_modules:
    #     print("Removing package loaded modules...")

    def remove_package_loaded_modules():
        """
        Removes modules loaded by this package.
        Returns:
            list: List of removed module names. (str)
        """
        modules_to_remove = []
        modules_to_remove.extend(PACKAGE_REQUIREMENTS)
        modules_to_remove.extend(PACKAGE_DIRS)
        removed_modules = []
        for module_name in modules_to_remove:
            removed = remove_modules_startswith(module_name)
            if removed:
                removed_modules.extend(removed)
        return removed_modules

    def remove_modules_startswith(prefix):
        """
        Removes modules from "sys.modules" dictionary that start with the specified prefix.
        Args:
            prefix (str): The prefix that the module names should start with.

        Returns:
            list: A list of module names that were removed.
        """
        modules_to_remove = set()
        # Iterate through all loaded modules
        for module_name in list(sys.modules.keys()):
            if module_name.startswith(prefix):
                modules_to_remove.add(module_name)
        # Remove the modules from the sys.modules dictionary
        for module_name in list(modules_to_remove):
            del sys.modules[module_name]
        return list(modules_to_remove)

    # Prepend sys path with drag and drop location
    print("Prepending system paths with drag-and-drop location...")
    parent_dir = os.path.dirname(__file__)
    print(parent_dir)
    print('Current location: "' + parent_dir + '"')
    package_dir = os.path.join(parent_dir, "msl")
    print(package_dir)
    # sys.path.insert(0, parent_dir)
    # sys.path.insert(0, package_dir)

    # Import and run installer GUI
    print("Initializing installer GUI...")
    # import gt.tools.package_setup as package_setup
    #
    # package_setup.launcher_entry_point()
