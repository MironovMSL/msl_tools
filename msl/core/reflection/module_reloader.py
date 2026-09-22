"""
Development-time reload of a Python package already imported into a running process (e.g. Maya).

Deliberately blunt: instead of importlib.reload()-ing module by module - which needs a correct
dependency order and silently leaves classes half-reloaded if one module in the middle fails -
every submodule of the package is simply dropped from sys.modules. Nothing runs here; the next
`import` of any of them picks up the change and re-executes that module from disk exactly like a
first-time import, in whatever order Python's normal import machinery resolves it.

Caveats worth knowing before wiring this into a "Reload" menu item:
  - Anything already holding a reference to an old class (an open window, a running instance)
    keeps behaving like the old code. Only code paths reached *after* the reload get the new
    version. For msl_tools this is fine for the main menu, since it's rebuilt from scratch on
    every reload; it is not a general hot-patch of already-open windows.
  - A class-level registry that lives on a module (e.g. a singleton keyed by class identity)
    starts empty again after its module is re-imported, because the class itself is a new
    object. A window built against the old singleton keeps its old instance; new code gets a
    fresh one.
"""

import logging
import sys

logger = logging.getLogger(__name__)


def unload_package(package_name: str) -> list[str]:
    """Removes `package_name` and every one of its submodules from sys.modules.

    Safe to call from a function that lives inside the very package being unloaded: a running
    function keeps executing off its module's old code object/globals even after that module's
    entry is deleted from sys.modules - deletion only affects what the *next* `import` sees.

    Args:
        package_name: Dotted root, e.g. "msl_tools". Submodules (msl_tools.msl.core...) are
            matched by prefix.

    Returns:
        The dotted names that were actually removed, in no particular order. Empty if the
        package was never imported - not an error, just nothing to do.
    """
    prefix = package_name + "."
    to_remove = [
        name for name in sys.modules
        if name == package_name or name.startswith(prefix)
    ]
    for name in to_remove:
        del sys.modules[name]
    if to_remove:
        logger.debug(f'Unloaded {len(to_remove)} module(s) under "{package_name}".')
    return to_remove