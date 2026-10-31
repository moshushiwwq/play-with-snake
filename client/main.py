"""客户端入口：本机页面服务 + QWebEngineView + Python 持网 + 托盘 + 本地存储。

运行方式：
    python client/main.py                 # 正常打开窗口
    python client/main.py --tray          # 启动即隐藏到托盘
    python client/main.py --shot out.png  # 截图后退出（自检用）
"""
from __future__ import annotations

import argparse
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

# QWebEngine 必须在创建 QApplication 之前设置共享 OpenGL 上下文
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

# 部分环境（安全软件 / 组策略 / 以管理员身份运行）会阻止 Chromium 渲染进程启用沙箱，
# 表现为页面空白、渲染进程异常退出。客户端只渲染内置的本地页面，
# 因此默认关闭渲染沙箱以保证启动稳定；如需开启可用同名环境变量覆盖。
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--no-sandbox')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from client.bridge import SnakeBridge
from client.config import ClientConfig
from client.net_client import NetClient
from client.page_server import PageServer
from client.storage import ClientStorage
from client.tray import ClientTray
from client.window import ClientWindow
from shared.qt_theme import QSS
from shared.version import APP_VERSION


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数。

    Returns:
        argparse 命名空间。
    """
    p = argparse.ArgumentParser(description='Play With Snake 客户端')
    p.add_argument('--tray', action='store_true', help='启动后隐藏到系统托盘')
    p.add_argument('--shot', default='', help='加载完成后截图到指定路径并退出')
    p.add_argument('--url', default='', help='直接加载指定地址（调试用）')
    p.add_argument('--autotest', default='', help='加载后执行内置联机自检（参数为服务器地址）')
    return p.parse_args(argv)


class ClientApp:
    """客户端上下文。"""

    def __init__(self, args: argparse.Namespace):
        """装配所有组件。

        Args:
            args: 命令行参数。
        """
        self.args = args
        self.config = ClientConfig()
        self.storage = ClientStorage()
        self.page_server = PageServer()
        self.page_url = args.url or self.page_server.start()
        if args.autotest:
            # 自检需要页面暴露内部接口（正常运行时不会加这个参数）
            self.page_url = self.page_url + ('&' if '?' in self.page_url else '?') + 'selftest=1'
        self.net = NetClient()
        self.net.auto_reconnect = bool(self.config.auto_reconnect)
        self.bridge = SnakeBridge(self.net, self.storage, self.config)
        self.window: ClientWindow | None = None
        self.tray: ClientTray | None = None

    def build_ui(self) -> None:
        """创建窗口与托盘。"""
        self.window = ClientWindow(self)
        from PyQt6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = ClientTray(self.window, self.window.show_and_raise,
                                   self.window.on_check_update, self.window.quit_app)
            self.net.stateChanged.connect(self._on_net_state)
        if self.args.tray or self.config.start_hidden:
            self.window.hide()
        else:
            self.window.show()

    def _on_net_state(self, state: str, host: str) -> None:
        """把连接状态同步到托盘。"""
        if self.tray is None:
            return
        if state == 'connected':
            self.tray.set_state('已连接 ' + host, True)
        elif state == 'connecting':
            self.tray.set_state('正在连接 ' + host, False)
        else:
            self.tray.set_state('未连接服务器', False)


CLIENT_SINGLE_KEY = 'play-with-snake-client'


def _activate_existing() -> bool:
    """若已有客户端实例在运行，则通知它把窗口唤到前台。

    Returns:
        是否成功唤起已有实例（True 表示当前进程应当直接退出）。
    """
    probe = QLocalSocket()
    probe.connectToServer(CLIENT_SINGLE_KEY)
    if not probe.waitForConnected(400):
        return False
    probe.write(b'SHOW')
    probe.flush()
    probe.waitForBytesWritten(400)
    probe.disconnectFromServer()
    return True


def main() -> int:
    """程序入口。

    Returns:
        进程退出码。
    """
    args = parse_args(sys.argv[1:])
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Play With Snake')
    app.setStyleSheet(QSS)

    # 多实例会并发共享同一个 QWebEngine 配置/缓存目录，进而导致渲染进程异常、页面空白，
    # 因此交互模式只允许一个实例存在：第二次启动时唤起已有窗口后直接退出。
    holder: QLocalServer | None = None
    if not (args.shot or args.autotest):
        if _activate_existing():
            return 0
        QLocalServer.removeServer(CLIENT_SINGLE_KEY)
        holder = QLocalServer()
        holder.listen(CLIENT_SINGLE_KEY)

    ctx = ClientApp(args)
    ctx.build_ui()
    if holder is not None:
        def _on_new_connection():
            """再次启动时把当前窗口唤到前台。"""
            while holder.hasPendingConnections():
                conn = holder.nextPendingConnection()
                if conn is not None:
                    conn.readAll()
                    conn.disconnectFromServer()
                    conn.deleteLater()
            ctx.window.show_and_raise()
        holder.newConnection.connect(_on_new_connection)
    if args.shot or args.autotest:
        print('page_url=%r view_url=%r' % (ctx.page_url, ctx.window.view.url().toString()))

    if args.shot:
        def shot():
            """显示窗口并在页面加载完成后截图退出（最多等待 8 秒）。"""
            try:
                ctx.window.show_and_raise()
                state = {'done': False}

                def save():
                    """保存截图并退出。"""
                    if state['done']:
                        return
                    state['done'] = True
                    ok = ctx.window.view.grab().save(args.shot)
                    print('shotsaved=%s ok=%s url=%s' % (args.shot, ok, ctx.window.view.url().toString()))
                    ctx.window.quit_app()

                def on_loaded(ok: bool):
                    """页面加载完成后再留一点渲染时间。"""
                    print('loadFinished ok=%s url=%s' % (ok, ctx.window.view.url().toString()))
                    QTimer.singleShot(900, save)

                ctx.window.view.loadFinished.connect(on_loaded)
                QTimer.singleShot(8000, save)
            except Exception as e:
                print('shot failed=' + str(e))
                ctx.window.quit_app()
        QTimer.singleShot(400, shot)

    if args.autotest:
        _run_autotest(ctx, args.autotest)

    app.aboutToQuit.connect(lambda: (
        ctx.page_server.stop(),
        ctx.net.close(),
        ctx.storage.close(),
    ))
    return app.exec()


def _run_autotest(ctx: 'ClientApp', server_host: str) -> None:
    """执行一次内置联机自检（加载页面 → 通过桥接连接服务器 → 打印结果后退出）。

    Args:
        ctx: 客户端上下文。
        server_host: 服务器地址（如 127.0.0.1:18081）。
    """
    import json

    script = """
window.__AUTOTEST = { results: [], done: false };
(async function(){
  function log(k, v){ window.__AUTOTEST.results.push([k, v]); }
  try {
    var B = (window.__T && window.__T.Backend) || window.Backend;
    if (!B){ log('error', 'Backend 未暴露'); window.__AUTOTEST.done = true; return; }
    await B.init();
    log('mode', B.mode);
    B.onState = function(st, host){ log('state', st + ' ' + host); };
    B.onMessage = function(t){
      try {
        var m = JSON.parse(t);
        log('msg', m.t);
        if (m.t === 'hello' && m.httpPort) B.setHttpPort(m.httpPort);
      } catch(e){ log('msg', 'parse-fail'); }
    };
    B.connect('%(host)s', function(r){ log('connectret', r && r.ok); });
    setTimeout(function(){
      B.httpGet('/api/online-board', '%(host)s', function(j){
        log('board', j && j.ok ? (j.rows || []).length : 'fail');
      });
      B.httpGet('/api/maps', '%(host)s', function(j){
        log('maps', j && j.ok ? (j.maps || []).length : 'fail');
      });
      setTimeout(function(){
        B.send({ t: 'create', name: '客户端甲', maxPlayers: 2, map: 'classic', diff: 'normal', isPublic: true });
        setTimeout(function(){ window.__AUTOTEST.done = true; }, 1500);
      }, 1200);
    }, 1500);
  } catch (e){ log('error', String(e)); window.__AUTOTEST.done = true; }
})();
""" % {'host': server_host}

    state = {'tries': 0}

    def poll():
        state['tries'] += 1
        ctx.window.view.page().runJavaScript('JSON.stringify(window.__AUTOTEST || {})', 0, report)
        if state['tries'] > 12:
            ctx.window.quit_app()

    def report(result):
        try:
            data = json.loads(result) if result else {}
        except Exception:
            data = {}
        if data.get('results'):
            print('AUTOTEST ' + json.dumps(data, ensure_ascii=False))
            if data.get('done'):
                ctx.window.quit_app()
                return
        if state['tries'] > 12:
            print('AUTOTEST EMPTY raw=' + repr(result))
            ctx.window.quit_app()

    def run():
        ctx.window.show_and_raise()
        ctx.window.view.page().runJavaScript(script)

    QTimer.singleShot(2200, run)
    poll_timer = QTimer(ctx.window)
    poll_timer.setInterval(900)
    poll_timer.timeout.connect(poll)
    poll_timer.start()
    ctx._poll_timer = poll_timer      # 保持引用


if __name__ == '__main__':
    sys.exit(main())