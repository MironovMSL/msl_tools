"""Standalone entry point of the setup window (tools/desktop/installer).

Run BY PATH — `python <root>/msl/run_installer.py` — by
setup_express_launcher.bat, after core/installer/runtime_bootstrap.py made
the Python environment. Unlike run_hub.py it can't be started as
`-m msl_tools.msl.run_installer`: setup runs from wherever the archive was
unpacked, and that folder is usually not named `msl_tools` (GitHub archives
unpack as "msl_tools-<tag>"), so the package isn't importable by name.
`_make_package_importable()` fixes that for this process.
"""
import sys
import types
from pathlib import Path


def _make_package_importable() -> None:
    """Makes `import msl_tools.msl...` work from this checkout / archive,
    whatever its folder is called. msl_tools is a namespace package (no
    __init__.py), so a module object whose __path__ is this folder is all
    Python needs."""
    root = Path(__file__).resolve().parents[1]  # <root>/msl/run_installer.py -> <root>
    if root.name == "msl_tools":
        if str(root.parent) not in sys.path:
            sys.path.insert(0, str(root.parent))
        return
    package = types.ModuleType("msl_tools")
    package.__path__ = [str(root)]
    sys.modules["msl_tools"] = package


def _use_own_taskbar_icon() -> None:
    """Windows groups a script's window under python(w).exe — and shows the
    Python icon on the taskbar — unless the process has its own AppUserModelID.
    Not the hub's: the setup is another program (and may run beside it)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("msl_tools.setup")


def main() -> None:
    _make_package_importable()
    _use_own_taskbar_icon()
    from msl_tools.msl.ui.app.application_context import QtApplicationContext
    from msl_tools.msl.tools.desktop.installer.installer_view import InstallerView

    with QtApplicationContext():
        window = InstallerView()
        window.show()


if __name__ == "__main__":
    main()
