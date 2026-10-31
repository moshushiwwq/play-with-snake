"""Windows 开机/登录自启动与防火墙放行。

策略（与原 Node 版一致，并修正权限异常的表现）：
    1. 先清理旧的计划任务与启动文件夹快捷方式；
    2. boot 模式需要管理员：注册 onstart 计划任务（SYSTEM / 最高权限）；
    3. 非管理员时自动降级为 onlogon 计划任务；
    4. 计划任务失败则回退到「启动文件夹 .lnk」（用户级，无需管理员）；
    5. 任何一步失败都返回中文原因，不抛异常。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys

TASK_NAME = 'PlayWithSnakeServer'
FIREWALL_RULE = 'PlayWithSnake Server'


def is_admin() -> bool:
    """当前进程是否具有管理员权限。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run(args: list[str], timeout: int = 20) -> tuple[bool, str]:
    """执行命令并返回是否成功与输出。

    Args:
        args: 命令参数。
        timeout: 超时秒数。

    Returns:
        (是否成功, 输出文本)。
    """
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding='utf-8', errors='replace',
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ok = p.returncode == 0
        return ok, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return False, str(e)


def _startup_lnk() -> str:
    """启动文件夹快捷方式路径。"""
    base = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows',
                        'Start Menu', 'Programs', 'Startup')
    return os.path.join(base, TASK_NAME + '.lnk')


def _self_command() -> str:
    """自启动时要执行的命令行（源码运行与 exe 运行都适用）。"""
    if getattr(sys, 'frozen', False):
        return '"%s" --tray' % sys.executable
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'server', 'main.py')
    return '"%s" "%s" --tray' % (sys.executable, main_py)


def _create_shortcut() -> tuple[bool, str]:
    """在启动文件夹创建快捷方式（无需管理员）。"""
    lnk = _startup_lnk()
    target = sys.executable
    args = '--tray' if getattr(sys, 'frozen', False) else '"%s" --tray' % os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'server', 'main.py')
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        "$s = $ws.CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.WindowStyle = 7;"
        "$s.Save()"
    ) % (lnk.replace("'", "''"), target.replace("'", "''"), args.replace("'", "''"),
         os.path.dirname(target).replace("'", "''"))
    ok, out = _run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], 30)
    if ok and os.path.exists(lnk):
        return True, '已创建启动文件夹快捷方式'
    return False, '创建快捷方式失败：' + (out.strip()[:120] or '未知错误')


def _remove_shortcut() -> None:
    """删除启动文件夹快捷方式。"""
    try:
        if os.path.exists(_startup_lnk()):
            os.remove(_startup_lnk())
    except Exception:
        pass


def query() -> str:
    """查询当前自启动形态。

    Returns:
        'boot' / 'logon' / 'none'。
    """
    if not sys.platform.startswith('win'):
        return 'none'
    ok_boot, _ = _run(['schtasks', '/query', '/tn', TASK_NAME + '-Boot'])
    if ok_boot:
        return 'boot'
    ok_logon, _ = _run(['schtasks', '/query', '/tn', TASK_NAME])
    if ok_logon:
        return 'logon'
    if os.path.exists(_startup_lnk()):
        return 'logon'
    return 'none'


def firewall(enable: bool = True, ports: tuple[int, ...] = (8080, 8081)) -> tuple[bool, str]:
    """放行/移除防火墙入站规则（TCP 端口 + UDP 41999）。

    Args:
        enable: True 添加规则，False 删除规则。
        ports: 需要放行的 TCP 端口。

    Returns:
        (是否成功, 提示信息)。
    """
    if not sys.platform.startswith('win'):
        return False, '仅支持 Windows'
    if not is_admin():
        return False, '防火墙放行需要管理员权限，已跳过（可右键以管理员身份运行）'
    port_str = ','.join(str(p) for p in ports)
    if enable:
        _run(['netsh', 'advfirewall', 'firewall', 'add', 'rule', 'name=' + FIREWALL_RULE,
              'dir=in', 'action=allow', 'protocol=TCP', 'localport=' + port_str], 30)
        _run(['netsh', 'advfirewall', 'firewall', 'add', 'rule', 'name=' + FIREWALL_RULE + ' UDP',
              'dir=in', 'action=allow', 'protocol=UDP', 'localport=41999'], 30)
        return True, '已放行防火墙端口 ' + port_str + ' 与 UDP 41999'
    _run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', 'name=' + FIREWALL_RULE], 30)
    _run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', 'name=' + FIREWALL_RULE + ' UDP'], 30)
    return True, '已移除防火墙规则'


def apply(mode: str) -> tuple[bool, str]:
    """设置自启动方式。

    Args:
        mode: 'none' / 'logon' / 'boot'。

    Returns:
        (是否成功, 提示信息)。
    """
    if not sys.platform.startswith('win'):
        return False, '该功能仅支持 Windows'
    # 清理旧形态
    _run(['schtasks', '/end', '/tn', TASK_NAME + '-Boot'])
    _run(['schtasks', '/delete', '/tn', TASK_NAME + '-Boot', '/f'])
    _run(['schtasks', '/end', '/tn', TASK_NAME])
    _run(['schtasks', '/delete', '/tn', TASK_NAME, '/f'])
    _remove_shortcut()
    if mode == 'none':
        return True, '已关闭开机/登录自启动'

    admin = is_admin()
    if mode == 'boot' and admin:
        ok, out = _run(['schtasks', '/create', '/tn', TASK_NAME + '-Boot', '/tr', _self_command(),
                        '/sc', 'onstart', '/ru', 'SYSTEM', '/rl', 'HIGHEST', '/f'], 30)
        if ok:
            fw_ok, fw_msg = firewall(True)
            return True, '已设置开机自启（无需登录）；' + fw_msg
        return False, '创建开机自启任务失败：' + out.strip()[:120]

    degrade = '开机自启需要管理员权限，已自动降级为「登录后自动启动」。' if mode == 'boot' else ''
    ok, out = _run(['schtasks', '/create', '/tn', TASK_NAME, '/tr', _self_command(), '/sc', 'onlogon', '/f'], 30)
    if ok:
        fw_msg = firewall(True)[1] if admin else '防火墙放行需管理员，已跳过'
        return True, degrade + '已设置登录后自动启动；' + fw_msg
    sc_ok, sc_msg = _create_shortcut()
    if sc_ok:
        fw_msg = firewall(True)[1] if admin else '防火墙放行需管理员，已跳过'
        return True, degrade + sc_msg + '；' + fw_msg
    return False, degrade + '创建计划任务失败：' + out.strip()[:100] + '；' + sc_msg


def open_data_folder(path: str) -> tuple[bool, str]:
    """在资源管理器中打开数据目录。

    Args:
        path: 目录路径。

    Returns:
        (是否成功, 提示信息)。
    """
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True, '已打开目录'
    except Exception as e:
        return False, '打开目录失败：%s' % e
