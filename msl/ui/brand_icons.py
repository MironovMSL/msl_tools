# ui/brand_icons.py
"""Windows .ico files of our own app icons (assets/icons/brand/<name>.svg).

An .ico holds one picture per size; Windows picks the one that fits (16 px
in a window's corner, 24 / 32 on the taskbar, 48 + in Explorer) instead of
shrinking a single big one. Qt writes an .ico with one size only, so the
file is put together here: the standard header + one PNG per size (PNG
entries are what Windows Vista and later read).

    python -m msl_tools.msl.ui.brand_icons installer        # -> brand/installer.ico
"""
import struct
import sys
from pathlib import Path

import msl_tools.msl.ui.qt_bindings as qt
from msl_tools.msl.core.fs.manager import FileSystemManager

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _png(renderer, size: int) -> bytes:
    image = qt.QtGui.QImage(size, size, qt.QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(qt.QtCore.Qt.GlobalColor.transparent)
    painter = qt.QtGui.QPainter(image)
    painter.setRenderHint(qt.QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(painter, qt.QtCore.QRectF(0, 0, size, size))
    painter.end()
    data = qt.QtCore.QByteArray()
    buffer = qt.QtCore.QBuffer(data)
    buffer.open(qt.QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(svg: Path, target: Path, sizes=SIZES) -> Path:
    """Renders `svg` at every size into one .ico at `target`."""
    renderer = qt.QtSvg.QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise ValueError(f"Not a usable SVG: {svg}")
    pictures = [(size, _png(renderer, size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(pictures))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(pictures)
    entries, payload = b"", b""
    for size, png in pictures:
        side = 0 if size >= 256 else size  # 0 means 256 in an .ico entry
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    target.write_bytes(header + entries + payload)
    return target


def write_brand_ico(name: str) -> Path:
    folder = FileSystemManager.icons / "brand"
    return write_ico(folder / f"{name}.svg", folder / f"{name}.ico")


if __name__ == "__main__":
    application = qt.QtGui.QGuiApplication.instance() or qt.QtGui.QGuiApplication([])
    for brand_name in sys.argv[1:] or ["installer"]:
        print(write_brand_ico(brand_name))
