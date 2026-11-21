"""客户端主窗口：仅展示运行日志（游戏交互全部在外部浏览器网页中完成）。"""
from __future__ import annotations

import time

from PyQt6.QtGui import QIcon, QTextCharFormat, QColor, QTextCursor
from PyQt6.QtWidgets import QMainWindow, QPlainTextEdit, QMessageBox

from client.config import app_data_dir
from client.updater import check_update
from shared.qt_icons import make_icon
from shared.version import APP_VERSION

_LEVEL_COLORS = {
    'info': '#3a4a66',
    'ok': '#0aa96a',
    'warn': '#d99b00',
    'error': '#d64545',
}


class ClientWindow(QMainWindow):
    """日志窗口（不含内嵌网页控件）。"""

    def __init__(self, ctx):
        """初始化日志窗口。

        Args:
            ctx: 应用上下文（含 config/tray 等）。
        """
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle('Play With Snake · 运行日志')
        self.setWindowIcon(make_icon('snake', '#0aa96a', 32))
        self.resize(760, 520)
        self.setMinimumSize(560, 360)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setPlaceholderText('客户端运行日志将显示在这里；游戏界面请在浏览器中操作。')
        self.setCentralWidget(self.view)

        geo = ctx.config.geometry
        if geo:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ---------------------------------------------------------------- 行为
    def append_log(self, text: str, level: str = 'info') -> None:
        """追加一条日志（线程安全由 Qt 信号保证，这里直接在主线程调用）。

        Args:
            text: 日志文本。
            level: info/ok/warn/error。
        """
        ts = time.strftime('%H:%M:%S')
        color = QColor(_LEVEL_COLORS.get(level, _LEVEL_COLORS['info']))
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        cursor.setCharFormat(fmt)
        cursor.insertText('[%s] %s\n' % (ts, text))
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def closeEvent(self, event) -> None:  # noqa: N802
        """关闭窗口时按设置隐藏到托盘，真正退出由托盘菜单触发。"""
        try:
            self.ctx.config.set_geometry(self.saveGeometry())
        except Exception:
            pass
        if self.ctx.tray is not None and self.ctx.config.minimize_to_tray:
            event.ignore()
            self.hide()
            self.ctx.tray.notify('仍在后台运行', '窗口已隐藏到系统托盘，右键托盘图标可重新打开。')
            return
        event.accept()

    def quit_app(self) -> None:
        """真正退出客户端。"""
        try:
            self.ctx.config.set_geometry(self.saveGeometry())
        except Exception:
            pass
        if self.ctx.tray is not None:
            self.ctx.tray.hide()
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def show_and_raise(self) -> None:
        """显示并激活窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_check_update(self) -> None:
        """检查更新并给出提示。"""
        r = check_update()
        if not r.get('ok'):
            QMessageBox.information(self, '检查更新', r.get('msg') or '暂时无法检查更新')
            return
        if r.get('hasUpdate'):
            QMessageBox.information(
                self, '发现新版本',
                '当前版本 v%s，最新版本 %s。\n\n%s\n\n下载地址：%s' % (
                    APP_VERSION, r.get('latest'), r.get('notes') or '（暂无更新）', r.get('url') or '（暂无）'))
        else:
            QMessageBox.information(self, '检查更新', '已是最新版本 v%s。' % APP_VERSION)
