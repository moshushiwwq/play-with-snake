"""系统托盘：后台常驻、运行状态/IP/端口/总运行时长与日志入口。"""
from __future__ import annotations

import socket

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from server.gui import icons


def local_ipv4() -> list[str]:
    """获取本机可用于局域网访问的 IPv4 地址。

    Returns:
        地址列表；没有局域网地址时回退到 127.0.0.1。
    """
    ips: list[str] = []
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith('127.') and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(('8.8.8.8', 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith('127.'):
                ips.append(ip)
            probe.close()
        except Exception:
            pass
    if not ips:
        ips.append('127.0.0.1')
    return ips


def fmt_uptime(ms: int) -> str:
    """把毫秒格式化为「天 时:分:秒」。

    Args:
        ms: 毫秒数。

    Returns:
        可读的运行时长。
    """
    seconds = max(0, int(ms // 1000))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return '%d 天 %02d:%02d:%02d' % (days, hours, minutes, seconds)
    return '%02d:%02d:%02d' % (hours, minutes, seconds)


class Tray:
    """服务端托盘图标与右键菜单。"""

    def __init__(self, parent, on_panel, on_start, on_stop, on_quit,
                 info_provider=None, on_logs=None):
        """初始化托盘与菜单。

        Args:
            parent: 父对象。
            on_panel: 打开管理面板回调。
            on_start: 启动服务回调。
            on_stop: 停止服务回调。
            on_quit: 退出程序回调。
            info_provider: 返回运行状态字典的回调（running/uptime_ms/addresses/端口）。
            on_logs: 打开运行日志窗口回调。
        """
        self.info_provider = info_provider
        self._copy_text = ''
        self.icon = QSystemTrayIcon(icons.make_icon('snake', '#0aa96a', 32), parent)
        self.icon.setToolTip('Play With Snake 服务器')
        menu = QMenu(parent)

        # 状态区（只读）
        self.a_title = QAction('Play With Snake 服务器', parent)
        self.a_title.setEnabled(False)
        font = self.a_title.font()
        font.setBold(True)
        self.a_title.setFont(font)
        menu.addAction(self.a_title)

        self.a_status = QAction('○ 服务已停止', parent)
        self.a_status.setEnabled(False)
        menu.addAction(self.a_status)

        self.a_uptime = QAction('运行时长 --', parent)
        self.a_uptime.setEnabled(False)
        menu.addAction(self.a_uptime)

        self.a_addr = QAction('地址：未启动', parent)
        self.a_addr.setEnabled(False)
        menu.addAction(self.a_addr)

        self.a_copy = QAction('复制服务器地址', parent)
        self.a_copy.triggered.connect(self._copy_address)
        menu.addAction(self.a_copy)
        menu.addSeparator()

        # 功能入口
        a_panel = QAction('打开管理面板', parent)
        a_panel.triggered.connect(on_panel)
        menu.addAction(a_panel)

        self.a_logs = QAction('查看运行日志', parent)
        self.a_logs.triggered.connect(on_logs or (lambda: None))
        self.a_logs.setEnabled(on_logs is not None)
        menu.addAction(self.a_logs)
        menu.addSeparator()

        a_start = QAction('启动服务器', parent)
        a_start.triggered.connect(on_start)
        menu.addAction(a_start)
        a_stop = QAction('停止服务器', parent)
        a_stop.triggered.connect(on_stop)
        menu.addAction(a_stop)
        menu.addSeparator()

        a_quit = QAction('退出', parent)
        a_quit.triggered.connect(on_quit)
        menu.addAction(a_quit)

        self.menu = menu
        self.menu.aboutToShow.connect(self.refresh_info)
        self.icon.setContextMenu(menu)
        self.icon.show()
        self.actions = {'start': a_start, 'stop': a_stop}

        # 每秒刷新运行时长与地址（菜单打开时立即可见）
        self._timer = QTimer()
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh_info)
        self._timer.start()
        self.refresh_info()

    def refresh_info(self) -> None:
        """刷新状态、运行时长、地址与托盘提示。"""
        info = {}
        if self.info_provider is not None:
            try:
                info = self.info_provider() or {}
            except Exception:
                info = {}
        running = bool(info.get('running'))
        uptime = fmt_uptime(int(info.get('uptime_ms') or 0))
        addresses = info.get('addresses') or ['127.0.0.1']
        http_port = int(info.get('http_port') or 8080)
        ws_port = int(info.get('ws_port') or 8081)
        primary = addresses[0] if addresses else '127.0.0.1'

        self.a_status.setText('● 服务运行中' if running else '○ 服务已停止')
        self.a_uptime.setText('运行时长 %s' % uptime)
        if running:
            self.a_addr.setText('地址：%s:%d（WS %d）' % (primary, http_port, ws_port))
            self._copy_text = 'http://%s:%d/' % (primary, http_port)
        else:
            self.a_addr.setText('地址：服务未启动')
            self._copy_text = ''
        self.a_copy.setEnabled(running)
        self.a_addr.setToolTip('\n'.join('%s:%d' % (ip, http_port) for ip in addresses))
        self.icon.setToolTip(
            'Play With Snake 服务器\n%s · %s:%d · 运行 %s'
            % ('运行中' if running else '已停止', primary, http_port, uptime)
        )

    def _copy_address(self) -> None:
        """把当前服务器访问地址复制到剪贴板。"""
        if not self._copy_text:
            return
        try:
            QApplication.clipboard().setText(self._copy_text)
            self.notify('已复制', self._copy_text)
        except Exception:
            pass

    def set_running(self, running: bool) -> None:
        """按运行状态启用/禁用菜单项。

        Args:
            running: 是否运行中。
        """
        self.actions['start'].setEnabled(not running)
        self.actions['stop'].setEnabled(running)
        self.refresh_info()

    def notify(self, title: str, text: str) -> None:
        """弹一条托盘气泡提示。"""
        try:
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass

    def hide(self) -> None:
        """隐藏托盘图标（退出前调用）。"""
        try:
            self._timer.stop()
            self.icon.hide()
        except Exception:
            pass
