"""客户端联机连接：由 Python 持有的 QWebSocket（经 QWebChannel 与页面交互）。"""
from __future__ import annotations

import json

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtWebSockets import QWebSocket


class NetClient(QObject):
    """WebSocket 连接封装。

    页面不直接联网，所有收发都经由这里；断线后可自动重连。
    """

    stateChanged = pyqtSignal(str, str)   # connected / connecting / disconnected / error, host
    messageReceived = pyqtSignal(str)
    autoReconnectChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        """初始化连接对象。"""
        super().__init__(parent)
        self.sock = QWebSocket()
        self.sock.setParent(self)
        self.sock.connected.connect(self._on_open)
        self.sock.disconnected.connect(self._on_close)
        self.sock.textMessageReceived.connect(self._on_text)
        self.sock.errorOccurred.connect(lambda e: self._on_error(e))
        self.host_url = ''
        self.host_text = ''
        self.auto_reconnect = True
        self._retry = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reconnect)
        self._manual_close = False

    # ---------------------------------------------------------------- 连接
    def connect_to(self, host: str) -> dict:
        """连接服务器。

        Args:
            host: "IP:端口" 或 "IP"。

        Returns:
            {'ok': bool, 'msg': str}。
        """
        text = str(host or '').strip()
        if not text:
            return {'ok': False, 'msg': '请填写服务器地址'}
        text = text.replace('ws://', '').replace('wss://', '').replace('http://', '').replace('https://', '')
        text = text.rstrip('/')
        if ':' not in text:
            text += ':8081'
        self.host_text = text
        self.host_url = 'ws://' + text
        self._manual_close = False
        self._retry = 0
        self.stateChanged.emit('connecting', self.host_text)
        self.sock.abort()
        self.sock.open(QUrl(self.host_url))
        return {'ok': True, 'msg': '正在连接 ' + text}

    def disconnect(self) -> None:
        """主动断开（不触发自动重连）。"""
        self._manual_close = True
        self._retry = 0
        try:
            self.sock.close()
        except Exception:
            pass

    def send(self, obj_or_text) -> None:
        """发送 JSON 消息。

        Args:
            obj_or_text: 字典或已序列化的 JSON 文本。
        """
        try:
            text = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text, ensure_ascii=False)
            self.sock.sendTextMessage(text)
        except Exception:
            pass

    # ---------------------------------------------------------------- 事件
    def _on_open(self) -> None:
        """连接建立。"""
        self._retry = 0
        self.stateChanged.emit('connected', self.host_text)

    def _on_close(self) -> None:
        """连接断开（按需自动重连）。"""
        self.stateChanged.emit('disconnected', self.host_text)
        if self._manual_close or not self.auto_reconnect or not self.host_url:
            return
        if self._retry >= 5:
            return
        self._retry += 1
        self._timer.start(3000)

    def _reconnect(self) -> None:
        """延时重连。"""
        if self._manual_close or not self.host_url:
            return
        self.stateChanged.emit('connecting', self.host_text)
        self.sock.abort()
        self.sock.open(QUrl(self.host_url))

    def _on_text(self, text: str) -> None:
        """收到文本消息。"""
        self.messageReceived.emit(text)

    def _on_error(self, err) -> None:
        """连接错误。"""
        self.stateChanged.emit('error', self.host_text)

    def close(self) -> None:
        """释放资源。"""
        self._manual_close = True
        self._timer.stop()
        try:
            self.sock.close()
            self.sock.deleteLater()
        except Exception:
            pass
