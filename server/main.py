"""服务端入口：装配配置、存储、网络服务、Qt 界面与托盘。

运行方式：
    python server/main.py                 # 正常启动（自动开启 HTTP/WS/内网发现）
    python server/main.py --tray          # 启动后隐藏到系统托盘
    python server/main.py --port 8080 --ws-port 8081
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

# 必须在创建 QApplication 之前设置（QWebEngineView 需要共享 OpenGL 上下文），
# 同时要早于任何 QtWebEngine 模块的导入。
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

# 与客户端一致：部分环境会阻止 Chromium 渲染进程启用沙箱，导致「访问密码与排行榜」
# 面板空白。服务器只渲染本地面板页面，因此默认关闭渲染沙箱，可用同名环境变量覆盖。
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--no-sandbox')

# 让 `python server/main.py` 也能导入 shared/ 与 server/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.version import APP_VERSION
from server.config import Config
from server.core.service import GameService
from server.gui.theme import QSS
from server.gui.tray import Tray
from server.gui.window import ServerWindow
from server.net.http_api import HttpApi
from server.net.ws_server import WsServer
from server.paths import data_dir
from server.store.auth import PanelAuth
from server.store.custom_maps import CustomMaps
from server.store.ip_notes import IpNotes
from server.store.leaderboard import Leaderboard
from server.store.online_board import OnlineBoard
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
    p.add_argument('--tray', action='store_true', help='启动后隐藏到系统托盘')
    p.add_argument('--no-tray', action='store_true', help='禁用系统托盘')
    p.add_argument('--shot', default='', help='启动后截图到指定路径并退出（自检用）')
    return p.parse_args(argv)


class ServerApp(QObject):
    """应用上下文：持有全部服务对象与定时器。"""

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
        self.auth = PanelAuth(self.config.data.get('panelAuth'), self._persist_auth)
        self.service = GameService(
            self.leaderboard, self.online_board, self.ip_notes, self.custom_maps,
            snapshot_hz=self.config.snapshot_hz, logger=self.logbus.push)
        self.http = HttpApi(self.service, self.config, self.auth, APP_VERSION, self.logbus.push)
        self.ws = WsServer(self.service, self.config)
        self.ws.logged.connect(self.logbus.push)
        self.discovery: Discovery | None = None
        self.started_at = 0.0
        self.tray: Tray | None = None
        self.window: ServerWindow | None = None
        self.admin = autostart.is_admin()

        self._tick_timer = QTimer(self)
        self._tick_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick_timer.setInterval(10)
        self._tick_timer.timeout.connect(self._on_tick)
        self._last_tick = time.time()

    def _persist_auth(self, params) -> None:
        """把新的密码参数写入配置。"""
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

    # ---------------------------------------------------------------- 界面
    def build_ui(self) -> None:
        """创建主窗口与托盘。"""
        self.window = ServerWindow(self)
        from PyQt6.QtWidgets import QSystemTrayIcon
        self.tray_available = (not self.args.no_tray) and QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available:
            self.tray = Tray(self.window, self.show_window, self._tray_start,
                             self._tray_stop, self._tray_panel, self.window.quit_app)
            self.tray.set_running(self.http_running and self.ws_running)
        if self.args.tray or self.config.data.get('trayStart', False):
            self.window.hide()
        else:
            self.window.show()

    def show_window(self) -> None:
        """显示并激活主窗口。"""
        if self.window:
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()

    def _tray_start(self) -> None:
        """托盘菜单：启动服务。"""
        ok, msg = self.start_services()
        self.logbus.push(msg, 'ok' if ok else 'error')
        if self.window:
            self.window.refresh_all()

    def _tray_stop(self) -> None:
        """托盘菜单：停止服务。"""
        self.stop_services()
        self.logbus.push('服务器已停止', 'warn')
        if self.window:
            self.window.refresh_all()

    def _tray_panel(self) -> None:
        """托盘菜单：打开面板。"""
        if self.window:
            if not self.http_running:
                QMessageBox.information(self.window, '提示', '请先启动服务器，再打开面板。')
                return
            self.window._open_panel()


def main() -> int:
    """程序入口。

    Returns:
        进程退出码。
    """
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Play With Snake Server')
    app.setStyleSheet(QSS)

    # 单实例：已有实例时只把它唤到前台
    # 需要握手确认，否则进程异常退出留下的同名管道会让新实例「静默不启动」
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
    ctx.logbus.push('Play With Snake 服务器控制台 v%s 启动中…' % APP_VERSION)
    ctx.logbus.push('数据目录：%s' % ctx.data_dir)
    ctx.logbus.push('权限：%s' % ('管理员' if ctx.admin else '普通用户（防火墙/开机自启需要管理员）'),
                    'ok' if ctx.admin else 'warn')

    def on_new_conn():
        """再次启动时回写握手结果并把主窗口唤到前台。"""
        conn = holder.nextPendingConnection()
        if conn:
            conn.waitForReadyRead(200)
            conn.write(b'OK')
            conn.flush()
            conn.waitForBytesWritten(200)
            if ctx.window:
                ctx.show_window()
    holder.newConnection.connect(on_new_conn)

    ctx.build_ui()
    ctx.start_services()

    if args.shot:
        def take_shot():
            try:
                ctx.show_window()
                QTimer.singleShot(900, lambda: (
                    ctx.window.grab().save(args.shot),
                    ctx.logbus.push('已保存界面截图：' + args.shot, 'ok'),
                    ctx.window.quit_app(),
                ))
            except Exception as e:
                ctx.logbus.push('截图失败：%s' % e, 'error')
        QTimer.singleShot(600, take_shot)

    code = app.exec()
    ctx.stop_services()
    try:
        holder.close()
    except Exception:
        pass
    return code


if __name__ == '__main__':
    sys.exit(main())
