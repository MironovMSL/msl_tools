# ui/maya_menu_icons.py
"""The PNG icons of the MSL menu inside Maya, rendered from our own SVGs.

Maya's classic menus draw an item's image from a FILE (cmds.menuItem
image=...), and the menu is built without Qt on purpose (fast startup,
core/maya_menu/menu_spec.py) — so the icons are rendered ahead of time and
committed: assets/icons/menu/<name>.png. Run this module after changing
MENU_ICONS or one of the SVGs:

    python -m msl_tools.msl.ui.maya_menu_icons

The one-color SVGs (#000000 = the color placeholder) are drawn in COLOR, a
light grey that reads on Maya's dark menus (its own menu text is about as
light), on Maya's icon canvas: 32 px, the shape inset like Maya's own menu
icons.
"""
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.manager import FileSystemManager

# menu icon name -> (sub folder, SVG name) under assets/icons; names used in tools/maya/menu_definition.py
MENU_ICONS = {
    "playblast": ("actions", "clapper"),     # the Playblast window's own icon
    "dev": ("actions", "code"),
    "print_hello": ("actions", "play"),
    "print_environment": ("actions", "hud"),
    "launch_report": ("actions", "report"),
    "reload_code": ("actions", "restart"),
    "rebuild_menu": ("actions", "repeat"),
}
COLOR = "#c8c8c8"
CANVAS = 32      # Maya's menu icons (menuIconHelp.png & co.) are 32 x 32
SHAPE = 24       # the 24-grid shape, drawn at its own size in the middle


def render(target_dir: Path | None = None) -> list:
    """Writes every MENU_ICONS entry as a PNG; returns the files written."""
    target_dir = Path(target_dir or FileSystemManager.icons / "menu")
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (sub_folder, svg_name) in MENU_ICONS.items():
        source = FileSystemManager.icons / sub_folder / f"{svg_name}.svg"
        svg = source.read_text(encoding="utf-8").replace("#000000", COLOR)
        renderer = qt.QtSvg.QSvgRenderer(qt.QtCore.QByteArray(svg.encode("utf-8")))
        image = qt.QtGui.QImage(CANVAS, CANVAS, qt.QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(qt.QtCore.Qt.GlobalColor.transparent)
        painter = qt.QtGui.QPainter(image)
        painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
        inset = (CANVAS - SHAPE) / 2
        renderer.render(painter, qt.QtCore.QRectF(inset, inset, SHAPE, SHAPE))
        painter.end()
        target = target_dir / f"{name}.png"
        image.save(str(target), "PNG")
        written.append(target)
    return written


if __name__ == "__main__":
    application = qt.QtGui.QGuiApplication.instance() or qt.QtGui.QGuiApplication([])
    for path in render():
        print(path)
