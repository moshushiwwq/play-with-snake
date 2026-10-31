"""QWebChannel 桥：把联机、HTTP、地图、日志与系统能力暴露给页面 JS。

页面通过 `new QWebChannel(...).objects.snake` 调用；所有返回值都是 JSON 字符串，
便于 JS 统一解析。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

from client.config import app_data_dir
from client.storage import ClientStorage


class SnakeBridge(QObject):
    """页面与 Python 后端之间的桥接对象（注册名 "snake"）。"""

    connectionState = pyqtSignal(str, str)
    serverMessage = pyqtSignal(str)

    def __init__(self, net, storage: ClientStorage, config, parent=None):
        """初始化桥接。

        Args:
            net: NetClient。
            storage: ClientStorage。
            config: ClientConfig。
            parent: 父对象。
        """
        super().__init__(parent)
        self.net = net
        self.storage = storage
        self.config = config
        self.last_host = config.last_server
        self.http_port = 8080
        net.stateChanged.connect(self._on_state)
        net.messageReceived.connect(self.serverMessage.emit)

    # ---------------------------------------------------------------- 内部
    def _on_state(self, state: str, host: str) -> None:
        """转发连接状态，并在连接成功后记住地址。"""
        if state == 'connected' and host:
            self.last_host = host
            self.config.set_last_server(host)
        self.connectionState.emit(state, host)

    def _http_base(self) -> str:
        """根据最近连接的服务器推导 HTTP 基地址（端口由服务器 hello 下发）。"""
        host = (self.last_host or '').split(':')[0] or '127.0.0.1'
        return 'http://' + host + ':' + str(self.http_port or 8080)

    def _http(self, path: str, body: dict | None = None, timeout: int = 8) -> str:
        """发起一次 HTTP 请求并返回 JSON 文本。

        Args:
            path: 以 / 开头的接口路径。
            body: POST 数据（None 表示 GET）。
            timeout: 超时秒数。

        Returns:
            JSON 文本；失败时返回 {"ok": false, "msg": "..."}。
        """
        url = self._http_base() + path
        try:
            data = None
            headers = {}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode('utf-8')
                headers['Content-Type'] = 'application/json'
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            try:
                return e.read().decode('utf-8', 'replace')
            except Exception:
                return json.dumps({'ok': False, 'msg': 'HTTP %d' % e.code})
        except Exception as e:
            return json.dumps({'ok': False, 'msg': '无法连接服务器：%s' % e})

    # ---------------------------------------------------------------- 网络
    @pyqtSlot(int)
    def setHttpPort(self, port: int) -> None:
        """由页面在收到 hello 后告知服务器 HTTP 端口。"""
        try:
            p = int(port)
        except Exception:
            return
        if 1 <= p <= 65535:
            self.http_port = p

    @pyqtSlot(str, result=str)
    def connectServer(self, host: str) -> str:
        """连接联机服务器。"""
        r = self.net.connect_to(host)
        r['autoReconnect'] = bool(getattr(self.net, 'auto_reconnect', True))
        return json.dumps(r, ensure_ascii=False)

    @pyqtSlot()
    def disconnectServer(self) -> None:
        """断开联机服务器。"""
        self.net.disconnect()

    @pyqtSlot(str)
    def sendMessage(self, text: str) -> None:
        """把页面消息发送到服务器。"""
        self.net.send(text)

    # ---------------------------------------------------------------- HTTP
    @pyqtSlot(str, result=str)
    def httpGet(self, path: str) -> str:
        """GET 一个服务器接口（相对路径）。"""
        return self._http(path)

    @pyqtSlot(str, str, result=str)
    def httpPost(self, path: str, body: str) -> str:
        """POST 一个服务器接口（body 为 JSON 文本）。"""
        try:
            obj = json.loads(body) if body else {}
        except Exception:
            obj = {}
        return self._http(path, obj)

    @pyqtSlot(str, result=str)
    def uploadMap(self, map_json: str) -> str:
        """上传自制地图到服务器。"""
        try:
            obj = json.loads(map_json)
        except Exception:
            return json.dumps({'ok': False, 'msg': '地图数据格式错误'}, ensure_ascii=False)
        return self._http('/api/map', obj)

    # ---------------------------------------------------------------- 存储
    @pyqtSlot(str, result=str)
    def saveLog(self, entry_json: str) -> str:
        """写入一条操作日志。"""
        try:
            e = json.loads(entry_json)
        except Exception:
            e = {}
        ok = self.storage.save_log(e.get('kind') or 'unknown', e.get('detail') or '', e.get('ts'))
        return json.dumps({'ok': bool(ok)}, ensure_ascii=False)

    @pyqtSlot(str, result=str)
    def saveMaps(self, list_json: str) -> str:
        """整体保存自制地图库。"""
        try:
            maps = json.loads(list_json)
        except Exception:
            maps = []
        ok = self.storage.save_maps(maps if isinstance(maps, list) else [])
        return json.dumps({'ok': bool(ok), 'count': len(maps) if isinstance(maps, list) else 0},
                          ensure_ascii=False)

    @pyqtSlot(result=str)
    def listMaps(self) -> str:
        """读取自制地图库。"""
        return json.dumps(self.storage.list_maps(), ensure_ascii=False)

    @pyqtSlot(result=str)
    def getInfo(self) -> str:
        """返回客户端信息（版本、数据目录等）。"""
        from shared.version import APP_VERSION
        return json.dumps({
            'ok': True, 'mode': 'qt', 'version': APP_VERSION,
            'dataDir': app_data_dir(), 'platform': 'windows',
        }, ensure_ascii=False)

    @pyqtSlot()
    def openDataDir(self) -> None:
        """在资源管理器中打开客户端数据目录。"""
        try:
            os.startfile(app_data_dir())  # type: ignore[attr-defined]
        except Exception:
            pass

    @pyqtSlot()
    def exportLogs(self) -> None:
        """导出操作日志为 JSON 文件（弹出保存对话框）。"""
        name = 'snake-oplogs-%s.json' % time.strftime('%Y%m%d-%H%M%S')
        path, _ = QFileDialog.getSaveFileName(None, '导出操作日志', name, 'JSON 文件 (*.json)')
        if path:
            self.storage.export_logs(path)

    @pyqtSlot(bool)
    def setAutoReconnect(self, on: bool) -> None:
        """开/关断线自动重连。"""
        self.net.auto_reconnect = bool(on)
