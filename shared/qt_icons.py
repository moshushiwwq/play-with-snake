"""共享的 Qt 自绘图标工具（客户端与服务端共用，禁止使用表情符号）。"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def paint_icon(name: str, size: int, color: str) -> QPixmap:
    """把指定图标画到透明底图上。

    Args:
        name: 图标名（play/stop/gear/shield/key/trophy/globe/house/users/list/
              trash/file/clipboard/warn/info/lock/sliders/snake）。
        size: 画布边长（像素）。
        color: 线条颜色。

    Returns:
        QPixmap。
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = QColor(color)
    u = size / 24.0
    pen = QPen(c, max(1.0, 1.8 * u))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1 * u, y1 * u), QPointF(x2 * u, y2 * u))

    if name == 'play':
        path = QPainterPath()
        path.moveTo(7.8 * u, 5.2 * u)
        path.lineTo(18.6 * u, 12 * u)
        path.lineTo(7.8 * u, 18.8 * u)
        path.closeSubpath()
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
    elif name == 'stop':
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(6.6 * u, 6.6 * u, 10.8 * u, 10.8 * u), 2.2 * u, 2.2 * u)
    elif name == 'gear':
        p.drawEllipse(QPointF(12 * u, 12 * u), 3.3 * u, 3.3 * u)
        for ang in range(0, 360, 45):
            r1, r2 = 5.0 * u, 8.2 * u
            a = math.radians(ang)
            line(12 + math.cos(a) * r1, 12 + math.sin(a) * r1,
                 12 + math.cos(a) * r2, 12 + math.sin(a) * r2)
    elif name == 'shield':
        path = QPainterPath()
        path.moveTo(12 * u, 3 * u)
        path.lineTo(20 * u, 6.6 * u)
        path.lineTo(20 * u, 12.7 * u)
        path.quadTo(20 * u, 18.3 * u, 12 * u, 21 * u)
        path.quadTo(4 * u, 18.3 * u, 4 * u, 12.7 * u)
        path.lineTo(4 * u, 6.6 * u)
        path.closeSubpath()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        line(8.6, 11.8, 11.2, 14.4)
        line(11.2, 14.4, 15.6, 9.4)
    elif name == 'key':
        p.drawEllipse(QPointF(8.4 * u, 8.4 * u), 4 * u, 4 * u)
        line(11.2, 11.2, 20, 20)
        line(17.4, 17.4, 19.4, 15.4)
        line(15, 15, 17, 13)
    elif name == 'trophy':
        line(7.4, 4.4, 16.6, 4.4)
        line(7.4, 4.4, 7.4, 9)
        line(16.6, 4.4, 16.6, 9)
        p.drawArc(QRectF(7.4 * u, 4.4 * u, 9.2 * u, 9.2 * u), 180 * 16, 180 * 16)
        line(5, 8, 7.4, 8)
        line(4.6, 5.6, 4.6, 7.8)
        line(19, 8, 16.6, 8)
        line(19.4, 5.6, 19.4, 7.8)
        line(12, 13.6, 12, 16.8)
        line(8.6, 19.6, 15.4, 19.6)
    elif name == 'globe':
        p.drawEllipse(QPointF(12 * u, 12 * u), 8.6 * u, 8.6 * u)
        line(3.4, 12, 20.6, 12)
        p.drawEllipse(QPointF(12 * u, 12 * u), 3.4 * u, 8.6 * u)
    elif name == 'house':
        line(3.4, 11.4, 12, 4.2)
        line(12, 4.2, 20.6, 11.4)
        line(5.4, 10, 5.4, 19.8)
        line(18.6, 10, 18.6, 19.8)
        line(5.4, 19.8, 18.6, 19.8)
    elif name == 'users':
        p.drawEllipse(QPointF(9.4 * u, 8.6 * u), 3.2 * u, 3.2 * u)
        p.drawArc(QRectF(3.6 * u, 13.4 * u, 11.6 * u, 11.6 * u), 0, 180 * 16)
        p.drawArc(QRectF(12.4 * u, 12.2 * u, 8.4 * u, 9.0 * u), 0, 150 * 16)
    elif name == 'list':
        p.drawRoundedRect(QRectF(5.4 * u, 3.6 * u, 13.2 * u, 16.8 * u), 2.2 * u, 2.2 * u)
        line(8.6, 8.4, 15.4, 8.4)
        line(8.6, 12, 15.4, 12)
        line(8.6, 15.6, 13, 15.6)
    elif name == 'trash':
        line(4.8, 6.8, 19.2, 6.8)
        line(9.6, 6.8, 9.6, 4.6)
        line(9.6, 4.6, 14.4, 4.6)
        line(14.4, 4.6, 14.4, 6.8)
        line(6.6, 6.8, 7.6, 19.4)
        line(7.6, 19.4, 16.4, 19.4)
        line(16.4, 19.4, 17.4, 6.8)
    elif name == 'file':
        line(6.2, 3.6, 13.6, 3.6)
        line(13.6, 3.6, 17.8, 7.8)
        line(17.8, 7.8, 17.8, 20.4)
        line(17.8, 20.4, 6.2, 20.4)
        line(6.2, 20.4, 6.2, 3.6)
        line(13.4, 3.6, 13.4, 8)
        line(13.4, 8, 17.8, 8)
    elif name == 'clipboard':
        p.drawRoundedRect(QRectF(6.4 * u, 5 * u, 11.2 * u, 15.4 * u), 2 * u, 2 * u)
        line(9.4, 4.2, 14.6, 4.2)
        line(9.4, 6.8, 14.6, 6.8)
        line(9.4, 11, 14.6, 11)
        line(9.4, 14.6, 14.6, 14.6)
    elif name == 'warn':
        path = QPainterPath()
        path.moveTo(12 * u, 3.6 * u)
        path.lineTo(21.4 * u, 20 * u)
        path.lineTo(2.6 * u, 20 * u)
        path.closeSubpath()
        p.drawPath(path)
        line(12, 9.4, 12, 14)
        line(12, 16.4, 12, 17)
    elif name == 'info':
        p.drawEllipse(QPointF(12 * u, 12 * u), 8.6 * u, 8.6 * u)
        line(12, 11, 12, 16.6)
        line(12, 7.8, 12, 8.4)
    elif name == 'lock':
        p.drawRoundedRect(QRectF(4.6 * u, 10.4 * u, 14.8 * u, 9.6 * u), 2.3 * u, 2.3 * u)
        p.drawArc(QRectF(8.1 * u, 3.6 * u, 7.8 * u, 7.8 * u), 0, 180 * 16)
        line(8.1, 7.5, 8.1, 10.4)
        line(15.9, 7.5, 15.9, 10.4)
        p.drawEllipse(QPointF(12 * u, 15.3 * u), 1.4 * u, 1.4 * u)
    elif name == 'sliders':
        line(4, 8, 12, 8)
        line(16, 8, 20, 8)
        line(4, 16, 8, 16)
        line(12, 16, 20, 16)
        p.drawEllipse(QPointF(14 * u, 8 * u), 2.2 * u, 2.2 * u)
        p.drawEllipse(QPointF(10 * u, 16 * u), 2.2 * u, 2.2 * u)
    elif name == 'snake':
        path = QPainterPath()
        path.moveTo(5 * u, 17 * u)
        path.cubicTo(5 * u, 13.6 * u, 7.6 * u, 11.4 * u, 10.6 * u, 11.4 * u)
        path.lineTo(14 * u, 11.4 * u)
        path.cubicTo(15.5 * u, 11.4 * u, 16.5 * u, 10.5 * u, 16.5 * u, 9.2 * u)
        path.cubicTo(16.5 * u, 7.9 * u, 15.5 * u, 7 * u, 14 * u, 7 * u)
        path.lineTo(8.6 * u, 7 * u)
        p.drawPath(path)
        p.setBrush(c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(17.8 * u, 17.4 * u), 2.6 * u, 2.6 * u)
    else:
        p.drawEllipse(QPointF(12 * u, 12 * u), 7 * u, 7 * u)

    p.end()
    return pm


def make_icon(name: str, color: str = '#0aa96a', size: int = 20) -> QIcon:
    """生成自绘 QIcon（含 2x 高清档）。"""
    icon = QIcon()
    icon.addPixmap(paint_icon(name, size, color))
    icon.addPixmap(paint_icon(name, size * 2, color))
    return icon


def make_pixmap(name: str, color: str = '#0aa96a', size: int = 20) -> QPixmap:
    """生成自绘 QPixmap（按钮前置图标用）。"""
    return paint_icon(name, size, color)
