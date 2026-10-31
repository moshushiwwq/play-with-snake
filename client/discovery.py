"""客户端服务器发现：UDP 41999 广播探测 + HTTP /api/discover 端口解析。

服务端启动后会监听 UDP 41999 并对探测包回包（见 server/sys/discovery.py），
同时提供 HTTP 接口 `/api/discover` 与 `/health`。客户端通过两者组合完成：

    · 自动发现局域网内的服务器（含 HTTP/WS 端口与房间人数）；
    · 把用户手填的「IP」或「IP:端口」解析成真实的 HTTP 端口与 WS 端口。

注意：UDP 广播与 HTTP 探测都是阻塞操作，界面侧应放到后台线程（见 client/bridge.py）。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

DISCOVER_MAGIC = 'SNAKE_DISCOVER'
DISCOVER_PORT = 41999
DEFAULT_HTTP_PORT = 8080
DEFAULT_WS_PORT = 8081


def local_ipv4() -> list[str]:
    """列出本机所有 IPv4 地址（尽力而为，失败返回空列表）。

    Returns:
        形如 ['192.168.1.10', '127.0.0.1'] 的地址列表。
    """
    ips: list[str] = []
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    if '127.0.0.1' not in ips:
        ips.append('127.0.0.1')
    return ips


def _broadcast_targets() -> list[str]:
    """构造广播目标：全网广播 + 各网段的 /24 广播地址。

    Returns:
        目标地址列表。
    """
    targets = ['255.255.255.255']
    for ip in local_ipv4():
        parts = ip.split('.')
        if len(parts) == 4 and ip != '127.0.0.1':
            guess = '%s.%s.%s.255' % (parts[0], parts[1], parts[2])
            if guess not in targets:
                targets.append(guess)
    return targets


def http_discover(host: str, port: int, timeout: float = 1.2) -> dict | None:
    """请求服务器的 /api/discover，成功时返回服务器信息。

    局域网请求一律直连，避免系统代理把 127.0.0.1/内网地址转发到外部。

    Args:
        host: 服务器 IP。
        port: HTTP 端口。
        timeout: 超时秒数。

    Returns:
        信息字典（含 port / wsPort / name / version / rooms / players）或 None。
    """
    url = 'http://%s:%d/api/discover' % (host, int(port))
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={'User-Agent': 'PlayWithSnake-Client'})
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8', 'replace'))
    except (urllib.error.URLError, ValueError, OSError):
        return None
    if isinstance(data, dict) and data.get('ok'):
        return data
    return None


def _normalize(info: dict, host: str, source: str) -> dict:
    """把服务器返回的原始信息整理成界面可直接使用的结构。

    Args:
        info: /api/discover 或 UDP 广播的原始字典。
        host: 服务器 IP。
        source: 来源标记（udp / http）。

    Returns:
        规整后的服务器信息。
    """
    try:
        http_port = int(info.get('port') or DEFAULT_HTTP_PORT)
    except Exception:
        http_port = DEFAULT_HTTP_PORT
    try:
        ws_port = int(info.get('wsPort') or DEFAULT_WS_PORT)
    except Exception:
        ws_port = DEFAULT_WS_PORT
    return {
        'host': host,
        'httpPort': http_port,
        'wsPort': ws_port,
        'name': str(info.get('name') or '贪吃蛇大冒险服务器'),
        'version': str(info.get('version') or ''),
        'rooms': int(info.get('rooms') or 0),
        'players': int(info.get('players') or 0),
        'online': int(info.get('online') or 0),
        'source': source,
    }


class ServerFinder:
    """局域网服务器发现与端口解析。"""

    def scan(self, timeout: float = 2.5) -> list[dict]:
        """扫描局域网服务器（UDP 广播 + 本机 HTTP 探测）。

        Args:
            timeout: 总耗时上限（秒）。

        Returns:
            去重后的服务器列表，本机服务器排在前面。
        """
        found: dict[tuple[str, int], dict] = {}
        self._scan_udp(found, timeout)
        self._scan_http(found)
        return sorted(found.values(), key=lambda s: (s['host'] != '127.0.0.1', s['host']))

    def _scan_udp(self, found: dict, timeout: float) -> None:
        """发送 UDP 探测并收集回包。

        Args:
            found: 结果累加字典（键为 (host, wsPort)）。
            timeout: 收集时长（秒）。
        """
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(('0.0.0.0', 0))
            sock.settimeout(0.25)
            payload = DISCOVER_MAGIC.encode('utf-8')
            targets = _broadcast_targets()
            deadline = time.time() + max(0.8, timeout)
            next_send = 0.0
            sends = 0
            while time.time() < deadline:
                if sends < 3 and time.time() >= next_send:
                    for target in targets:
                        try:
                            sock.sendto(payload, (target, DISCOVER_PORT))
                        except OSError:
                            pass
                    sends += 1
                    next_send = time.time() + 0.6
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._take_udp(found, data, addr[0])
        except OSError:
            return
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    @staticmethod
    def _take_udp(found: dict, data: bytes, host: str) -> None:
        """解析一个 UDP 回包并累加结果。

        Args:
            found: 结果累加字典。
            data: 原始报文。
            host: 来源 IP。
        """
        if not data or b'snake' not in data.lower():
            return
        try:
            info = json.loads(data.decode('utf-8', 'replace'))
        except ValueError:
            return
        if not isinstance(info, dict):
            return
        srv = _normalize(info, host, 'udp')
        found[(srv['host'], srv['wsPort'])] = srv

    def _scan_http(self, found: dict) -> None:
        """探测本机默认端口上的服务器（UDP 被禁用时的兜底）。

        Args:
            found: 结果累加字典。
        """
        info = http_discover('127.0.0.1', DEFAULT_HTTP_PORT, timeout=0.6)
        if info:
            srv = _normalize(info, '127.0.0.1', 'http')
            found.setdefault((srv['host'], srv['wsPort']), srv)

    def resolve(self, text: str, timeout: float = 1.0) -> dict:
        """把用户输入的地址解析成真实的 HTTP / WS 端口。

        Args:
            text: "IP"、"IP:端口" 或完整 URL。
            timeout: 单次 HTTP 探测超时。

        Returns:
            {'ok': bool, 'host': str, 'httpPort': int, 'wsPort': int,
             'name': str, 'version': str}。
        """
        raw = str(text or '').strip()
        for prefix in ('ws://', 'wss://', 'http://', 'https://'):
            if raw.lower().startswith(prefix):
                raw = raw[len(prefix):]
        raw = raw.strip().rstrip('/')
        if not raw:
            return {'ok': False, 'host': '', 'httpPort': DEFAULT_HTTP_PORT,
                    'wsPort': DEFAULT_WS_PORT, 'name': '', 'version': ''}
        parts = raw.split(':')
        host = parts[0] or '127.0.0.1'
        given = 0
        if len(parts) > 1:
            try:
                given = int(parts[1])
            except ValueError:
                given = 0

        candidates: list[int] = []
        if given:
            candidates.append(given)
            # 用户可能填的是 WS 端口，顺带试一下相邻的 HTTP 端口
            if given > 1:
                candidates.append(given - 1)
        for port in (DEFAULT_HTTP_PORT, DEFAULT_WS_PORT):
            if port not in candidates:
                candidates.append(port)
        for port in candidates:
            info = http_discover(host, port, timeout=timeout)
            if info:
                srv = _normalize(info, host, 'http')
                return {'ok': True, 'host': srv['host'], 'httpPort': srv['httpPort'],
                        'wsPort': srv['wsPort'], 'name': srv['name'], 'version': srv['version']}

        # 探测失败：把用户填写的端口当作 WS 端口，HTTP 端口按「WS 端口 - 1」推断
        ws_port = given or DEFAULT_WS_PORT
        http_port = ws_port - 1 if given and ws_port > 1 else DEFAULT_HTTP_PORT
        if http_port < 1:
            http_port = DEFAULT_HTTP_PORT
        return {'ok': False, 'host': host, 'httpPort': http_port,
                'wsPort': ws_port, 'name': '', 'version': ''}
