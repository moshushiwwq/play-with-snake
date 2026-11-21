"""客户端启动动画：无边框圆角窗口 + 渐变光晕 + 游动小蛇 + 动态进度条。

设计要点：
    · 顶层窗口使用 WA_TranslucentBackground，圆角由 QPainter 直接绘制，
      不依赖系统窗口边框，四周保留阴影绘制空间；
    · 蛇身沿参数化曲线游动，头部带眼睛与呼吸光晕，光环与星点持续旋转闪烁；
    · 进度条随启动时长填充，结束前整体淡出，最后发出 finished 信号。
"""
from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QFont, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

# 窗口与面板尺寸
WINDOW_W = 720
WINDOW_H = 420
MARGIN = 26
RADIUS = 34


class SplashScreen(QWidget):
    """圆角动态启动动画窗口。"""

    finished = pyqtSignal()

    def __init__(self, version: str, duration_ms: int = 2100, parent=None):
        """创建启动动画。

        Args:
            version: 版本号文本。
            duration_ms: 动画总时长（毫秒）。
            parent: 父对象（可为空）。
        """
        super().__init__(parent)
        self.version = version
        self.duration = max(600, int(duration_ms)) / 1000.0
        self._started = 0.0
        self._emitted = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setWindowTitle('Play With Snake')
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        """把窗口移动到主屏幕可用区域中央。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center() - self.rect().center())

    def start(self) -> None:
        """显示并开始动画。"""
        self._started = time.perf_counter()
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        """停止动画（不发出 finished 信号）。"""
        self._timer.stop()

    def _progress(self) -> float:
        """当前动画进度（0.0 - 1.0）。"""
        if not self._started:
            return 0.0
        return min(1.0, (time.perf_counter() - self._started) / self.duration)

    def _on_tick(self) -> None:
        """定时刷新；结束时淡出并发出信号。"""
        t = self._progress()
        if t >= 1.0:
            self._timer.stop()
            if not self._emitted:
                self._emitted = True
                self.finished.emit()
            return
        # 结束前 12% 的时长内整体淡出
        if t > 0.88:
            self.setWindowOpacity(max(0.0, (1.0 - t) / 0.12))
        self.update()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭时停止定时器。"""
        self._timer.stop()
        super().closeEvent(event)

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        """绘制整个动画画面。"""
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        t = self._progress()
        self._paint_panel(painter, t)
        self._paint_badge(painter, t)
        self._paint_text(painter, t)
        painter.end()

    def _paint_panel(self, painter: QPainter, t: float) -> None:
        """绘制圆角面板、阴影与背景光效。

        Args:
            painter: 画笔。
            t: 动画进度。
        """
        rect = QRectF(MARGIN, MARGIN, self.width() - 2 * MARGIN, self.height() - 2 * MARGIN)

        # 外层柔和阴影
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(18, 0, -1):
            alpha = int(2 + (18 - i) * 0.55)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(
                rect.adjusted(-i * 0.55, -i * 0.35 + 5, i * 0.55, i * 0.75 + 5),
                RADIUS + i * 0.55, RADIUS + i * 0.55,
            )

        # 主体渐变背景
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0.0, QColor('#071a17'))
        bg.setColorAt(0.52, QColor('#0a2226'))
        bg.setColorAt(1.0, QColor('#102b34'))
        painter.setBrush(bg)
        painter.setPen(QPen(QColor(65, 227, 154, 80), 1.2))
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        # 顶部高光
        sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + rect.height() * 0.5))
        sheen.setColorAt(0.0, QColor(255, 255, 255, 24))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sheen)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        # 右下角装饰弧线
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(43, 182, 255, 32), 1.2))
        painter.drawArc(rect.adjusted(190, 130, -18, -8), -20 * 16, 130 * 16)
        painter.setPen(QPen(QColor(65, 227, 154, 26), 1.2))
        painter.drawArc(rect.adjusted(230, 160, -18, -8), -10 * 16, 110 * 16)

        # 细微网格点
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(120, 255, 205, 10))
        x = int(rect.left()) + 18
        while x < rect.right() - 12:
            y = int(rect.top()) + 18
            while y < rect.bottom() - 12:
                painter.drawEllipse(QPointF(x, y), 1.0, 1.0)
                y += 26
            x += 26

        # 进度驱动的呼吸光晕
        pulse = 0.5 + 0.5 * math.sin(t * math.tau * 1.6)
        glow = QRadialGradient(QPointF(rect.left() + 180, rect.center().y()), 250)
        glow.setColorAt(0.0, QColor(65, 227, 154, int(18 + 14 * pulse)))
        glow.setColorAt(1.0, QColor(65, 227, 154, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(rect.left() + 180, rect.center().y()), 250, 250)

    def _paint_badge(self, painter: QPainter, t: float) -> None:
        """绘制左侧圆环徽章、游动小蛇与星点。

        Args:
            painter: 画笔。
            t: 动画进度。
        """
        cx = MARGIN + 178
        cy = self.height() / 2 + 4
        radius = 104.0
        phase = t * math.tau

        # 呼吸光晕
        halo = QRadialGradient(QPointF(cx, cy), radius * 1.5)
        halo.setColorAt(0.0, QColor(65, 227, 154, 46))
        halo.setColorAt(0.55, QColor(43, 182, 255, 16))
        halo.setColorAt(1.0, QColor(65, 227, 154, 0))
        painter.setBrush(halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius * 1.5, radius * 1.5)

        # 徽章底盘
        painter.setBrush(QColor(7, 24, 22, 224))
        painter.setPen(QPen(QColor(65, 227, 154, 54), 1.0))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        # 旋转的锥形光环
        conic = QConicalGradient(QPointF(cx, cy), -90 + (phase * 57.2958) % 360)
        conic.setColorAt(0.0, QColor(65, 227, 154, 235))
        conic.setColorAt(0.18, QColor(43, 182, 255, 120))
        conic.setColorAt(0.42, QColor(65, 227, 154, 0))
        conic.setColorAt(0.78, QColor(43, 182, 255, 40))
        conic.setColorAt(1.0, QColor(65, 227, 154, 235))
        ring = QPen(QBrush(conic), 4.0)
        ring.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(ring)
        painter.drawEllipse(QPointF(cx, cy), radius - 5, radius - 5)

        # 参数化蛇身路径
        points: list[QPointF] = []
        count = 150
        swing = phase * 1.35
        for i in range(count):
            a = -math.pi / 2 + (i / (count - 1)) * math.tau * 0.96 + swing * 0.22
            r = 60 + 13 * math.sin(a * 3 + phase * 2.4)
            points.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        path = QPainterPath(points[0])
        for pt in points[1:]:
            path.lineTo(pt)

        # 蛇身外描边
        outline = QPen(QColor(0, 0, 0, 90), 25.0)
        outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(outline)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # 蛇身渐变主体
        body = QLinearGradient(QPointF(cx - radius, cy - radius), QPointF(cx + radius, cy + radius))
        body.setColorAt(0.0, QColor('#8effc8'))
        body.setColorAt(0.45, QColor('#41e39a'))
        body.setColorAt(1.0, QColor('#1fb6b0'))
        body_pen = QPen(QBrush(body), 18.0)
        body_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        body_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(body_pen)
        painter.drawPath(path)

        # 蛇身高光
        highlight = QPen(QColor(255, 255, 255, 42), 4.0)
        highlight.setCapStyle(Qt.PenCapStyle.RoundCap)
        highlight.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(highlight)
        painter.drawPath(path)

        # 蛇头与眼睛
        head = points[-1]
        prev = points[-2]
        dx, dy = head.x() - prev.x(), head.y() - prev.y()
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        painter.setBrush(QColor('#41e39a'))
        painter.setPen(QPen(QColor(4, 26, 21), 2.0))
        painter.drawEllipse(head, 15.0, 15.0)
        blink = 1.0 if (t * 3.2) % 1.0 > 0.08 else 0.25
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#06231d'))
        for side in (-1, 1):
            eye = QPointF(head.x() + ux * 5 + px * 5 * side, head.y() + uy * 5 + py * 5 * side)
            painter.drawEllipse(eye, 2.7, 2.7 * blink)

        # 吐信（周期性伸出）
        if math.sin(t * math.tau * 2.2) > 0.55:
            tongue = QPainterPath(QPointF(head.x() + ux * 13, head.y() + uy * 13))
            tongue.lineTo(QPointF(head.x() + ux * 22 + px * 3, head.y() + uy * 22 + py * 3))
            tongue.moveTo(QPointF(head.x() + ux * 22 + px * 3, head.y() + uy * 22 + py * 3))
            tongue.lineTo(QPointF(head.x() + ux * 26 - px * 2, head.y() + uy * 26 - py * 2))
            pen = QPen(QColor('#ff6b81'), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tongue)

        # 环绕星点
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(14):
            a = i * math.tau / 14 + phase * 0.18
            r = radius + 16 + 9 * math.sin(i * 1.7)
            twinkle = (math.sin(t * math.tau * 2.6 + i * 1.31) + 1.0) / 2.0
            alpha = int(26 + 130 * twinkle)
            size = 1.2 + 2.0 * twinkle
            color = QColor(120, 255, 205, alpha) if i % 3 else QColor(120, 205, 255, alpha)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)), size, size)

    def _paint_text(self, painter: QPainter, t: float) -> None:
        """绘制标题、副标题、版本徽标、状态文字与进度条。

        Args:
            painter: 画笔。
            t: 动画进度。
        """
        x = 382.0
        top = 118.0
        # 文本淡入
        fade = max(0.0, min(1.0, (t - 0.03) / 0.3))
        painter.setOpacity(fade)

        # 标题渐变字
        title_font = QFont('Microsoft YaHei UI')
        title_font.setPixelSize(34)
        title_font.setWeight(QFont.Weight.Bold)
        painter.setFont(title_font)
        title_grad = QLinearGradient(x, top, x + 300, top + 44)
        title_grad.setColorAt(0.0, QColor('#f2fff9'))
        title_grad.setColorAt(0.62, QColor('#b9ffdf'))
        title_grad.setColorAt(1.0, QColor('#41e39a'))
        painter.setPen(QPen(QBrush(title_grad), 1.0))
        painter.drawText(QRectF(x, top, 320, 48),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         'Play With Snake')

        # 副标题
        sub_font = QFont('Microsoft YaHei UI')
        sub_font.setPixelSize(15)
        painter.setFont(sub_font)
        painter.setPen(QColor('#8fb3ad'))
        painter.drawText(QRectF(x, top + 58, 320, 26),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         '贪吃蛇大冒险')

        # 版本徽标
        pill = QRectF(x, top + 92, 92, 28)
        painter.setBrush(QColor(65, 227, 154, 22))
        painter.setPen(QPen(QColor(65, 227, 154, 92), 1.0))
        painter.drawRoundedRect(pill, 14, 14)
        ver_font = QFont('Microsoft YaHei UI')
        ver_font.setPixelSize(12)
        ver_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(ver_font)
        painter.setPen(QColor('#b6f2d8'))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), 'v' + self.version)

        # 动态状态文字
        status_font = QFont('Microsoft YaHei UI')
        status_font.setPixelSize(13)
        painter.setFont(status_font)
        painter.setPen(QColor('#6f8f8a'))
        dots = '·' * (1 + int(t * 9) % 3)
        painter.drawText(QRectF(x, top + 148, 300, 24),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         '正在准备游戏界面 ' + dots)

        # 进度条
        bar = QRectF(x, top + 186, 300, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22))
        painter.drawRoundedRect(bar, 3.5, 3.5)

        ratio = min(1.0, t / 0.88)
        fill_w = bar.width() * ratio
        if fill_w > 1:
            fill = QLinearGradient(bar.topLeft(), bar.topRight())
            fill.setColorAt(0.0, QColor('#41e39a'))
            fill.setColorAt(1.0, QColor('#2bb6ff'))
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(bar.left(), bar.top(), fill_w, bar.height()), 3.5, 3.5)

            # 进度条头部光点
            head_x = bar.left() + fill_w
            glow = QRadialGradient(QPointF(head_x, bar.center().y()), 12)
            glow.setColorAt(0.0, QColor(180, 255, 225, 190))
            glow.setColorAt(1.0, QColor(65, 227, 154, 0))
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(head_x, bar.center().y()), 12, 12)

        painter.setOpacity(1.0)
