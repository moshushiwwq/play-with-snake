"""内网自动发现：UDP 41999 广播与应答。

客户端「内网服务器搜索」既可以直接 HTTP 探测，也能依赖这里的广播识别服务端。
"""
from __future__ import annotations

import json
import socket
import threading


MAGIC = 'SNAKE_DISCOVER'
PORT = 41999


class Discovery(threading.Thread):
    """UDP 广播线程。"""

    def __init__(self, payload_provider, logger=None):
        """初始化。

        Args:
            payload_provider: 返回发现信息字典的回调。
            logger: 日志回调 fn(text, level)。
        """
        super().__init__(name='snake-discovery', daemon=True)
        self._provider = payload_provider
        self._logger = logger
        self._stop = threading.Event()
        self.sock: socket.socket | None = None

    def run(self) -> None:
        """线程主循环：应答探测请求并周期性广播。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except Exception:
                pass
            s.bind(('0.0.0.0', PORT))
            s.settimeout(1.0)
            self.sock = s
        except Exception as e:
            if self._logger:
                self._logger('内网发现启动失败：%s' % e, 'warn')
            return

        last_broadcast = 0.0
        import time
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(2048)
                if data and (MAGIC.encode() in data or b'snake' in data.lower()):
                    self._reply(addr)
            except socket.timeout:
                pass
            except Exception:
                continue
            now = time.time()
            if now - last_broadcast > 5:
                last_broadcast = now
                self._broadcast()

    def _payload(self) -> bytes:
        """构造发现信息 JSON 字节。"""
        try:
            info = self._provider() or {}
        except Exception:
            info = {}
        info = dict(info)
        info['magic'] = MAGIC
        return json.dumps(info, ensure_ascii=False).encode('utf-8')

    def _reply(self, addr) -> None:
        """向探测方回包。"""
        try:
            self.sock.sendto(self._payload(), addr)
        except Exception:
            pass

    def _broadcast(self) -> None:
        """周期性广播（局域网客户端可被动发现）。"""
        try:
            self.sock.sendto(self._payload(), ('255.255.255.255', PORT))
        except Exception:
            pass

    def stop(self) -> None:
        """停止线程。"""
        self._stop.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
