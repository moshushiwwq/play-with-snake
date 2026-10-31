"""客户端系统托盘：常驻、状态回显与退出入口。"""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from shared.qt_icons import make_icon


class ClientTray:
    """客户端托盘图标与菜单。"""

    def __init__(self, parent, on_show, on_check_update, on_quit):
        """初始化托盘。

        Args:
            parent: 父对象。
            on_show: 显示主界面回调。
            on_check_update: 检查更新回调。
            on_quit: 退出回调。
        """
        self.icon = QSystemTrayIcon(make_icon('snake', '#0aa96a', 32), parent)
        self.icon.setToolTip('Play With Snake')
        menu = QMenu(parent)
        a_show = QAction('显示主界面', parent)
        a_show.triggered.connect(on_show)
        menu.addAction(a_show)
        self.a_state = QAction('未连接服务器', parent)
        self.a_state.setEnabled(False)
        menu.addAction(self.a_state)
        menu.addSeparator()
        a_update = QAction('检查更新', parent)
        a_update.triggered.connect(on_check_update)
        menu.addAction(a_update)
        menu.addSeparator()
        a_quit = QAction('退出', parent)
        a_quit.triggered.connect(on_quit)
        menu.addAction(a_quit)
        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.show()

    def set_state(self, text: str, connected: bool) -> None:
        """更新托盘菜单中的连接状态与提示。

        Args:
            text: 状态文本。
            connected: 是否已连接。
        """
        self.a_state.setText(text)
        self.icon.setToolTip('Play With Snake · ' + text)

    def notify(self, title: str, text: str) -> None:
        """弹出一条托盘气泡提示。"""
        try:
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass

    def hide(self) -> None:
        """隐藏托盘图标。"""
        try:
            self.icon.hide()
        except Exception:
            pass
