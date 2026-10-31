"""生成程序图标 build/assets/app.ico（QPainter 绘制，不使用任何表情或外部素材）。

ICO 内嵌 PNG（Vista 及以上支持），因此无需 Pillow：
    · ICONDIR + 每个尺寸的 ICONDIRENTRY + PNG 数据
"""
from __future__ import annotations

import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt6.QtCore import QBuffer, QByteArray
from PyQt6.QtGui import QGuiApplication

from shared.qt_icons import paint_icon

SIZES = [16, 32, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    """把指定尺寸的图标渲染为 PNG 字节。

    Args:
        size: 边长像素。

    Returns:
        PNG 数据。
    """
    pm = paint_icon('snake', size, '#0aa96a')
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.save(buf, 'PNG')
    buf.close()
    return bytes(ba)


def write_ico(path: str, images: list[tuple[int, bytes]]) -> None:
    """把多张 PNG 打包成 ICO 文件。

    Args:
        path: 输出路径。
        images: [(尺寸, PNG 数据)]。
    """
    count = len(images)
    header = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count
    entries = b''
    data = b''
    for size, png in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    with open(path, 'wb') as f:
        f.write(header + entries + data)


def main() -> int:
    """生成 app.ico。

    Returns:
        进程退出码。
    """
    app = QGuiApplication(sys.argv[:1])  # noqa: F841  （QPainter 需要 QGuiApplication）
    out_dir = os.path.join(ROOT, 'build', 'assets')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'app.ico')
    images = [(s, png_bytes(s)) for s in SIZES]
    write_ico(out, images)
    print('已生成图标 %s（%d 种尺寸）' % (out, len(images)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
