"""客户端主窗口：QWebEngineView 加载内置页面（页面由本机回环 HTTP 托管）。"""
from __future__ import annotations

import os

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from client.config import app_data_dir
from client.updater import check_update
from shared.qt_icons import make_icon
from shared.version import APP_VERSION


class ClientWindow(QMainWindow):
    """游戏客户端窗口。"""

    def __init__(self, ctx):
        """初始化窗口与浏览器控件。

        Args:
            ctx: 应用上下文（含 bridge/page_url/config/tray 等）。
        """
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle('Play With Snake')
        self.setWindowIcon(make_icon('snake', '#0aa96a', 32))
        self.resize(1080, 760)
        self.setMinimumSize(900, 620)

        web_data = os.path.join(app_data_dir(), 'web')
        cache_dir = os.path.join(app_data_dir(), 'webcache')
        os.makedirs(web_data, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        profile = QWebEngineProfile('PlayWithSnake', self)
        profile.setPersistentStoragePath(web_data)
        profile.setCachePath(cache_dir)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

        page = QWebEnginePage(profile, self)
        channel = QWebChannel(page)
        channel.registerObject('snake', ctx.bridge)
        page.setWebChannel(channel)
        self._channel = channel          # 保持引用，避免被回收

        view = QWebEngineView(self)
        view.setPage(page)
        self.setCentralWidget(view)
        self.view = view
        view.load(QUrl(ctx.page_url))

        geo = ctx.config.geometry
        if geo:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    # ---------------------------------------------------------------- 行为
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
                    APP_VERSION, r.get('latest'), r.get('notes') or '（暂无更新说明）', r.get('url') or '（暂无）'))
        else:
            QMessageBox.information(self, '检查更新', '已是最新版本 v%s。' % APP_VERSION)
