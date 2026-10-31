"""服务端访问密码：scrypt 高强度哈希、会话 Cookie、失败递增锁定。

安全要点：
    · 密码绝不落明文，只保存盐与 scrypt 参数；
    · 使用 hmac.compare_digest 做恒定时间比对，防止时序侧信道；
    · 会话 token 为 24 字节随机数，12 小时过期，httpOnly Cookie；
    · 连续失败 5 次起锁定，时长从 60 秒翻倍，最长 15 分钟。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SESSION_MS = 12 * 3600 * 1000
COOKIE_NAME = 'snake_panel'


class PanelAuth:
    """控制台访问密码管理。"""

    def __init__(self, config: dict | None, persist):
        """初始化。

        Args:
            config: 已保存的密码参数 {salt,hash,N,r,p} 或 None。
            persist: 持久化回调 fn(params)，用于把新密码写入配置。
        """
        cfg = config or {}
        self.salt = str(cfg.get('salt') or '')
        self.hash = str(cfg.get('hash') or '')
        self.n = int(cfg.get('N') or 16384)
        self.r = int(cfg.get('r') or 8)
        self.p = int(cfg.get('p') or 1)
        self.sessions: dict[str, int] = {}
        self.fails: dict[str, dict] = {}
        self._persist = persist

    # ---------------------------------------------------------------- 状态
    def enabled(self) -> bool:
        """是否已设置访问密码。"""
        return bool(self.salt and self.hash)

    def params(self) -> dict | None:
        """导出可持久化的参数（未设置时返回 None）。"""
        if not self.enabled():
            return None
        return {'salt': self.salt, 'hash': self.hash, 'N': self.n, 'r': self.r, 'p': self.p}

    # ---------------------------------------------------------------- 密码
    def compute(self, password: str, salt: str) -> str:
        """计算 scrypt 哈希（64 字节 hex）。

        Args:
            password: 明文密码。
            salt: 盐。

        Returns:
            哈希十六进制字符串。
        """
        return hashlib.scrypt(str(password).encode('utf-8'), salt=salt.encode('utf-8'),
                              n=self.n, r=self.r, p=self.p, dklen=64).hex()

    def verify(self, password: str) -> bool:
        """校验密码（未设置密码时恒为真）。

        Args:
            password: 明文密码。

        Returns:
            正确返回 True。
        """
        if not self.enabled():
            return True
        try:
            calc = self.compute(password, self.salt)
            return hmac.compare_digest(calc, self.hash)
        except Exception:
            return False

    def set_password(self, new_password: str) -> None:
        """设置/修改/清除密码（空字符串表示清除）。

        Args:
            new_password: 新密码。
        """
        pwd = str(new_password or '')
        if not pwd:
            self.salt = ''
            self.hash = ''
            self.sessions.clear()
            self._persist(None)
            return
        self.salt = secrets.token_hex(16)
        self.hash = self.compute(pwd, self.salt)
        self.sessions.clear()
        self._persist(self.params())

    # ---------------------------------------------------------------- 会话
    def issue(self) -> str:
        """签发一个新的会话 token（12 小时有效）。

        Returns:
            32 位十六进制 token。
        """
        token = secrets.token_hex(24)
        self.sessions[token] = int(time.time() * 1000) + SESSION_MS
        return token

    def valid(self, token: str | None) -> bool:
        """校验 token 是否有效（顺带清理过期项）。

        Args:
            token: 会话 token。

        Returns:
            有效返回 True。
        """
        if not token:
            return False
        exp = self.sessions.get(token)
        if exp is None:
            return False
        if exp < int(time.time() * 1000):
            self.sessions.pop(token, None)
            return False
        return True

    def authed(self, token: str | None) -> bool:
        """是否已通过登录（未设置密码时视为已登录）。

        Args:
            token: Cookie 中的 token。

        Returns:
            通过返回 True。
        """
        if not self.enabled():
            return True
        return self.valid(token)

    # ---------------------------------------------------------------- 锁定
    def fail(self, ip: str) -> dict:
        """记录一次失败；连续 5 次起锁定，时长翻倍，上限 15 分钟。

        Args:
            ip: 来源 IP。

        Returns:
            该 IP 的失败记录 {count, lockMs, until}。
        """
        rec = self.fails.get(ip) or {'count': 0, 'lockMs': 0, 'until': 0.0}
        rec['count'] += 1
        if rec['count'] >= 5:
            rec['lockMs'] = min(15 * 60 * 1000, (rec['lockMs'] * 2) if rec['lockMs'] else 60 * 1000)
            rec['until'] = time.time() + rec['lockMs'] / 1000.0
        self.fails[ip] = rec
        return rec

    def locked_for(self, ip: str) -> int:
        """查询某 IP 还需锁定多少秒。

        Args:
            ip: 来源 IP。

        Returns:
            剩余秒数（0 表示未锁定）。
        """
        rec = self.fails.get(ip)
        if not rec or not rec.get('until'):
            return 0
        left = rec['until'] - time.time()
        return int(round(left)) if left > 0 else 0

    def reset_fail(self, ip: str) -> None:
        """登录成功后清除失败计数。

        Args:
            ip: 来源 IP。
        """
        self.fails.pop(ip, None)

    def cookie_header(self, token: str) -> str:
        """构造下发 Cookie 的响应头。

        Args:
            token: 会话 token。

        Returns:
            Set-Cookie 值。
        """
        return '%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200' % (COOKIE_NAME, token)
