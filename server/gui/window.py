"""服务端主窗口：状态、设置、自启动、局域网地址、房间/连接、用户与 IP、实时日志。

界面沿用客户端网页的设计语言（白底、浅色卡片、青绿渐变主按钮、自绘图标），
所有功能都直接操作 Python 侧对象，HTML 只保留「访问密码 + 排行榜」面板。
"""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtNetwork import QHostAddress, QNetworkInterface
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy,
)

from server.gui import icons
from server.gui.panel_dialog import PanelDialog
from server.sys import autostart


def _card(title: str, icon_name: str = '') -> tuple[QFrame, QVBoxLayout]:
    """创建一个带标题的卡片容器。

    Args:
        title: 卡片标题。
        icon_name: 标题图标名。

    Returns:
        (卡片框架, 内容布局)。
    """
    card = QFrame()
    card.setObjectName('Card')
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(9)
    head = QHBoxLayout()
    head.setSpacing(6)
    if icon_name:
        ic = QLabel()
        ic.setPixmap(icons.make_pixmap(icon_name, '#8a99b8', 14))
        head.addWidget(ic)
    tl = QLabel(title)
    tl.setObjectName('CardTitle')
    head.addWidget(tl)
    head.addStretch(1)
    lay.addLayout(head)
    return card, lay


def _kv(label: str, value: str = '-') -> tuple[QWidget, QLabel]:
    """生成一行「标签 + 值」。

    Args:
        label: 标签文本。
        value: 初始值。

    Returns:
        (行容器, 值标签)。
    """
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    k = QLabel(label)
    k.setObjectName('Muted')
    k.setMinimumWidth(64)
    v = QLabel(value)
    v.setObjectName('Strong')
    h.addWidget(k)
    h.addWidget(v)
    h.addStretch(1)
    return row, v


class ServerWindow(QMainWindow):
    """服务端控制台主窗口。"""

    def __init__(self, ctx):
        """初始化窗口。

        Args:
            ctx: 应用上下文（含 config/service/http/ws/logbus/auth/...）。
        """
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle('Play With Snake · 服务器控制台')
        self.setWindowIcon(icons.make_icon('snake', '#0aa96a', 32))
        self.resize(1180, 860)
        self._note_guard = False
        self._last_tick = time.time()
        self._build()
        self._load_config()
        self.refresh_all()
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(150)
        self._log_timer.timeout.connect(self._drain_logs)
        self._log_timer.start()
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self.refresh_all)
        self._ui_timer.start()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        """构建整个界面骨架。"""
        root = QWidget()
        root.setObjectName('Root')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(10)

        # 顶部栏
        head = QHBoxLayout()
        head.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(icons.make_pixmap('snake', '#0aa96a', 26))
        head.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t1 = QLabel('Play With Snake · 服务器控制台')
        t1.setStyleSheet('font-size:16px;font-weight:800;')
        t2 = QLabel('多人联机 · 房间公示 · 联机排行榜 · 无第三方依赖')
        t2.setObjectName('Muted')
        title_box.addWidget(t1)
        title_box.addWidget(t2)
        head.addLayout(title_box)
        head.addStretch(1)
        self.pill = QLabel('● 已停止')
        self.pill.setObjectName('Pill')
        head.addWidget(self.pill)
        btn_panel = QPushButton('访问密码与排行榜')
        btn_panel.setIcon(icons.make_icon('key', '#3a4a66', 16))
        btn_panel.clicked.connect(self._open_panel)
        head.addWidget(btn_panel)
        btn_open = QPushButton('打开游戏页面')
        btn_open.setIcon(icons.make_icon('globe', '#3a4a66', 16))
        btn_open.clicked.connect(self._open_game_page)
        head.addWidget(btn_open)
        outer.addLayout(head)

        # 可滚动的主体（两列卡片）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 1 运行状态
        c1, l1 = _card('运行状态', 'sliders')
        row_btn = QHBoxLayout()
        self.btn_start = QPushButton('启动服务器')
        self.btn_start.setObjectName('Primary')
        self.btn_start.setIcon(icons.make_icon('play', '#04121a', 16))
        self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton('停止')
        self.btn_stop.setObjectName('Danger')
        self.btn_stop.setIcon(icons.make_icon('stop', '#d64545', 16))
        self.btn_stop.clicked.connect(self._stop)
        row_btn.addWidget(self.btn_start)
        row_btn.addWidget(self.btn_stop)
        l1.addLayout(row_btn)
        g1 = QGridLayout()
        g1.setHorizontalSpacing(18)
        g1.setVerticalSpacing(6)
        self.v_http, self.v_http_l = self._grid_kv(g1, 0, 0, 'HTTP 端口')
        self.v_ws, self.v_ws_l = self._grid_kv(g1, 0, 1, 'WebSocket 端口')
        self.v_online, self.v_online_l = self._grid_kv(g1, 1, 0, '在线连接')
        self.v_rooms, self.v_rooms_l = self._grid_kv(g1, 1, 1, '房间 / 对局')
        self.v_uptime, self.v_uptime_l = self._grid_kv(g1, 2, 0, '运行时长')
        self.v_players, self.v_players_l = self._grid_kv(g1, 2, 1, '房间内玩家')
        l1.addLayout(g1)
        grid.addWidget(c1, 0, 0)

        # 2 基本设置
        c2, l2 = _card('基本设置', 'gear')
        g2 = QGridLayout()
        g2.setHorizontalSpacing(8)
        g2.setVerticalSpacing(8)
        g2.addWidget(QLabel('HTTP 端口'), 0, 0)
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        g2.addWidget(self.sp_port, 0, 1)
        g2.addWidget(QLabel('WS 端口'), 0, 2)
        self.sp_ws = QSpinBox()
        self.sp_ws.setRange(1, 65535)
        g2.addWidget(self.sp_ws, 0, 3)
        g2.addWidget(QLabel('快照频率'), 1, 0)
        self.sp_hz = QSpinBox()
        self.sp_hz.setRange(5, 60)
        self.sp_hz.setSuffix(' Hz')
        g2.addWidget(self.sp_hz, 1, 1)
        g2.addWidget(QLabel('自启动'), 1, 2)
        self.cb_autostart = QComboBox()
        self.cb_autostart.addItem('关闭', 'none')
        self.cb_autostart.addItem('登录后自动启动', 'logon')
        self.cb_autostart.addItem('开机自动启动（需管理员）', 'boot')
        g2.addWidget(self.cb_autostart, 1, 3)
        l2.addLayout(g2)
        self.ck_discovery = QCheckBox('开启内网自动发现（UDP 41999）')
        self.ck_tray = QCheckBox('启动时隐藏到系统托盘')
        self.ck_firewall = QCheckBox('同时放行防火墙端口（需管理员）')
        l2.addWidget(self.ck_discovery)
        l2.addWidget(self.ck_tray)
        l2.addWidget(self.ck_firewall)
        row_save = QHBoxLayout()
        self.btn_save = QPushButton('保存设置')
        self.btn_save.setIcon(icons.make_icon('gear', '#3a4a66', 16))
        self.btn_save.clicked.connect(self._save_config)
        self.btn_apply_sys = QPushButton('应用系统设置')
        self.btn_apply_sys.setIcon(icons.make_icon('shield', '#3a4a66', 16))
        self.btn_apply_sys.clicked.connect(self._apply_system)
        row_save.addWidget(self.btn_save)
        row_save.addWidget(self.btn_apply_sys)
        row_save.addStretch(1)
        l2.addLayout(row_save)
        tip = QLabel('端口或页面变更后需重启服务生效；数据保存在程序目录的 server_data 文件夹。')
        tip.setObjectName('Muted')
        tip.setWordWrap(True)
        l2.addWidget(tip)
        self.lbl_admin = QLabel()
        self.lbl_admin.setWordWrap(True)
        l2.addWidget(self.lbl_admin)
        grid.addWidget(c2, 0, 1)

        # 3 局域网地址
        c3, l3 = _card('局域网地址', 'globe')
        self.lan_box = QVBoxLayout()
        self.lan_box.setSpacing(6)
        l3.addLayout(self.lan_box)
        hint = QLabel('把游戏地址发给同一网络内的玩家；跨网络联机需要路由器把 TCP 8080 / 8081 与 UDP 41999 映射到本机。')
        hint.setObjectName('Muted')
        hint.setWordWrap(True)
        l3.addWidget(hint)
        grid.addWidget(c3, 1, 0)

        # 4 房间与连接
        c4, l4 = _card('房间与连接', 'house')
        tabs = QTabWidget()
        self.tbl_rooms = QTableWidget(0, 7)
        self.tbl_rooms.setHorizontalHeaderLabels(['房间码', '房主', '人数', '观战', '地图', '难度', '状态'])
        self.tbl_rooms.verticalHeader().setVisible(False)
        self.tbl_rooms.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_rooms.horizontalHeader().setStretchLastSection(True)
        self.tbl_conns = QTableWidget(0, 5)
        self.tbl_conns.setHorizontalHeaderLabels(['编号', 'IP', '昵称', '角色', '房间'])
        self.tbl_conns.verticalHeader().setVisible(False)
        self.tbl_conns.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_conns.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.tbl_rooms, '房间')
        tabs.addTab(self.tbl_conns, '连接')
        l4.addWidget(tabs)
        grid.addWidget(c4, 1, 1)

        # 5 联机用户与 IP
        c5, l5 = _card('联机用户与 IP 备注', 'users')
        self.tbl_users = QTableWidget(0, 7)
        self.tbl_users.setHorizontalHeaderLabels(['昵称', 'IP', '单机最高', '联机局数', '胜场', '总分', '备注（回车保存）'])
        self.tbl_users.verticalHeader().setVisible(False)
        self.tbl_users.horizontalHeader().setStretchLastSection(True)
        self.tbl_users.itemChanged.connect(self._on_note_changed)
        l5.addWidget(self.tbl_users)
        grid.addWidget(c5, 2, 0)

        # 6 实时日志
        c6, l6 = _card('实时日志', 'list')
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(220)
        l6.addWidget(self.log_box)
        row_log = QHBoxLayout()
        b_clear = QPushButton('清空显示')
        b_clear.setIcon(icons.make_icon('trash', '#3a4a66', 16))
        b_clear.clicked.connect(lambda: self.log_box.clear())
        b_open = QPushButton('打开日志文件')
        b_open.setIcon(icons.make_icon('file', '#3a4a66', 16))
        b_open.clicked.connect(self._open_log_file)
        b_copy = QPushButton('复制全部')
        b_copy.setIcon(icons.make_icon('clipboard', '#3a4a66', 16))
        b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.log_box.toPlainText()))
        row_log.addWidget(b_clear)
        row_log.addWidget(b_open)
        row_log.addWidget(b_copy)
        row_log.addStretch(1)
        l6.addLayout(row_log)
        grid.addWidget(c6, 2, 1)

        self._initial_logs()

    def _grid_kv(self, grid: QGridLayout, r: int, c: int, label: str) -> tuple[QLabel, QLabel]:
        """在网格中放一个「标签 + 值」，返回值标签。"""
        box = QVBoxLayout()
        box.setSpacing(2)
        k = QLabel(label)
        k.setObjectName('Muted')
        v = QLabel('-')
        v.setStyleSheet('font-size:18px;font-weight:900;')
        box.addWidget(k)
        box.addWidget(v)
        holder = QWidget()
        holder.setLayout(box)
        grid.addWidget(holder, r, c)
        return holder, v

    def _initial_logs(self) -> None:
        """把已缓存的日志填入文本框。"""
        for item in self.ctx.logbus.recent(200):
            self._append_log(item)

    def _append_log(self, item: dict) -> None:
        """追加一行日志（带颜色）。"""
        color = {'ok': '#0aa96a', 'warn': '#a97a00', 'error': '#d64545'}.get(item.get('level'), '#33415c')
        self.log_box.appendHtml(
            '<span style="color:#9aa8c4">[%s]</span> <span style="color:%s">%s</span>' % (
                item.get('ts', ''), color, _escape(item.get('text', ''))))

    def _drain_logs(self) -> None:
        """定时拉取增量日志。"""
        for item in self.ctx.logbus.drain():
            self._append_log(item)

    # ---------------------------------------------------------------- 配置
    def _load_config(self) -> None:
        """把配置读入控件。"""
        c = self.ctx.config
        self.sp_port.setValue(c.port)
        self.sp_ws.setValue(c.ws_port)
        self.sp_hz.setValue(c.snapshot_hz)
        self.ck_discovery.setChecked(bool(c.data.get('discovery', True)))
        self.ck_tray.setChecked(bool(c.data.get('trayStart', False)))
        idx = self.cb_autostart.findData(c.data.get('autostart', 'none'))
        self.cb_autostart.setCurrentIndex(max(0, idx))
        self.ck_firewall.setChecked(bool(c.data.get('firewall', False)))
        if self.ctx.admin:
            self.lbl_admin.setText('当前以管理员身份运行：可放行防火墙、设置开机自启。')
            self.lbl_admin.setStyleSheet('color:#0aa96a;font-weight:700;')
        else:
            self.lbl_admin.setText('当前为普通用户：防火墙放行与开机自启会失败，请右键程序选择「以管理员身份运行」。')
            self.lbl_admin.setStyleSheet('color:#a97a00;font-weight:700;')
        self._refresh_lan()

    def _save_config(self) -> None:
        """保存基本设置。"""
        c = self.ctx.config
        c.data['port'] = int(self.sp_port.value())
        c.data['wsPort'] = int(self.sp_ws.value())
        c.data['snapshotHz'] = int(self.sp_hz.value())
        c.data['discovery'] = bool(self.ck_discovery.isChecked())
        c.data['trayStart'] = bool(self.ck_tray.isChecked())
        c.data['autostart'] = self.cb_autostart.currentData()
        c.data['firewall'] = bool(self.ck_firewall.isChecked())
        c.save()
        self.ctx.service.snapshot_hz = c.snapshot_hz
        self.ctx.logbus.push('设置已保存（端口/页面变更需重启服务生效）', 'ok')
        self.refresh_all()

    def _apply_system(self) -> None:
        """应用自启动与防火墙设置。"""
        mode = self.cb_autostart.currentData() or 'none'
        if mode != 'none':
            ok, msg = autostart.apply(mode)
            self.ctx.logbus.push(msg, 'ok' if ok else 'warn')
            if not ok:
                QMessageBox.warning(self, '自启动设置失败', msg)
        else:
            ok, msg = autostart.apply('none')
            self.ctx.logbus.push(msg, 'ok')
        if self.ck_firewall.isChecked():
            ok, msg = autostart.firewall(True, (self.ctx.config.port, self.ctx.config.ws_port))
            self.ctx.logbus.push(msg, 'ok' if ok else 'warn')
        self.refresh_all()

    # ---------------------------------------------------------------- 服务
    def _start(self) -> None:
        """启动 HTTP / WebSocket / 内网发现。"""
        ok, msg = self.ctx.start_services()
        self.ctx.logbus.push(msg, 'ok' if ok else 'error')
        self.refresh_all()

    def _stop(self) -> None:
        """停止所有网络服务。"""
        self.ctx.stop_services()
        self.ctx.logbus.push('服务器已停止', 'warn')
        self.refresh_all()

    def _open_panel(self) -> None:
        """打开「访问密码 + 排行榜」面板。"""
        if not self.ctx.http_running:
            QMessageBox.information(self, '提示', '请先启动服务器，再打开面板。')
            return
        dlg = PanelDialog('http://127.0.0.1:%d/panel' % self.ctx.config.port, self)
        dlg.exec()

    def _open_game_page(self) -> None:
        """用系统浏览器打开游戏页面（便于本机快速验证）。"""
        import webbrowser
        webbrowser.open('http://127.0.0.1:%d/' % self.ctx.config.port)

    def _open_log_file(self) -> None:
        """打开日志文件所在目录。"""
        ok, msg = autostart.open_data_folder(self.ctx.data_dir)
        if not ok:
            self.ctx.logbus.push(msg, 'warn')

    # ---------------------------------------------------------------- 刷新
    def refresh_all(self) -> None:
        """刷新状态、局域网地址、房间/连接与用户表。"""
        running = self.ctx.http_running and self.ctx.ws_running
        self.pill.setText('● 运行中' if running else '● 已停止')
        self.pill.setStyleSheet(
            'font-weight:800;border-radius:12px;padding:5px 12px;'
            + ('color:#0a8f5c;background:rgba(10,169,106,.10);border:1px solid rgba(10,169,106,.28);'
               if running else
               'color:#d64545;background:#fff5f5;border:1px solid rgba(214,69,69,.30);'))
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.v_http_l.setText(str(self.ctx.config.port))
        self.v_ws_l.setText(str(self.ctx.config.ws_port))
        svc = self.ctx.service
        self.v_online_l.setText(str(len(svc.conns)))
        self.v_rooms_l.setText('%d / %d' % (len(svc.rooms), svc.match_count()))
        self.v_uptime_l.setText(_fmt_uptime(self.ctx.uptime_ms()))
        self.v_players_l.setText(str(svc.player_count()))
        self._refresh_lan()
        self._refresh_rooms()
        self._refresh_conns()
        self._refresh_users()

    def _refresh_lan(self) -> None:
        """刷新局域网地址列表（含 HTTP 与 WS 各一条复制按钮）。"""
        while self.lan_box.count():
            item = self.lan_box.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        port = self.ctx.config.port
        ws = self.ctx.config.ws_port
        addrs = ['127.0.0.1']
        try:
            for a in QNetworkInterface.allAddresses():
                if a.isLoopback():
                    continue
                s = a.toString()
                if a.protocol() == QHostAddress.Protocol.IPv4Protocol and s not in addrs:
                    addrs.append(s)
        except Exception:
            pass
        for a in addrs[:6]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            lab = QLabel('http://%s:%d' % (a, port))
            lab.setObjectName('Strong')
            h.addWidget(lab)
            sub = QLabel('WS %d' % ws)
            sub.setObjectName('Muted')
            h.addWidget(sub)
            h.addStretch(1)
            b = QPushButton('复制')
            b.setFixedWidth(64)
            b.setIcon(icons.make_icon('clipboard', '#3a4a66', 14))
            b.clicked.connect(lambda _, t='http://%s:%d' % (a, port): (
                QGuiApplication.clipboard().setText(t),
                self.ctx.logbus.push('已复制地址：' + t, 'ok')))
            h.addWidget(b)
            self.lan_box.addWidget(row)

    def _refresh_rooms(self) -> None:
        """刷新房间表。"""
        rooms = list(self.ctx.service.rooms.values())
        self.tbl_rooms.clearSpans()
        self.tbl_rooms.setRowCount(len(rooms))
        for i, r in enumerate(rooms):
            info = r.public_info()
            phase = '对战中' if r.state == 'playing' else ('结算中' if r.state == 'over' else '等待中')
            vals = [info['code'], info['host'], '%d/%d' % (info['count'], info['max']),
                    str(len(r.spectators)), info['mapName'], info['diffName'], phase]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 0:
                    it.setFont(_mono_font())
                self.tbl_rooms.setItem(i, j, it)
        if not rooms:
            self.tbl_rooms.setRowCount(1)
            it = QTableWidgetItem('暂无房间')
            it.setForeground(Qt.GlobalColor.gray)
            self.tbl_rooms.setItem(0, 0, it)
            self.tbl_rooms.setSpan(0, 0, 1, 7)

    def _refresh_conns(self) -> None:
        """刷新连接表。"""
        conns = [c for c in self.ctx.service.conns if not getattr(c, 'closed', False)]
        self.tbl_conns.clearSpans()
        self.tbl_conns.setRowCount(len(conns))
        for i, c in enumerate(conns):
            vals = ['#%d' % c.id, c.ip, c.name or '-', c.role or '-',
                    c.room.code if getattr(c, 'room', None) else '-']
            for j, v in enumerate(vals):
                self.tbl_conns.setItem(i, j, QTableWidgetItem(str(v)))
        if not conns:
            self.tbl_conns.setRowCount(1)
            it = QTableWidgetItem('暂无连接')
            it.setForeground(Qt.GlobalColor.gray)
            self.tbl_conns.setItem(0, 0, it)
            self.tbl_conns.setSpan(0, 0, 1, 5)

    def _refresh_users(self) -> None:
        """刷新用户与 IP 备注表（保留正在编辑的单元格）。"""
        self._note_guard = True
        try:
            players = self.ctx.service.leaderboard.top(200)
            self.tbl_users.clearSpans()
            self.tbl_users.setRowCount(len(players))
            for i, p in enumerate(players):
                ip = str(p.get('ip') or '')
                note = self.ctx.ip_notes.get(ip) if ip else ''
                vals = [str(p.get('name') or '-'), ip or '-', str(p.get('soloBest') or 0),
                        str(p.get('mpGames') or 0), str(p.get('wins') or 0), str(p.get('score') or 0)]
                for j, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if j >= 2:
                        it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.tbl_users.setItem(i, j, it)
                it_note = QTableWidgetItem(note)
                it_note.setData(Qt.ItemDataRole.UserRole, ip)
                self.tbl_users.setItem(i, 6, it_note)
            if not players:
                self.tbl_users.setRowCount(1)
                it = QTableWidgetItem('暂无用户数据（玩家提交成绩后会出现在这里）')
                it.setForeground(Qt.GlobalColor.gray)
                self.tbl_users.setItem(0, 0, it)
                self.tbl_users.setSpan(0, 0, 1, 7)
        finally:
            self._note_guard = False

    def _on_note_changed(self, item: QTableWidgetItem) -> None:
        """备注单元格修改后写入存储。"""
        if self._note_guard or item.column() != 6:
            return
        ip = str(item.data(Qt.ItemDataRole.UserRole) or '')
        if not ip:
            return
        ok = self.ctx.ip_notes.set(ip, item.text().strip())
        self.ctx.logbus.push(('已保存 IP 备注：%s' % ip) if ok else 'IP 备注保存失败', 'ok' if ok else 'warn')

    # ---------------------------------------------------------------- 托盘
    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭窗口时隐藏到托盘（真正退出由托盘菜单触发）。"""
        if getattr(self.ctx, 'tray_available', False):
            event.ignore()
            self.hide()
            self.ctx.logbus.push('窗口已隐藏到系统托盘，右键托盘图标可继续操作', 'info')
        else:
            event.accept()

    def quit_app(self) -> None:
        """真正退出程序：停止服务并退出事件循环。"""
        self.ctx.stop_services()
        if getattr(self.ctx, 'tray', None) is not None:
            self.ctx.tray.hide()
        QTimer.singleShot(120, self._real_quit)

    def _real_quit(self) -> None:
        """结束 QApplication。"""
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()


def _escape(text: str) -> str:
    """转义 HTML 特殊字符。"""
    return (str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _mono_font():
    """等宽字体（房间码用）。"""
    from PyQt6.QtGui import QFont
    f = QFont('Consolas')
    f.setBold(True)
    return f


def _fmt_uptime(ms: int) -> str:
    """把毫秒格式化为「x时y分z秒」。"""
    if not ms:
        return '—'
    s = int(ms / 1000)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return ('%d时' % h if h else '') + '%d分%d秒' % (m, sec)
