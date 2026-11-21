"""服务端管理员账号：scrypt 高强度哈希、会话 Cookie、失败递增锁定。

安全要点：
    · 密码绝不落明文，只保存盐与 scrypt 参数；
    · 使用 hmac.compare_digest 做恒定时间比对，防止时序侧信道；
    · 会话 token 为 24 字节随机数，12 小时过期，httpOnly Cookie；
    · 连续失败 5 次起锁定，时长从 60 秒翻倍，最长 15 分钟。

账号由「用户名 + 密码」组成；用户名与密码都可在管理面板修改。
未设置过密码时视为开放状态（任何能访问本机的人都可进入面板），
与历史版本行为保持兼容。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

SESSION_MS = 12 * 3600 * 1000
COOKIE_NAME = 'snake_panel'
DEFAULT_USER = 'admin'


class PanelAuth:
    """管理员账号与会话管理。"""

    def __init__(self, config: dict | None, persist):
        """初始化。

        Args:
            config: 已保存的账号参数 {salt,hash,N,r,p,user} 或 None。
            persist: 持久化回调 fn(params)，用于把新账号写入配置。
        """
        cfg = config or {}
        self.salt = str(cfg.get('salt') or '')
        self.hash = str(cfg.get('hash') or '')
        self.n = int(cfg.get('N') or 16384)
        self.r = int(cfg.get('r') or 8)
        self.p = int(cfg.get('p') or 1)
        self.user = str(cfg.get('user') or '')
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
        return {'salt': self.salt, 'hash': self.hash, 'N': self.n, 'r': self.r,
                'p': self.p, 'user': self.user}

    def username(self) -> str:
        """当前管理员用户名（未设置时返回默认用户名）。"""
        return self.user or DEFAULT_USER

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

    def verify(self, username: str = '', password: str = '') -> bool:
        """校验账号（未设置密码时恒为真）。

        兼容历史调用：若只传入一个位置参数，按密码处理。

        Args:
            username: 用户名。
            password: 明文密码。

        Returns:
            正确返回 True。
        """
        if not self.enabled():
            return True
        # 兼容旧签名 verify(password)：第二个参数缺省时第一个参数视为密码
        if password == '' and username and not self.user:
            password = username
            username = ''
        if self.user and str(username or '') != self.user:
            return False
        try:
            calc = self.compute(str(password or ''), self.salt)
            return hmac.compare_digest(calc, self.hash)
        except Exception:
            return False

    def set_password(self, new_password: str) -> None:
        """只设置/修改/清除密码（保留现有用户名）。

        Args:
            new_password: 新密码，空字符串表示清除。
        """
        pwd = str(new_password or '')
        if not pwd:
            self._clear()
            return
        self.salt = secrets.token_hex(16)
        self.hash = self.compute(pwd, self.salt)
        self.sessions.clear()
        self._persist(self.params())

    def set_account(self, username: str, new_password: str) -> None:
        """设置用户名与密码；空密码表示清除账号保护。

        Args:
            username: 新用户名（空则回退默认 admin）。
            new_password: 新密码，空字符串表示清除。
        """
        pwd = str(new_password or '')
        if not pwd:
            self._clear()
            return
        self.user = str(username or DEFAULT_USER).strip() or DEFAULT_USER
        self.salt = secrets.token_hex(16)
        self.hash = self.compute(pwd, self.salt)
        self.sessions.clear()
        self._persist(self.params())

    def _clear(self) -> None:
        """清除账号保护并落盘。"""
        self.salt = ''
        self.hash = ''
        self.user = ''
        self.sessions.clear()
        self._persist(None)

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
