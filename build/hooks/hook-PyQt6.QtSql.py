"""PyInstaller 自定义钩子：只保留 QtSql 的 SQLite 驱动。

PyInstaller 默认会收集 PyQt6 自带的全部 sqldrivers（OCI、PostgreSQL、
Firebird、Mimer 等）。这些驱动依赖本机未安装的第三方客户端 DLL，会在
打包日志中产生「Library not found」告警。本项目只用 SQLite，因此在
钩子阶段直接过滤，既消除告警也减小产物体积。
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)


def _keep(entry):
    """判断打包条目是否保留（sqldrivers 目录下只保留 qsqlite）。

    Args:
        entry: PyInstaller TOC 条目 (name, path, type)。

    Returns:
        保留返回 True。
    """
    name = str(entry[0]).replace('\\', '/').lower()
    if 'sqldrivers' not in name:
        return True
    return 'qsqlite' in name


binaries = [x for x in binaries if _keep(x)]
datas = [x for x in datas if _keep(x)]
