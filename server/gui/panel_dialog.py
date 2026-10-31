"""「访问密码 + 排行榜」面板对话框：HTML 只负责这两个功能，宿主为 QWebEngineView。"""
from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView


class PanelDialog(QDialog):
    """内嵌网页面板（访问密码与排行榜）。"""

    def __init__(self, url: str, parent=None):
        """初始化并加载页面。

        Args:
            url: 面板页面地址（如 http://127.0.0.1:8080/panel）。
            parent: 父窗口。
        """
        super().__init__(parent)
        self.setWindowTitle('访问密码与排行榜 · Play With Snake')
        self.resize(820, 680)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView(self)
        view.setUrl(QUrl(url))
        lay.addWidget(view)
        self.view = view
