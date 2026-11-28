"""客户端启动决策：把发现到的服务器整理成「浏览器可直接打开」的地址。

这里只放纯函数，不依赖 Qt，便于单元测试：
    · server_page_url  把服务器信息拼成 http://主机:HTTP端口/
    · match_last       判断上次用过的服务器是否还在线
    · auto_open_target 决定是否可以自动打开（不打扰用户）
    · server_title     列表里显示的主标题
"""
from __future__ import annotations

DEFAULT_HTTP_PORT = 8080
DEFAULT_WS_PORT = 8081


def _clean_host(text: str) -> str:
    """把用户填写的地址规整成纯主机名。

    Args:
        text: 'IP'、'IP:端口'、'http://IP:端口/xxx' 等写法。

    Returns:
        主机名（无法解析时返回空字符串）。
    """
    raw = str(text or '').strip()
    for prefix in ('ws://', 'wss://', 'http://', 'https://'):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.strip().rstrip('/').split('/')[0]
    if not raw:
        return ''
    return raw.split(':')[0].strip()


def server_page_url(srv: dict | None) -> str:
    """拼出该服务器的网页地址。

    Args:
        srv: 服务器信息字典（host / httpPort）。

    Returns:
        形如 http://192.168.1.5:8080/ 的地址；信息缺失时返回空字符串。
    """
    if not isinstance(srv, dict):
        return ''
    host = _clean_host(srv.get('host') or '')
    if not host:
        return ''
    try:
        port = int(srv.get('httpPort') or DEFAULT_HTTP_PORT)
    except Exception:
        port = DEFAULT_HTTP_PORT
    if port <= 0 or port > 65535:
        port = DEFAULT_HTTP_PORT
    return 'http://%s:%d/' % (host, port)


def match_last(servers: list[dict], last: str) -> dict | None:
    """在扫描结果里找上次连接过的那台服务器。

    Args:
        servers: 扫描结果。
        last: 上次使用的地址（'IP'、'IP:端口' 或完整 URL）。

    Returns:
        命中的服务器信息，未命中返回 None。
    """
    host = _clean_host(last)
    if not host:
        return None
    for srv in servers or []:
        if _clean_host(srv.get('host') or '') == host:
            return srv
    return None


def collapse_servers(servers: list[dict], last: str = '',
                     own_hosts: set[str] | None = None) -> list[dict]:
    """把「本机自己」的多条地址合并成一条。

    同一台服务器常会同时以回环地址（本机兜底探测）和局域网地址（广播回包）出现，
    直接列出来会变成两条重复项，启动时的自动打开也会因为「多台」而失效。
    这里只合并「地址属于本机」的条目：回环地址必然是本机，局域网地址要看是否在
    own_hosts 里。别的机器即使在相同端口、相同版本出现，也各自独立成条，避免把
    两台真实服务器误判成一台。

    Args:
        servers: 扫描结果。
        last: 上次使用的地址。
        own_hosts: 本机拥有的 IPv4 地址（含 127.0.0.1）。

    Returns:
        合并后的服务器列表，保持原顺序。
    """
    own = set(own_hosts or ()) | {'127.0.0.1'}

    def ident(srv: dict) -> tuple:
        """同一台服务器的识别键（不含人数等易变字段）。"""
        return (str(srv.get('name') or ''), str(srv.get('version') or ''),
                str(srv.get('httpPort') or ''), str(srv.get('wsPort') or ''))

    groups: dict[tuple, list[dict]] = {}
    for srv in servers or []:
        if not server_page_url(srv):
            continue
        if _clean_host(srv.get('host') or '') in own:
            groups.setdefault(ident(srv), []).append(srv)

    merged: list[dict] = []
    emitted: set[tuple] = set()
    for srv in servers or []:
        if not server_page_url(srv):
            continue
        key = ident(srv)
        if _clean_host(srv.get('host') or '') in own:
            if key in emitted:
                continue
            emitted.add(key)
            members = groups[key]
            hit = match_last(members, last)
            if hit is not None:
                merged.append(hit)
                continue
            loop = [m for m in members if _clean_host(m.get('host') or '') == '127.0.0.1']
            merged.append(loop[0] if loop else members[0])
        else:
            merged.append(srv)
    return merged


def auto_open_target(servers: list[dict], last: str,
                     own_hosts: set[str] | None = None) -> dict | None:
    """判断本次是否可以自动打开浏览器。

    只在没有歧义时自动打开：上次用过的服务器还在，或局域网里只有一台服务器。
    多台服务器且都不是上次那台时返回 None，交给用户在列表里选择。

    Args:
        servers: 扫描结果。
        last: 上次使用的地址。
        own_hosts: 本机拥有的 IPv4 地址（用于合并本机重复条目）。

    Returns:
        可自动打开的服务器信息，或 None。
    """
    items = [s for s in (servers or []) if server_page_url(s)]
    if not items:
        return None
    hit = match_last(items, last)
    if hit is not None:
        return hit
    merged = collapse_servers(items, last, own_hosts)
    if len(merged) == 1:
        return merged[0]
    return None


def server_title(srv: dict) -> str:
    """列表项主标题：服务器名 + 地址。

    Args:
        srv: 服务器信息。

    Returns:
        一行文本。
    """
    name = str((srv or {}).get('name') or '贪吃蛇大冒险服务器')
    return '%s    %s' % (name, server_page_url(srv) or '地址未知')


def server_detail(srv: dict) -> str:
    """列表项副标题：版本、房间与在线人数。

    Args:
        srv: 服务器信息。

    Returns:
        一行文本。
    """
    srv = srv or {}
    ver = str(srv.get('version') or '').strip()
    ver_text = ('版本 %s' % ver) if ver else '版本未知'
    return '%s    房间 %d    在线 %d' % (
        ver_text, int(srv.get('rooms') or 0), int(srv.get('players') or 0))
