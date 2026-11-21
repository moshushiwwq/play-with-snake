"""服务端运行日志窗口：从托盘菜单打开，按秒增量刷新最近日志。

日志数据来自 LogBus 的内存环形缓冲；用户也可以直接打开
`server_data/server.log` 查看包含历史运行记录的完整文件。
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from server.sys.logs import LogBus


class LogWindow(QDialog):
    """只读运行日志窗口（自动刷新、可打开日志文件）。"""

    MAX_LINES = 800

    def __init__(self, logbus: LogBus, data_dir: str, parent=None):
        """创建日志窗口。

        Args:
            logbus: 服务端日志总线。
            data_dir: 数据目录（用于定位 server.log）。
            parent: 父窗口（可为空）。
        """
        super().__init__(parent)
        self.logbus = logbus
        self.log_path = os.path.join(data_dir, 'server.log')
        self._last_item = None
        self.setWindowTitle('运行日志 · Play With Snake 服务器')
        self.resize(780, 540)
        self.setMinimumSize(560, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self.info = QLabel('等待日志…')
        self.info.setStyleSheet('color:#6f8f8a;')
        bar.addWidget(self.info, 1)

        btn_refresh = QPushButton('刷新')
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_refresh)

        btn_file = QPushButton('打开日志文件')
        btn_file.clicked.connect(self._open_file)
        bar.addWidget(btn_file)

        btn_close = QPushButton('关闭')
        btn_close.clicked.connect(self.hide)
        bar.addWidget(btn_close)
        root.addLayout(bar)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont('Consolas')
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPixelSize(13)
        self.editor.setFont(font)
        self.editor.setStyleSheet(
            'QPlainTextEdit{background:#0b1a19;color:#c9ded8;border:1px solid #1d3a35;'
            'border-radius:10px;padding:10px;}'
        )
        root.addWidget(self.editor, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    # ---------------------------------------------------------------- 数据
    def refresh(self) -> None:
        """从 LogBus 拉取最近日志并刷新文本。"""
        rows = self.logbus.recent(self.MAX_LINES)
        last = rows[-1] if rows else None
        # 以最后一条日志对象的身份判断是否有新增：缓冲达到上限后条数不再变化
        if last is self._last_item:
            return
        self._last_item = last
        scroll = self.editor.verticalScrollBar()
        at_bottom = scroll.value() >= scroll.maximum() - 4
        old_value = scroll.value()
        text = '\n'.join('[%s] %s' % (r.get('ts', ''), r.get('text', '')) for r in rows)
        self.editor.setPlainText(text)
        if at_bottom:
            scroll.setValue(scroll.maximum())
        else:
            scroll.setValue(min(old_value, scroll.maximum()))
        self.info.setText('当前会话 %d 条 · 文件：%s' % (len(rows), self.log_path))

    def _open_file(self) -> None:
        """用系统默认程序打开完整日志文件。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_path))

    # ---------------------------------------------------------------- 生命周期
    def showEvent(self, event) -> None:  # noqa: N802
        """显示时立即刷新并开启定时器。"""
        super().showEvent(event)
        self._last_item = None
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        """隐藏时停止定时器。"""
        self._timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭按钮只隐藏窗口，下次可从托盘再次打开。"""
        self._timer.stop()
        event.ignore()
        self.hide()
