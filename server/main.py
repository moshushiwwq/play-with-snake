"""服务端入口：后台驻留的 HTTP / WebSocket / 内网发现服务 + 系统托盘。

运行方式：
    python server/main.py                 # 启动后直接后台运行（托盘常驻，不弹窗口）
    python server/main.py --tray         # 同默认（后台驻留）
    python server/main.py --no-tray      # 不显示托盘图标
    python server/main.py --port 8080 --ws-port 8081

管理面板通过客户端「管理员选项」或托盘菜单在外部浏览器中打开
（http://127.0.0.1:<http端口>/panel），程序本身不再内嵌网页控件。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from PyQt6.QtCore import Qt, QObject, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.version import APP_VERSION
from server.config import Config
from server.core.service import GameService
from server.gui.log_window import LogWindow
from server.gui.tray import Tray, local_ipv4
from server.net.http_api import HttpApi
from server.net.ws_server import WsServer
from server.paths import data_dir
from server.store.auth import PanelAuth
from server.store.custom_maps import CustomMaps
from server.store.ip_notes import IpNotes
from server.store.leaderboard import Leaderboard
from server.store.online_board import OnlineBoard
from server.store.replays import ReplayStore
from server.sys import autostart
from server.sys.discovery import Discovery
from server.sys.logs import LogBus


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行。

    Returns:
        argparse 命名空间。
    """
    p = argparse.ArgumentParser(description='Play With Snake 服务器')
    p.add_argument('--port', type=int, default=None, help='HTTP 端口（默认 8080）')
    p.add_argument('--ws-port', type=int, default=None, help='WebSocket 端口（默认 8081）')
    p.add_argument('--tray', action='store_true', help='启动后隐藏到系统托盘（默认即后台）')
    p.add_argument('--no-tray', action='store_true', help='禁用系统托盘')
    return p.parse_args(argv)


class ServerApp(QObject):
    """应用上下文：持有全部服务对象、定时器与托盘。"""

    def __init__(self, args: argparse.Namespace):
        """装配所有组件。

        Args:
            args: 命令行参数。
        """
        super().__init__()
        self.args = args
        self.data_dir = data_dir()
        self.config = Config()
        if args.port:
            self.config.data['port'] = args.port
        if args.ws_port:
            self.config.data['wsPort'] = args.ws_port
        self.config.save()

        self.logbus = LogBus(self.data_dir)
        self.ip_notes = IpNotes(self.data_dir)
        self.leaderboard = Leaderboard(self.data_dir)
        self.custom_maps = CustomMaps(self.data_dir)
        self.online_board = OnlineBoard(self.data_dir, self.ip_notes)
        self.replays = ReplayStore(self.data_dir)
        self.auth = PanelAuth(self.config.data.get('panelAuth'), self._persist_auth)
        self.service = GameService(
            self.leaderboard, self.online_board, self.ip_notes, self.custom_maps,
            snapshot_hz=self.config.snapshot_hz, logger=self.logbus.push,
            replays=self.replays)
        self.http = HttpApi(self.service, self.config, self.auth, APP_VERSION,
                            self.logbus.push, logbus=self.logbus)
        self.ws = WsServer(self.service, self.config)
        self.ws.logged.connect(self.logbus.push)
        self.discovery: Discovery | None = None
        self.started_at = 0.0
        self.launched_at = time.time()
        self.tray: Tray | None = None
        self.log_window: LogWindow | None = None
        self.admin = autostart.is_admin()

        self._tick_timer = QTimer(self)
        self._tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick_timer.setInterval(10)
        self._tick_timer.timeout.connect(self._on_tick)
        self._last_tick = time.time()

    def _persist_auth(self, params) -> None:
        """把新的账号参数写入配置。"""
        self.config.data['panelAuth'] = params
        self.config.save()

    # ---------------------------------------------------------------- 服务
    @property
    def http_running(self) -> bool:
        """HTTP 服务是否在运行。"""
        return self.http._httpd is not None

    @property
    def ws_running(self) -> bool:
        """WebSocket 服务是否在运行。"""
        return self.ws.server is not None

    def _open_firewall(self) -> None:
        """启动后尝试放行局域网所需端口（TCP HTTP/WS + UDP 发现）。

        非管理员或非 Windows 时仅记录提示，不中断服务。这是修复
        「UDP 广播能搜到服务器、但 TCP/WebSocket 连不上」的关键一步。
        """
        try:
            ok, msg = autostart.firewall(True, (self.config.port, self.config.ws_port))
            self.logbus.push(msg, 'ok' if ok else 'warn')
        except Exception as e:
            self.logbus.push('防火墙放行跳过：%s' % e, 'warn')

    def start_services(self) -> tuple[bool, str]:
        """启动 HTTP、WebSocket 与内网发现。

        Returns:
            (是否成功, 提示信息)。
        """
        if self.http_running and self.ws_running:
            return True, '服务已在运行'
        if not self.http_running:
            ok, msg = self.http.start()
            if not ok:
                return False, msg
            self.logbus.push(msg, 'ok')
        if not self.ws_running:
            ok, msg = self.ws.start()
            if not ok:
                self.http.stop()
                return False, msg
            self.logbus.push(msg, 'ok')
        self.service.snapshot_hz = self.config.snapshot_hz
        self.started_at = time.time()
        self._last_tick = time.time()
        if self.config.data.get('discovery', True) and self.discovery is None:
            self.discovery = Discovery(self._discover_payload, self.logbus.push)
            self.discovery.start()
            self.logbus.push('内网自动发现已开启（UDP 41999）', 'ok')
        self.logbus.push('服务器已启动：HTTP %d / WS %d' % (self.config.port, self.config.ws_port), 'ok')
        self._open_firewall()
        self._tick_timer.start()
        if self.tray:
            self.tray.set_running(True)
        return True, '服务器已启动'

    def stop_services(self) -> None:
        """停止所有网络服务与定时器。"""
        self._tick_timer.stop()
        if self.discovery is not None:
            self.discovery.stop()
            self.discovery = None
        self.ws.stop()
        self.http.stop()
        self.started_at = 0.0
        if self.tray:
            self.tray.set_running(False)

    def uptime_ms(self) -> int:
        """服务已运行的毫秒数。"""
        return int((time.time() - self.started_at) * 1000) if self.started_at else 0

    def total_uptime_ms(self) -> int:
        """程序自启动以来的总运行毫秒数（停止服务后仍继续累计）。"""
        return int((time.time() - self.launched_at) * 1000)

    def tray_info(self) -> dict:
        """托盘菜单展示所需的运行状态。

        Returns:
            含运行状态、总运行时长、局域网地址与端口。
        """
        return {
            'running': self.http_running and self.ws_running,
            'uptime_ms': self.total_uptime_ms(),
            'addresses': local_ipv4(),
            'http_port': self.config.port,
            'ws_port': self.config.ws_port,
        }

    def _discover_payload(self) -> dict:
        """内网发现响应内容。"""
        return self.service.discover_info(APP_VERSION, self.config.port, self.config.ws_port)

    def _on_tick(self) -> None:
        """10ms 游戏 tick。"""
        now = time.time()
        dt = min(500.0, (now - self._last_tick) * 1000.0)
        self._last_tick = now
        try:
            self.service.tick(dt)
        except Exception as e:
            self.logbus.push('tick 异常：%s' % e, 'error')

    # ---------------------------------------------------------------- 界面（仅托盘）
    def build_ui(self) -> None:
        """创建托盘图标；不创建任何主窗口。"""
        from PyQt6.QtWidgets import QSystemTrayIcon
        self.tray_available = (not self.args.no_tray) and QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available:
            self.tray = Tray(None, self.open_panel, self._tray_start,
                             self._tray_stop, self.quit_app,
                             info_provider=self.tray_info, on_logs=self.open_logs)
            self.tray.set_running(self.http_running and self.ws_running)
        if self.config.data.get('splashServer', True):
            self.logbus.push('服务器已在后台运行，右键托盘图标可打开管理面板', 'ok')

    def open_logs(self) -> None:
        """在独立窗口中查看运行日志。"""
        if self.log_window is None:
            self.log_window = LogWindow(self.logbus, self.data_dir)
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()

    def open_panel(self) -> None:
        """在外部默认浏览器中打开管理面板网页。"""
        if not self.http_running:
            self.logbus.push('请先启动服务器，再打开管理面板', 'warn')
            if self.tray:
                self.tray.notify('提示', '服务器尚未启动')
            return
        url = QUrl('http://127.0.0.1:%d/panel' % self.config.port)
        QDesktopServices.openUrl(url)

    def _tray_start(self) -> None:
        """托盘菜单：启动服务。"""
        ok, msg = self.start_services()
        self.logbus.push(msg, 'ok' if ok else 'error')

    def _tray_stop(self) -> None:
        """托盘菜单：停止服务。"""
        self.stop_services()
        self.logbus.push('服务器已停止', 'warn')

    def quit_app(self) -> None:
        """退出服务端。"""
        self.stop_services()
        if self.log_window is not None:
            self.log_window.close()
            self.log_window = None
        if self.tray:
            self.tray.hide()
        QApplication.quit()


def main() -> int:
    """程序入口。

    Returns:
        进程退出码。
    """
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Play With Snake Server')
    app.setQuitOnLastWindowClosed(False)   # 无主窗口，关闭最后窗口不应退出

    # 单实例：已有实例时打开它的面板后直接退出
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    key = 'play-with-snake-server'
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(400):
        probe.write(b'SHOW')
        probe.flush()
        if probe.waitForBytesWritten(400) and probe.waitForReadyRead(600):
            if b'OK' in bytes(probe.readAll()):
                probe.disconnectFromServer()
                return 0
        probe.abort()
    QLocalServer.removeServer(key)
    holder = QLocalServer()
    holder.listen(key)

    ctx = ServerApp(args)
    ctx.logbus.push('Play With Snake 服务器 v%s 启动中…' % APP_VERSION)
    ctx.logbus.push('数据目录：%s' % ctx.data_dir)
    ctx.logbus.push('权限：%s' % ('管理员' if ctx.admin else '普通用户（防火墙/开机自启需要管理员）'),
                    'ok' if ctx.admin else 'warn')

    def on_new_conn():
        """再次启动时回写握手结果并打开面板。"""
        conn = holder.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(200)
            conn.write(b'OK')
            conn.flush()
            conn.waitForBytesWritten(200)
            ctx.open_panel()
    holder.newConnection.connect(on_new_conn)

    ctx.build_ui()
    ctx.start_services()

    code = app.exec()
    ctx.stop_services()
    try:
        holder.close()
    except Exception:
        pass
    return code


if __name__ == '__main__':
    sys.exit(main())
