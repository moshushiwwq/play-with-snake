"""WebSocket 服务：QWebSocketServer 承载权威对局协议（端口默认 8081）。

注意线程安全：房间广播可能来自 HTTP 线程，而 QWebSocket 只能在 GUI 线程写入，
因此所有发送统一进入线程安全队列，由 GUI 线程的定时器批量冲刷。
"""
from __future__ import annotations

import json
import queue

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QHostAddress
from PyQt6.QtWebSockets import QWebSocketServer

from shared.constants import DIFFS


class Conn:
    """一条客户端连接的轻量封装（供 core 层使用）。"""

    def __init__(self, cid: int, socket, ip: str, outbox: queue.Queue):
        """初始化连接。

        Args:
            cid: 连接 id。
            socket: QWebSocket 对象。
            ip: 来源 IP。
            outbox: 线程安全发送队列。
        """
        self.id = cid
        self.socket = socket
        self.ip = ip
        self.name = ''
        self.room = None
        self.role = None
        self.closed = False
        self.last_solo_submit = 0.0
        self._outbox = outbox

    def send(self, obj: dict) -> None:
        """把一条消息放入发送队列（任意线程可调用）。

        Args:
            obj: 消息字典。
        """
        if self.closed:
            return
        try:
            self._outbox.put((self, json.dumps(obj, ensure_ascii=False)))
        except Exception:
            pass


class WsServer(QObject):
    """QWebSocketServer 封装。"""

    logged = pyqtSignal(str, str)
    changed = pyqtSignal()

    def __init__(self, service, config, parent=None):
        """初始化。

        Args:
            service: GameService。
            config: 配置对象（提供 ws_port）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self.service = service
        self.config = config
        self.server: QWebSocketServer | None = None
        self.conns: list[Conn] = []
        self._outbox: queue.Queue = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._drain)

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> tuple[bool, str]:
        """启动 WebSocket 服务。

        Returns:
            (是否成功, 提示信息)。
        """
        if self.server is not None:
            return True, 'WebSocket 服务已在运行'
        srv = QWebSocketServer('PlayWithSnake', QWebSocketServer.SslMode.NonSecureMode, self)
        if not srv.listen(QHostAddress('0.0.0.0'), self.config.ws_port):
            return False, 'WebSocket 端口 %d 启动失败：%s' % (self.config.ws_port, srv.errorString())
        self.server = srv
        srv.newConnection.connect(self._on_new)
        self._timer.start()
        return True, 'WebSocket 服务已启动：%d' % self.config.ws_port

    def stop(self) -> None:
        """停止 WebSocket 服务并断开所有连接。"""
        self._timer.stop()
        for c in list(self.conns):
            try:
                c.closed = True
                c.socket.close()
            except Exception:
                pass
        self.conns.clear()
        if self.server is not None:
            try:
                self.server.close()
            except Exception:
                pass
            self.server = None

    # ---------------------------------------------------------------- 事件
    def _on_new(self) -> None:
        """接受一条新连接：登记、下发 hello、广播大厅。"""
        srv = self.server
        if srv is None:
            return
        ws = srv.nextPendingConnection()
        if ws is None:
            return
        try:
            ip = ws.peerAddress().toString()
        except Exception:
            ip = ''
        if ip.startswith('::ffff:'):
            ip = ip[7:]
        conn = Conn(self.service.next_conn_id(), ws, ip, self._outbox)
        self.conns.append(conn)
        self.service.add_conn(conn)
        ws.textMessageReceived.connect(lambda text, c=conn: self._on_text(c, text))
        ws.disconnected.connect(lambda c=conn: self._on_close(c))
        conn.send({
            't': 'hello', 'name': '贪吃蛇大冒险',
            'maps': self.service.map_list(),
            'diffs': [{'id': k, 'name': v['name']} for k, v in DIFFS.items()],
            'lb': self.service.leaderboard.top(30),
            'wsPort': self.config.ws_port,
            'httpPort': self.config.port,
        })
        self.service.broadcast_lobby()
        self.logged.emit('连接建立 #%d 来自 %s' % (conn.id, ip), 'info')
        self.changed.emit()

    def _on_text(self, conn: Conn, text: str) -> None:
        """收到一条文本消息。"""
        try:
            self.service.handle(conn, text)
        except Exception as e:
            self.logged.emit('消息处理异常：#%d %s' % (conn.id, e), 'error')
        self.changed.emit()

    def _on_close(self, conn: Conn) -> None:
        """连接断开。"""
        conn.closed = True
        try:
            self.service.remove_conn(conn)
        except Exception:
            pass
        self.conns = [c for c in self.conns if c is not conn]
        self.logged.emit('连接断开 #%d（%s）' % (conn.id, conn.name or '-'), 'warn')
        self.changed.emit()

    # ---------------------------------------------------------------- 发送
    def _drain(self) -> None:
        """把队列中的消息真正写回各连接（仅在 GUI 线程执行）。"""
        for _ in range(400):
            try:
                conn, text = self._outbox.get_nowait()
            except queue.Empty:
                return
            if conn.closed:
                continue
            try:
                conn.socket.sendTextMessage(text)
            except Exception:
                pass
