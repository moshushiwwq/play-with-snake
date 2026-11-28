"""客户端窗口：搜索局域网服务器，选中后用系统浏览器直接打开服务器页面。

设计取舍：
    · 页面由服务器自己托管（http://服务器:HTTP端口/），客户端不再起本地页面服务，
      因此没有端口占用、没有旧缓存残留问题；
    · 扫描与地址解析都在后台线程执行，窗口保持可操作，避免搜索时界面卡住；
    · 全部文案为纯文本，不使用表情符号或装饰性符号；
    · 只使用普通用户权限：不写系统目录、不改注册表、不碰防火墙、不请求提权。
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from client.discovery import ServerFinder, local_ipv4
from client.launcher import (
    auto_open_target, collapse_servers, match_last, server_detail, server_page_url,
    server_title,
)
from shared.qt_icons import make_icon

SCAN_TIMEOUT = 2.0


class _Bridge(QWidget):
    """把后台线程的结果安全地送回界面线程。"""

    scanned = pyqtSignal(object)
    resolved = pyqtSignal(object)


class ServerPicker(QMainWindow):
    """服务器搜索与打开窗口。"""

    def __init__(self, ctx):
        """初始化窗口。

        Args:
            ctx: 客户端上下文（config 用于记录上次服务器与窗口位置）。
        """
        super().__init__()
        self.ctx = ctx
        self.finder = ServerFinder()
        self.servers: list[dict] = []
        self._own_hosts: set[str] = set()
        self._scanning = False
        self._resolving = False
        self._auto_opened = False

        self.setWindowTitle('Play With Snake 客户端')
        self.setWindowIcon(make_icon('snake', '#0aa96a', 32))
        self.resize(720, 470)
        self.setMinimumSize(600, 400)

        self.bridge = _Bridge()
        self.bridge.scanned.connect(self._on_scanned)
        self.bridge.resolved.connect(self._on_resolved)

        self._build_ui()
        geo = ctx.config.geometry
        if geo:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        """搭建窗口布局。"""
        root = QWidget()
        root.setObjectName('Root')
        self.setCentralWidget(root)
        box = QVBoxLayout(root)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel('Play With Snake')
        title.setStyleSheet('font-size:19px;font-weight:800;color:#0aa96a;')
        head.addWidget(title)
        self.state = QLabel('尚未搜索')
        self.state.setObjectName('Pill')
        head.addWidget(self.state)
        head.addStretch(1)
        box.addLayout(head)

        self.hint = QLabel('点击「搜索服务器」查找同一个局域网里正在运行的服务端，选中后由浏览器直接打开它的页面。')
        self.hint.setObjectName('Muted')
        self.hint.setWordWrap(True)
        box.addWidget(self.hint)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setStyleSheet(
            'QProgressBar{background:#f0f5fb;border:none;border-radius:3px;}'
            'QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,'
            'stop:0 #41e39a,stop:1 #22b8f0);border-radius:3px;}')
        self.bar.hide()
        box.addWidget(self.bar)

        card = QFrame()
        card.setObjectName('Card')
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(14, 12, 14, 14)
        card_box.setSpacing(8)
        card_title = QLabel('服务器列表')
        card_title.setObjectName('CardTitle')
        card_box.addWidget(card_title)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setStyleSheet(
            'QListWidget{background:#ffffff;border:1px solid rgba(30,50,90,.09);'
            'border-radius:10px;padding:4px;color:#223142;outline:0;}'
            'QListWidget::item{padding:8px 10px;border-radius:8px;outline:0;}'
            'QListWidget::item:hover{background:#f4faf7;}'
            'QListWidget::item:selected{background:#eaf7f2;color:#0b6b47;}')
        self.list.itemActivated.connect(lambda _: self.open_selected())
        self.list.itemDoubleClicked.connect(lambda _: self.open_selected())
        card_box.addWidget(self.list, 1)
        box.addWidget(card, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_scan = QPushButton('搜索服务器')
        self.btn_scan.setObjectName('Primary')
        self.btn_scan.clicked.connect(lambda: self.scan(auto=False))
        row.addWidget(self.btn_scan)
        self.btn_open = QPushButton('在浏览器打开')
        self.btn_open.clicked.connect(self.open_selected)
        row.addWidget(self.btn_open)
        box.addLayout(row)

        manual = QHBoxLayout()
        manual.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText('手动输入服务器地址，例如 192.168.1.5 或 192.168.1.5:8080')
        self.edit.returnPressed.connect(self.open_manual)
        manual.addWidget(self.edit, 1)
        self.btn_manual = QPushButton('打开该地址')
        self.btn_manual.clicked.connect(self.open_manual)
        manual.addWidget(self.btn_manual)
        box.addLayout(manual)

        self.note = QLabel('客户端只用普通用户权限运行：不修改系统设置、不需要管理员确认。')
        self.note.setObjectName('Muted')
        box.addWidget(self.note)

    # ---------------------------------------------------------------- 搜索
    def scan(self, auto: bool = False) -> None:
        """启动一次局域网扫描（后台线程）。

        Args:
            auto: 是否为启动时的自动搜索（用于决定是否自动打开）。
        """
        if self._scanning:
            return
        self._scanning = True
        self._auto = auto
        self.btn_scan.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.bar.show()
        self.state.setText('搜索中')
        self.hint.setText('正在向局域网广播探测包，等待服务器回应…')
        hint = self.ctx.config.last_server
        threading.Thread(
            target=self._scan_worker, args=(hint,), daemon=True, name='client-scan').start()

    def _scan_worker(self, hint: str) -> None:
        """后台扫描线程。

        Args:
            hint: 上次使用的服务器地址。
        """
        try:
            found = self.finder.scan(SCAN_TIMEOUT, hint)
        except Exception:
            found = []
        self.bridge.scanned.emit(list(found or []))

    def _on_scanned(self, servers: list) -> None:
        """扫描结束：刷新列表，必要时自动打开。

        Args:
            servers: 扫描结果。
        """
        self._scanning = False
        self.bar.hide()
        self.btn_scan.setEnabled(True)
        self.btn_open.setEnabled(True)
        last = self.ctx.config.last_server
        self._own_hosts = set(local_ipv4())
        self.servers = collapse_servers(
            [s for s in servers if server_page_url(s)], last, self._own_hosts)
        self._fill_list()
        if not self.servers:
            self.state.setText('未发现服务器')
            self.hint.setText('没有收到任何服务器回应。请确认服务端已启动、与本机在同一个局域网，'
                              '或在下方直接填写服务器地址。')
            return
        self.state.setText('已发现 %d 台' % len(self.servers))
        self.hint.setText('选中一台服务器后点击「在浏览器打开」，浏览器会直接进入它的游戏页面。')
        hit = match_last(self.servers, last)
        if hit is not None:
            self._select_host(hit.get('host') or '')
        elif len(self.servers) == 1:
            self.list.setCurrentRow(0)
        target = auto_open_target(self.servers, last, self._own_hosts) \
            if getattr(self, '_auto', False) else None
        if target is not None and not self._auto_opened:
            self._auto_opened = True
            self.open_server(target, auto=True)

    def _fill_list(self) -> None:
        """把服务器列表写入控件。"""
        self.list.clear()
        for srv in self.servers:
            item = QListWidgetItem('%s\n%s' % (server_title(srv), server_detail(srv)))
            item.setData(Qt.ItemDataRole.UserRole, srv)
            self.list.addItem(item)

    def _select_host(self, host: str) -> None:
        """按主机名选中列表项。

        Args:
            host: 服务器主机名。
        """
        for i in range(self.list.count()):
            srv = self.list.item(i).data(Qt.ItemDataRole.UserRole) or {}
            if str(srv.get('host') or '') == host:
                self.list.setCurrentRow(i)
                return

    # ---------------------------------------------------------------- 打开
    def current_server(self) -> dict | None:
        """当前选中的服务器。

        Returns:
            服务器信息，未选中返回 None。
        """
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def open_selected(self) -> None:
        """打开当前选中的服务器。"""
        srv = self.current_server()
        if srv is None:
            self.state.setText('请先选择服务器')
            self.hint.setText('列表里还没有选中的服务器：先搜索，或在下方直接填写地址。')
            return
        self.open_server(srv)

    def open_server(self, srv: dict, auto: bool = False) -> None:
        """用系统默认浏览器打开服务器页面。

        Args:
            srv: 服务器信息。
            auto: 是否为自动打开（自动打开时额外在窗口里说明）。
        """
        url = server_page_url(srv)
        if not url:
            self.state.setText('地址无效')
            return
        ok = self.ctx.open_url(url)
        host = str(srv.get('host') or '')
        if ok:
            self.ctx.config.set_last_server(host)
            self.state.setText('已打开')
            self.hint.setText(('已自动在浏览器打开：%s' if auto else '已在浏览器打开：%s') % url)
        else:
            self.state.setText('打开失败')
            self.hint.setText('没能拉起默认浏览器，请手动复制地址访问：%s' % url)

    def open_manual(self) -> None:
        """解析手动输入的地址并在浏览器中打开。"""
        text = self.edit.text().strip()
        if not text:
            self.state.setText('请输入地址')
            self.edit.setFocus()
            return
        if self._resolving:
            return
        self._resolving = True
        self.btn_manual.setEnabled(False)
        self.bar.show()
        self.state.setText('解析地址')
        self.hint.setText('正在确认 %s 上的服务器端口…' % text)
        threading.Thread(target=self._resolve_worker, args=(text,),
                         daemon=True, name='client-resolve').start()

    def _resolve_worker(self, text: str) -> None:
        """后台解析地址线程。

        Args:
            text: 用户输入。
        """
        try:
            info = self.finder.resolve(text)
        except Exception:
            info = {'ok': False, 'host': '', 'httpPort': 0, 'wsPort': 0}
        self.bridge.resolved.emit(info)

    def _on_resolved(self, info: dict) -> None:
        """解析结束：打开地址并同步列表状态。

        Args:
            info: 解析结果。
        """
        self._resolving = False
        self.bar.hide()
        self.btn_manual.setEnabled(True)
        if not info or not info.get('host'):
            self.state.setText('地址无效')
            self.hint.setText('地址无法识别，请填写 IP 或 IP:端口。')
            return
        srv = {
            'host': info.get('host'),
            'httpPort': info.get('httpPort'),
            'wsPort': info.get('wsPort'),
            'name': info.get('name') or '',
            'version': info.get('version') or '',
            'rooms': 0,
            'players': 0,
        }
        if not info.get('ok'):
            self.hint.setText('没有在该地址上探测到服务器，仍按 %s 打开页面。'
                              % server_page_url(srv))
        self.open_server(srv)

    # ---------------------------------------------------------------- 生命周期
    def show_and_raise(self) -> None:
        """显示并激活窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭窗口即退出客户端（不常驻托盘）。

        Args:
            event: 关闭事件。
        """
        try:
            self.ctx.config.set_geometry(self.saveGeometry())
        except Exception:
            pass
        event.accept()
        self.ctx.quit()
