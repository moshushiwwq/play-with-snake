"""系统托盘：常驻运行、右键菜单与退出入口。"""
from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from server.gui import icons


class Tray:
    """服务端托盘图标。"""

    def __init__(self, parent, on_show, on_start, on_stop, on_panel, on_quit):
        """初始化托盘与菜单。

        Args:
            parent: 父对象（通常是主窗口）。
            on_show: 显示主窗口回调。
            on_start: 启动服务回调。
            on_stop: 停止服务回调。
            on_panel: 打开面板回调。
            on_quit: 退出程序回调。
        """
        self.icon = QSystemTrayIcon(icons.make_icon('snake', '#0aa96a', 32), parent)
        self.icon.setToolTip('Play With Snake 服务器')
        menu = QMenu(parent)

        a_show = QAction('显示主窗口', parent)
        a_show.triggered.connect(on_show)
        menu.addAction(a_show)
        menu.addSeparator()

        a_start = QAction('启动服务器', parent)
        a_start.triggered.connect(on_start)
        menu.addAction(a_start)
        a_stop = QAction('停止服务器', parent)
        a_stop.triggered.connect(on_stop)
        menu.addAction(a_stop)
        menu.addSeparator()

        a_panel = QAction('访问密码与排行榜', parent)
        a_panel.triggered.connect(on_panel)
        menu.addAction(a_panel)
        menu.addSeparator()

        a_quit = QAction('退出', parent)
        a_quit.triggered.connect(on_quit)
        menu.addAction(a_quit)

        self.menu = menu
        self.icon.setContextMenu(menu)
        self.icon.show()
        self.actions = {'start': a_start, 'stop': a_stop}

    def set_running(self, running: bool) -> None:
        """按运行状态启用/禁用菜单项。

        Args:
            running: 是否运行中。
        """
        self.actions['start'].setEnabled(not running)
        self.actions['stop'].setEnabled(running)

    def notify(self, title: str, text: str) -> None:
        """弹一条托盘气泡提示。"""
        try:
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass

    def hide(self) -> None:
        """隐藏托盘图标（退出前调用）。"""
        self.icon.hide()
