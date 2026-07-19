# -*- coding: utf-8 -*-
"""
LockDevice · 专注锁定
====================
一个帮你「管住自己」的桌面工具：设定时长后锁定电脑防止分心。

两种锁定方式（在设置中选择、手动保存）：
  ① 全屏锁定（软）：全屏铁幕盖住屏幕 + 拦截逃逸热键，倒计时结束自动解锁。
       屏幕上只有：当前时钟、倒计时、一个「关机」按钮。可选「双进程互守」防结束进程。
  ② 定时关机（硬）：注册计划任务，立即关机，且设定时间内每次开机即关（SYSTEM 身份），
       到点自动解除。几乎不给使用/退出的机会。

安装 / 便携：
  - 绿色运行：免安装直接用；模式一锁定期间临时登录自启恢复，结束后自动清理。
  - 安装到本机：一次管理员授权，创建「最高权限」计划任务 —— 打开与定时关机此后免 UAC；
       模式一锁定期间「智能开机自启」恢复，空闲时段不自启。
  - 卸载工具 / 清除数据：随时移除。

界面用 customtkinter（需 `pip install customtkinter`）；核心逻辑与后台守护为标准库，缺 ctk 也能运行。
    python lock_device.py
"""

import os
import sys
import json
import time
import shutil
import getpass
import threading
import subprocess
import traceback
import importlib.util
import types
import tkinter as tk
from tkinter import messagebox

try:
    import customtkinter as ctk
    HAS_CTK = True
except Exception:
    ctk = None
    HAS_CTK = False

if sys.platform != "win32":
    raise SystemExit("此程序仅支持 Windows。")

import ctypes
import winreg
from ctypes import wintypes

# --dry-run 或 环境变量 LOCKDEVICE_DRYRUN=1：只打印不真正关机/建任务/落文件，便于测试
DRY_RUN = (os.environ.get("LOCKDEVICE_DRYRUN") == "1") or ("--dry-run" in sys.argv)

# 高 DPI 更清晰（失败不影响功能）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# 让任务栏用本程序图标而非 pythonw 图标
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LockDevice.FocusLock")
except Exception:
    pass

# ------------------------------------------------------------------ 常量 / 路径
CREATE_NO_WINDOW = 0x08000000
SHUTDOWN_DELAY = 25  # 立即关机前留给保存文件的秒数
VERSION = "1.5.0"    # 版本号（发布新版前在这里递增；更新识别靠它）
# 更新日志：版本号 -> 该版本更新条目（列表）。发布新版时在这里加一条（键 = 新版本号）；
# 「发现新版本」窗会展示「已安装版本 < v <= 当前版本」区间内所有条目（最新在前）。
CHANGELOG = {
    "1.5.0": [
        "界面重构：新增 PySide6 + qfluentwidgets 的 Fluent 现代界面（gui/ 文件夹）；本体自动识别——有 gui/ 且装了 Qt 库就用 Qt，否则回退经典 tkinter。功能对齐：专注锁定 / 插件 / 插件管理 / 安装卸载 / 更新",
        "打包：一次产出 4 个变体——tk 无插件（最小）/ tk 全插件 / qt 全插件 / qt 无插件；发布页可按需下载",
        "修复：从 Qt / 计划任务 / 自启拉起的一次性锁定（--startlock），锁定结束后进程直接退出，不再多弹一个 tkinter 主界面",
    ],
    "1.4.2": [
        "插件系统：支持启用/关闭各插件（关闭的插件不加载运行、不占按钮、开机也不唤醒）；配置存 plugins_disabled",
    ],
    "1.4.1": [
        "修复：自动锁机改为「每日时间窗口」——不再用定时任务在固定点直接触发固定时长的锁定；改由插件在每次登录时自己检查：在窗口内就锁「剩余时间」（迟到开机只锁剩下的），过点开机则不锁（该插件因此改为需要开机自启）",
    ],
    "1.4.0": [
        "插件系统：新增 plugins/ 目录，自动识别并加入插件（打包默认包含所有插件）；主页每个插件一个按钮 + 统一「⚙ 设置」页（与本体共用 config.json、按插件分区）；本体暴露锁机等函数供插件调用，插件与本体分离、独立演进",
        "界面：启动器主按钮更名为「🎯 专注锁定」（绿色运行 / 已安装打开 两处）",
        "首个插件 自动锁机 v1.0.0（最小版）：设定每天固定时间自动锁机一段时长（DailyTrigger 计划任务，复用模式一全屏锁定；后续支持节假日/按周/按月）",
    ],
    "1.3.0": [
        "模式二（定时关机）新增「⚡ 开始后立即关机」附加开关：不留 25 秒缓冲、开始即关，防止在倒计时窗口内清除数据逃脱（可与登录前/后自由组合）",
        "模式一锁屏新增「🌙 息屏」按钮：仅熄灭显示器防烧屏（不锁屏），点击后延迟 1 秒再息屏、避免点击瞬间又亮屏",
    ],
    "1.2.3": [
        "修复：「发现更新」窗更新日志排版——每行右侧不再被裁掉、行首圆点不再单独占一行（改为圆点独立列 + 正文按实际宽度换行、续行挂起缩进）",
    ],
    "1.2.2": [
        "修复：在已安装机器上运行新版文件时，「发现更新」窗与已安装版启动器改为『同时弹出』，不再需要先关掉更新窗启动器才出现",
    ],
    "1.2.1": [
        "界面：附加选项（模式一/二的复选框）置灰时，勾选框本身（边框/填充）也一起变灰，不再只有文字变灰",
    ],
    "1.2.0": [
        "模式二（定时关机）新增「🛡 加强防护：登录前关机」开关（与模式一附加开关一致）：默认关=登录后关机（当前用户 + LeastPrivilege 登录任务，标准用户免 UAC 即可创建）；勾选=登录前关机（BootTrigger + SYSTEM，绿色模式弹一次 UAC），开机即关、拦截更硬",
        "安全：模式二「登录前」在绿色模式下也把 exe 暂存到 ACL 受保护缓存再让 SYSTEM 任务指向它（此前绿色 SYSTEM 关机任务指向用户可写 exe，存在重启后被换 exe 提权的隐患）；「登录后」以当前用户身份运行、换 exe 也提不了权，无需受保护副本",
        "模式二「登录前」绿色模式提权改为一步直达（--startshutdown，提权后直接创建关机计划）",
        "两档关机任务都带 EndBoundary + DeleteExpiredTaskAfter，到点自动失效删除（登录后档改用计划任务、不再依赖 HKCU\\Run，保留系统级自动过期这道保险）",
    ],
    "1.1.1": [
        "修复：运行新版文件时「发现更新」窗与已安装版启动器两窗叠加、且已安装版在后台/最小化——改为先弹更新窗，选「稍后/跳过」后再免 UAC 打开已安装版（单窗切换）并强制到最前台",
        "安全：绿色模式勾禁用任务管理器时，开机恢复任务改指向系统级临时目录里的 ACL 受保护副本（病毒改不动/删不动），而非用户可写目录里的绿色 exe；解锁自动删除",
        "安全：开机恢复 / 定时关机等触发型任务禁用「按需触发」（仅登录/开机自动触发，不影响重启后自动解禁任务管理器），去掉可被 schtasks /run 免 UAC 触发的一条腿",
        "清除数据遇到上了 ACL 锁的受保护缓存会自动提权后删除",
    ],
    "1.1.0": [
        "默认安装到 %ProgramFiles%\\LockDevice（仅管理员可写）；自定义路径也自动上 ACL 锁，防病毒篡改被提权任务运行的程序",
        "已安装机器上运行新版文件：免 UAC 打开已安装版 + 单独弹「发现更新」窗（含更新日志），不点更新则全程零 UAC",
        "「发现更新」窗支持「跳过此版本」，跳过后同版本不再提示（出现更高版本仍会提示）",
        "更新时自动结束占用的旧实例再覆盖，无需手动先关闭",
        "安全加固：提权重生改用当前运行本体路径，不再信任用户可写的 installed.flag",
    ],
    "1.0.0": [
        "首个正式版本：全屏锁定（软）/ 定时关机（硬）两种锁定方式",
        "进程守护（分离进程树，防结束任务）、可禁用任务管理器",
        "安装到本机（免 UAC / 智能开机自启 / 定时关机）、绿色运行、卸载、原地更新",
    ],
}

SYSROOT = os.environ.get("SystemRoot", r"C:\Windows")
SHUTDOWN_EXE = os.path.join(SYSROOT, "System32", "shutdown.exe")

LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
PROGRAM_FILES = os.environ.get("ProgramFiles") or r"C:\Program Files"
ROOT_DIR = os.path.join(LOCALAPPDATA, "LockDevice")   # 数据/配置（固定不动）
# 默认安装到 Program Files（仅管理员可写）；用户可改路径，安装时对目录上 ACL 锁保护
APP_DIR = os.path.join(PROGRAM_FILES, "LockDevice")
INSTALL_FLAG = os.path.join(ROOT_DIR, "installed.flag")   # 内容 = 实际安装目录
PORTABLE_DIR = os.path.join(ROOT_DIR, "portable")
# 绿色模式+提权（勾禁用任务管理器）时，开机恢复任务指向的「受保护副本」目录：
# 用系统级临时目录 —— 管理员建的子目录非管理员改不动/删不动，解锁即删；崩溃残留也只是 Temp 项
GREEN_CACHE_DIR = os.path.join(SYSROOT, "Temp", "LockDevice")

TASK_SHUTDOWN = "LockDevice_Shutdown"   # 定时关机守护
TASK_BOOT = "LockDevice_Boot"           # 开机自启（仅锁定期间存在，恢复锁定）
TASK_PLUGIN_BOOT = "LockDevice_PluginBoot"  # 插件开机自启（仅当有插件声明需要时才存在）
TASK_OPEN = "LockDevice_Open"           # 按需打开界面（提权免 UAC）
TASK_UNINSTALL = "LockDevice_Uninstall" # 按需卸载（提权免 UAC）

DEFAULT_CONFIG = {"mode": 1, "minutes": 30, "lock_until": None, "guard": True,
                  "block_taskmgr": False, "mode2_preboot": False, "mode2_instant": False,
                  "shortcuts": [], "skip_version": None,
                  "plugins": {}, "plugins_autostart": [], "plugins_disabled": []}

# 界面配色
FONT = "Microsoft YaHei"
COL_GREEN = "#2fa572"
COL_BLUE = "#3b7dd8"
COL_RED = "#c0392b"
COL_ORANGE = "#e67e22"
COL_GRAY = "#565b5e"


# ------------------------------------------------------------------ 通用工具
def _run(args):
    """隐藏控制台执行命令，返回 CompletedProcess。"""
    return subprocess.run(args, capture_output=True, text=True,
                          creationflags=CREATE_NO_WINDOW)


def _hide_console():
    """若本进程独占控制台（python.exe 双击/提权启动），隐藏黑框；从终端共享启动则不动。"""
    try:
        k = ctypes.windll.kernel32
        hwnd = k.GetConsoleWindow()
        if not hwnd:
            return
        arr = (ctypes.c_uint * 4)()
        if k.GetConsoleProcessList(arr, 4) <= 1:   # 仅本进程占用该控制台才隐藏
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _self_path():
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)


def _pythonw_path():
    """返回无控制台窗口的 pythonw.exe（找不到就用当前解释器）。"""
    exe = sys.executable
    if os.path.basename(exe).lower() == "python.exe":
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand):
            return cand
    return exe


def _icon_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(_self_path())
    p = os.path.join(base, "lock_device.ico")
    return p if os.path.exists(p) else None


def _set_icon(window):
    """给窗口设置 .ico 图标（ctk 初始化会覆盖图标，故延迟再设一次）。"""
    p = _icon_path()
    if not p:
        return

    def apply():
        try:
            window.iconbitmap(p)
        except Exception:
            pass
    apply()
    try:
        window.after(300, apply)
    except Exception:
        pass


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args=""):
    """以管理员身份重新启动本程序（弹一次 UAC）。成功返回 True。"""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, extra_args
    else:
        exe, params = _pythonw_path(), f'"{_self_path()}" {extra_args}'.strip()
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return rc > 32
    except Exception:
        return False


def current_user_id():
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def _fmt_local(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def _log(msg):
    """把诊断/错误写到 %LOCALAPPDATA%\\LockDevice\\error.log（尽力而为，超过 64KB 自动重置）。"""
    try:
        os.makedirs(ROOT_DIR, exist_ok=True)
        path = os.path.join(ROOT_DIR, "error.log")
        try:
            if os.path.getsize(path) > 64 * 1024:
                os.remove(path)
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def _dialog(title, text, kind="info"):
    """在无主窗口场景下弹个消息框（用于 --install / --uninstall / 缺依赖 等）。"""
    r = tk.Tk()
    r.withdraw()
    {"info": messagebox.showinfo, "error": messagebox.showerror,
     "warn": messagebox.showwarning}[kind](title, text)
    r.destroy()


# ------------------------------------------------------------------ 配置持久化
def is_installed():
    return os.path.exists(INSTALL_FLAG)


def data_dir():
    return ROOT_DIR if is_installed() else PORTABLE_DIR


def config_path():
    return os.path.join(data_dir(), "config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in DEFAULT_CONFIG:
            if k in data:
                cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ------------------------------------------------------------------ 计划任务
def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _main_name():
    return "LockDevice.exe" if getattr(sys, "frozen", False) else "lock_device.py"


def installed_dir():
    """已安装时程序文件所在目录（安装标记文件里记录）；未安装返回 None。"""
    try:
        with open(INSTALL_FLAG, "r", encoding="utf-8") as f:
            d = f.read().strip()
    except OSError:
        return None
    if d and os.path.isdir(d):
        return d
    return APP_DIR if os.path.isdir(APP_DIR) else None   # 兼容旧标记（内容非路径）


def installed_main():
    d = installed_dir()
    return os.path.join(d, _main_name()) if d else None


def _version_file():
    return os.path.join(ROOT_DIR, "version.txt")


def installed_version():
    try:
        with open(_version_file(), "r", encoding="utf-8") as f:
            return f.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _ver_tuple(s):
    try:
        return tuple(int(x) for x in str(s).split("."))
    except (ValueError, AttributeError):
        return (0,)


def has_update():
    """当前运行版本高于已安装版本 → 可原地更新。"""
    return is_installed() and _ver_tuple(VERSION) > _ver_tuple(installed_version())


def changelog_since(old_version):
    """比 old_version 更新（且 <= 当前 VERSION）的版本更新日志：[(版本, [条目...]), ...]，最新在前。"""
    ot = _ver_tuple(old_version)
    cur = _ver_tuple(VERSION)
    items = [(v, notes) for v, notes in CHANGELOG.items() if ot < _ver_tuple(v) <= cur]
    items.sort(key=lambda kv: _ver_tuple(kv[0]), reverse=True)
    return items


def _action_for(extra_args):
    """返回计划任务动作的 (Command, Arguments)。安装态优先用安装目录里的副本。"""
    m = installed_main() or _self_path()
    if getattr(sys, "frozen", False):
        return m, extra_args
    return _pythonw_path(), f'"{m}" {extra_args}'.strip()


def _task_xml(triggers_inner, command, arguments, run_level="HighestAvailable",
              desc="LockDevice", delete_expired=False, system=False, on_demand=True):
    if triggers_inner:
        triggers_block = "  <Triggers>\n" + triggers_inner + "\n  </Triggers>\n"
    else:
        triggers_block = "  <Triggers />\n"
    if system:
        # 以 SYSTEM 身份运行（S-1-5-18）：可在登录前、开机时执行关机
        principal = ('    <Principal id="Author">\n'
                     '      <UserId>S-1-5-18</UserId>\n'
                     f'      <RunLevel>{run_level}</RunLevel>\n'
                     '    </Principal>\n')
    else:
        principal = ('    <Principal id="Author">\n'
                     f'      <UserId>{_xml_escape(current_user_id())}</UserId>\n'
                     '      <LogonType>InteractiveToken</LogonType>\n'
                     f'      <RunLevel>{run_level}</RunLevel>\n'
                     '    </Principal>\n')
    dexp = "    <DeleteExpiredTaskAfter>PT0S</DeleteExpiredTaskAfter>\n" if delete_expired else ""
    return "".join([
        '<?xml version="1.0" encoding="UTF-16"?>\n',
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n',
        '  <RegistrationInfo>\n',
        f'    <Description>{_xml_escape(desc)}</Description>\n',
        '  </RegistrationInfo>\n',
        triggers_block,
        '  <Principals>\n',
        principal,
        '  </Principals>\n',
        '  <Settings>\n',
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n',
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n',
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n',
        '    <AllowHardTerminate>true</AllowHardTerminate>\n',
        '    <StartWhenAvailable>true</StartWhenAvailable>\n',
        '    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n',
        f'    <AllowStartOnDemand>{"true" if on_demand else "false"}</AllowStartOnDemand>\n',
        '    <Enabled>true</Enabled>\n',
        '    <Hidden>false</Hidden>\n',
        '    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n',
        '    <WakeToRun>false</WakeToRun>\n',
        '    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>\n',
        '    <Priority>7</Priority>\n',
        dexp,
        '  </Settings>\n',
        '  <Actions Context="Author">\n',
        '    <Exec>\n',
        f'      <Command>{_xml_escape(command)}</Command>\n',
        f'      <Arguments>{_xml_escape(arguments)}</Arguments>\n',
        '    </Exec>\n',
        '  </Actions>\n',
        '</Task>\n',
    ])


def _register_task(name, xml):
    if DRY_RUN:
        print(f"[DRY] 创建计划任务 {name}:\n{xml}")
        return True, "dry-run"
    xml_path = os.path.join(os.environ.get("TEMP", "."), name + ".xml")
    try:
        with open(xml_path, "w", encoding="utf-16") as f:
            f.write(xml)
        r = _run(["schtasks", "/create", "/tn", name, "/xml", xml_path, "/f"])
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()


def _delete_task(name):
    if DRY_RUN:
        print(f"[DRY] 删除计划任务 {name}")
        return True, "dry-run"
    r = _run(["schtasks", "/delete", "/tn", name, "/f"])
    return r.returncode == 0, (r.stderr or r.stdout or "").strip()


def _task_exists(name):
    if DRY_RUN:
        return False
    return _run(["schtasks", "/query", "/tn", name]).returncode == 0


def _logon_trigger(start=None, end=None, user=True):
    lines = ["    <LogonTrigger>", "      <Enabled>true</Enabled>"]
    if user:
        lines.append(f"      <UserId>{_xml_escape(current_user_id())}</UserId>")
    if start:
        lines.append(f"      <StartBoundary>{start}</StartBoundary>")
    if end:
        lines.append(f"      <EndBoundary>{end}</EndBoundary>")
    lines.append("    </LogonTrigger>")
    return "\n".join(lines)


def _boot_trigger(start=None, end=None):
    # 系统启动时触发（登录前），配合 SYSTEM 身份实现「开机即关」
    lines = ["    <BootTrigger>", "      <Enabled>true</Enabled>"]
    if start:
        lines.append(f"      <StartBoundary>{start}</StartBoundary>")
    if end:
        lines.append(f"      <EndBoundary>{end}</EndBoundary>")
    lines.append("    </BootTrigger>")
    return "\n".join(lines)


# ---- 模式二：定时关机任务 ----
#  · 登录前(增强): BootTrigger + SYSTEM + HighestAvailable → 需管理员；绿色模式用受保护副本
#  · 登录后(默认): LogonTrigger + 当前用户 + LeastPrivilege → 标准用户即可创建，无需 UAC
def _shutdown_xml(cmd, args, s, e, preboot):
    if preboot:
        # 开机即触发（SYSTEM 身份，登录前关机）+ 登录触发兜底；均到 EndBoundary 后自动失效
        trig = _boot_trigger(s, e) + "\n" + _logon_trigger(s, e, user=False)
        return _task_xml(trig, cmd, args, delete_expired=True, system=True, on_demand=False,
                         desc="LockDevice 定时关机守护（登录前·开机即关，到期自动失效）")
    # 登录后：当前用户 + 最低权限（InteractiveToken/LeastPrivilege，标准用户免 UAC 即可创建）
    trig = _logon_trigger(s, e, user=True)
    return _task_xml(trig, cmd, args, run_level="LeastPrivilege", delete_expired=True,
                     system=False, on_demand=False,
                     desc="LockDevice 定时关机守护（登录后触发，到期自动失效）")


def build_shutdown_xml(minutes):
    """仅供 --print-xml 只读预览（登录前 SYSTEM 变体）。"""
    now = time.time()
    end = now + minutes * 60
    s, e = _fmt_local(now), _fmt_local(end)
    cmd, args = _action_for(f"--guard {int(end)}")
    return _shutdown_xml(cmd, args, s, e, preboot=True), end


def create_shutdown_task(unlock_epoch, preboot):
    """创建定时关机任务。preboot=True → 登录前 SYSTEM 变体（绿色+提权时指向 ACL 受保护副本，
    防病毒换掉用户可写 exe 借 SYSTEM 任务提权）；preboot=False → 登录后当前用户变体（无需管理员）。"""
    s, e = _fmt_local(time.time()), _fmt_local(unlock_epoch)
    ga = f"--guard {int(unlock_epoch)}"
    if preboot:
        staged = _prepare_protected_boot_exe()
        cmd, args = (staged, ga) if staged else _action_for(ga)
    else:
        cmd, args = _action_for(ga)   # 用户身份运行，换 exe 也提不了权 → 无需受保护副本
    return _register_task(TASK_SHUTDOWN, _shutdown_xml(cmd, args, s, e, preboot))


def remove_shutdown_task():
    return _delete_task(TASK_SHUTDOWN)


def do_shutdown(delay=0, comment=""):
    args = [SHUTDOWN_EXE, "/s", "/f", "/t", str(delay)]
    if comment:
        args += ["/c", comment]
    if DRY_RUN:
        print("[DRY] 将执行：" + " ".join(args))
        return
    _run(args)


def run_guard(unlock_epoch):
    """计划任务每次登录/开机调用的守护逻辑（双保险的第二道）。"""
    if time.time() >= unlock_epoch:
        remove_shutdown_task()   # 到点：清理并放行，绝不关机
    else:
        do_shutdown(0, "LockDevice 专注锁定进行中，自动关机")


# ------------------------------------------------------------------ 安装 / 卸载 / 自启
def start_menu_dir():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "LockDevice")


def create_autostart_tasks():
    """安装时创建按需任务：只需「最高权限打开」任务（快捷方式靠它免 UAC 提权打开）。"""
    opn = _register_task(TASK_OPEN, _task_xml(
        "", *_action_for("--open"),
        desc="LockDevice 打开界面（提权免 UAC）"))
    return opn[0], opn[1]


def _prepare_protected_boot_exe():
    """绿色模式 + 已提权（勾了禁用任务管理器）建开机恢复任务前：把当前 exe 复制到受保护缓存
    目录（系统级临时目录）并上 ACL 锁，返回该受保护副本路径——开机任务指向它、病毒改不动，
    而非指向用户可写目录里的绿色 exe。已安装 / 非冻结返回 None（前者已指向 Program Files 受保护副本）。"""
    if is_installed() or not getattr(sys, "frozen", False):
        return None
    dst = os.path.join(GREEN_CACHE_DIR, "LockDevice.exe")
    if DRY_RUN:
        print(f"[DRY] 暂存受保护副本并上 ACL 锁 -> {dst}")
        return dst
    try:
        os.makedirs(GREEN_CACHE_DIR, exist_ok=True)
        if os.path.abspath(_self_path()) != os.path.abspath(dst):
            _copy_with_retry(_self_path(), dst)
        _lock_dir_acl(GREEN_CACHE_DIR)
        return dst
    except OSError as e:
        _log(f"prepare protected boot exe failed: {e}")
        return None


def _remove_protected_cache():
    """删除绿色模式受保护缓存副本（需管理员；非提权删不掉，留待下次提权运行清理）。"""
    if DRY_RUN or not os.path.isdir(GREEN_CACHE_DIR):
        return
    try:
        shutil.rmtree(GREEN_CACHE_DIR, ignore_errors=True)
        if os.path.isdir(GREEN_CACHE_DIR):   # ACL 挡住普通删除：重置权限后再删
            _run(["icacls", GREEN_CACHE_DIR, "/reset", "/T", "/C"])
            shutil.rmtree(GREEN_CACHE_DIR, ignore_errors=True)
    except Exception as e:
        _log(f"remove protected cache failed: {e}")


def create_boot_task():
    """模式一锁定开始时创建开机恢复任务（智能自启：仅锁定期间存在）。需管理员。
    绿色+提权时指向受保护缓存副本，防病毒换掉用户可写目录里的绿色 exe 借提权任务运行。"""
    staged = _prepare_protected_boot_exe()
    if staged:
        cmd, args = staged, "--resume"
    else:
        cmd, args = _action_for("--resume")
    return _register_task(TASK_BOOT, _task_xml(
        _logon_trigger(), cmd, args, on_demand=False,
        desc="LockDevice 开机自启（恢复未结束的锁定 · 结束后自动移除）"))


# ------------------------------------------------------------------ 插件系统
# 插件放 plugins/ 目录，运行时自动识别加入；打包时整个目录打进 exe（见 build.py）。
# 关键：PyInstaller onefile 下入口以 __main__ 运行，插件不能 import 本体——本体把可用能力
# 打包成一个 api 命名空间注入给插件（_build_plugin_api）。坏插件被 try/except 隔离、不拖垮本体。
_PLUGINS_CACHE = None


def _plugins_dir():
    """插件目录：冻结态在 _MEIPASS 解包目录，源码态在脚本同级（复用 _icon_path 的定位模式）。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(_self_path())
    return os.path.join(base, "plugins")


def _qt_available():
    """gui 界面包 + PySide6 + qfluentwidgets 都在 → 用 Qt；否则回退 tkinter。
    直接试导入 gui.app 最稳（源码/冻结都适用）：能导入即用（随后 main 直接调 run）。"""
    try:
        import PySide6            # noqa: F401
        import qfluentwidgets     # noqa: F401
        import gui.app            # noqa: F401
        return True
    except Exception:
        return False


def load_plugins(force=False):
    """加载 plugins/*.py → [(meta, module), ...]。逐个隔离，坏插件只记日志、不影响其它。"""
    global _PLUGINS_CACHE
    if _PLUGINS_CACHE is not None and not force:
        return _PLUGINS_CACHE
    out = []
    d = _plugins_dir()
    if d and os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    "ld_plugin_" + os.path.splitext(fn)[0], os.path.join(d, fn))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                meta = getattr(mod, "PLUGIN", None)
                if isinstance(meta, dict) and meta.get("id"):
                    out.append((meta, mod))
            except Exception:
                _log("插件加载失败 " + fn + "\n" + traceback.format_exc())
    _PLUGINS_CACHE = out
    return out


def _find_plugin(pid):
    for meta, mod in load_plugins():
        if meta.get("id") == pid:
            return meta, mod
    return None, None


def plugin_disabled(pid):
    return pid in load_config().get("plugins_disabled", [])


def active_plugins():
    """已启用（未被用户关闭）的插件。用于启动器按钮 / 设置 / 开机自启等「生效」场景；
    管理页要列全部请用 load_plugins()。"""
    dis = load_config().get("plugins_disabled", [])
    return [(m, mod) for m, mod in load_plugins() if m.get("id") not in dis]


def _sync_plugin_autostart():
    """按 config.plugins_autostart 记账建/删共享的插件开机自启任务（登录触发·当前用户·免 UAC）。"""
    if bool(load_config().get("plugins_autostart")):
        cmd, args = _action_for("--plugin-boot")
        _register_task(TASK_PLUGIN_BOOT, _task_xml(
            _logon_trigger(), cmd, args, run_level="LeastPrivilege",
            system=False, on_demand=False, desc="LockDevice 插件开机自启"))
    else:
        _delete_task(TASK_PLUGIN_BOOT)


def _build_plugin_api(app=None):
    """本体暴露给插件的能力命名空间。app=None → 无界面（CLI 回调）用途，UI 字段缺省。"""
    def get_settings(pid):
        return dict(load_config().get("plugins", {}).get(pid, {}))

    def save_settings(pid, values):
        cfg = load_config()
        cfg.setdefault("plugins", {})[pid] = dict(values)
        save_config(cfg)

    def set_autostart(pid, on):
        cfg = load_config()
        lst = [x for x in cfg.get("plugins_autostart", []) if x != pid]
        if on:
            lst.append(pid)
        cfg["plugins_autostart"] = lst
        save_config(cfg)
        _sync_plugin_autostart()

    def start_lock(minutes, mode=1):
        secs = int(minutes) * 60
        if app is not None:   # GUI 上下文：直接开锁
            if int(mode) == 2:
                app.start_mode2_lock(int(minutes))
            else:
                app.start_mode1_lock(secs)
            return
        # CLI 上下文（如 --plugin-boot 登录检查）：拉起新进程锁定（复用 --startlock/--startshutdown）
        cli = ["--startshutdown", str(int(minutes))] if int(mode) == 2 else ["--startlock", str(secs)]
        if DRY_RUN:
            _log("[DRY] plugin start_lock -> " + " ".join(cli))
            return
        try:
            subprocess.Popen(_app_cmd(*cli), creationflags=CREATE_NO_WINDOW)
        except Exception:
            _log("plugin start_lock 拉起失败\n" + traceback.format_exc())

    def info(msg, title="LockDevice"):
        if app is not None and not DRY_RUN:
            messagebox.showinfo(title, msg)
        else:
            _log(f"[plugin] {msg}")

    def confirm(msg, title="LockDevice"):
        if app is not None and not DRY_RUN:
            return bool(messagebox.askyesno(title, msg))
        return True

    def error(msg, title="LockDevice"):
        if app is not None and not DRY_RUN:
            messagebox.showerror(title, msg)
        else:
            _log(f"[plugin ERROR] {msg}")

    def run_admin(plugin_id, *args):
        """让插件继承本体的管理员权限：已是管理员 → 返回 True（插件当场做需提权的事）；
        否则提权重启并回调该插件 handle_cli（--plugin <id> ...），返回是否已发起提权。"""
        if is_admin():
            return True
        return relaunch_as_admin(" ".join(["--plugin", str(plugin_id), *[str(a) for a in args]]))

    # 本体对插件只提供三类核心能力：**锁机**(start_lock) + **唤醒插件**(set_autostart → 登录回调 on_boot)
    # + **提权**(is_admin / run_admin，让插件继承本体管理员权限)；外加配置存取 / 对话框 / 环境信息 等支持。
    # 功能逻辑（何时锁、锁多久…）全在插件自己。界面由本体按 SETTINGS/ACTIONS 渲染（换 Qt 插件零改动）。
    return types.SimpleNamespace(
        get_settings=get_settings, save_settings=save_settings, set_autostart=set_autostart,
        start_lock=start_lock, is_admin=is_admin, run_admin=run_admin, is_installed=is_installed,
        DRY_RUN=DRY_RUN, VERSION=VERSION, log=_log,
        info=info, confirm=confirm, error=error)


def _cleanup_plugins():
    """卸载 / 清除数据时清理各插件残留（自身建的任务等）+ 共享的插件开机自启任务。"""
    api = _build_plugin_api(None)
    for _meta, mod in load_plugins():
        if hasattr(mod, "on_uninstall"):
            try:
                mod.on_uninstall(api)
            except Exception:
                _log("plugin on_uninstall 失败\n" + traceback.format_exc())
    _delete_task(TASK_PLUGIN_BOOT)


def _make_lnk(lnk_path, target, args, icon, workdir):
    """用 PowerShell 的 WScript.Shell 创建带图标的 .lnk 快捷方式。"""
    if DRY_RUN:
        print(f"[DRY] 创建快捷方式 {lnk_path} -> {target} {args} (icon={icon})")
        return

    def esc(s):
        return str(s).replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{esc(lnk_path)}');"
          f"$s.TargetPath='{esc(target)}';"
          f"$s.Arguments='{esc(args)}';"
          f"$s.IconLocation='{esc(icon)}';"
          f"$s.WorkingDirectory='{esc(workdir)}';"
          f"$s.Save()")
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])


def _desktop_dir():
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Desktop")


def create_shortcuts(desktop=False):
    """开始菜单（可选桌面）放带图标的 .lnk：打开=指向本体（靠程序自动分流免 UAC 提权）；
    卸载=本体 --uninstall（自提权一次）。"""
    d = installed_dir() or APP_DIR
    if getattr(sys, "frozen", False):
        target = os.path.join(d, "LockDevice.exe")
        base_args, icon = "", target
    else:
        target = _pythonw_path()
        base_args = f'"{os.path.join(d, "lock_device.py")}"'
        icon = os.path.join(d, "lock_device.ico")
    sm = start_menu_dir()
    if not DRY_RUN:
        try:
            os.makedirs(sm, exist_ok=True)
        except OSError:
            pass
    _make_lnk(os.path.join(sm, "LockDevice.lnk"), target, base_args, icon, d)
    _make_lnk(os.path.join(sm, "卸载 LockDevice.lnk"), target,
              (base_args + " --uninstall").strip(), icon, d)
    if desktop:
        _make_lnk(os.path.join(_desktop_dir(), "LockDevice.lnk"), target, base_args, icon, d)


def remove_shortcuts():
    if DRY_RUN:
        print("[DRY] 删除开始菜单/桌面快捷方式")
        return
    shutil.rmtree(start_menu_dir(), ignore_errors=True)
    try:
        os.remove(os.path.join(_desktop_dir(), "LockDevice.lnk"))
    except OSError:
        pass


def _install_opts_file():
    return os.path.join(ROOT_DIR, "install_opts.json")


def save_install_opts(opts):
    try:
        os.makedirs(ROOT_DIR, exist_ok=True)
        with open(_install_opts_file(), "w", encoding="utf-8") as f:
            json.dump(opts, f)
    except OSError:
        pass


def load_install_opts():
    try:
        with open(_install_opts_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def clear_install_opts():
    try:
        os.remove(_install_opts_file())
    except OSError:
        pass


def _ps_quote(s):
    """转义用于 PowerShell 单引号字符串的值。"""
    return str(s).replace("'", "''")


def _lock_dir_acl(path):
    """给安装目录上 ACL：SYSTEM / 管理员完全控制，普通用户仅「读取 + 执行」。
    → 非管理员（普通病毒）无法覆盖/篡改目录内文件，尤其是会被「最高权限任务」触发运行的 exe，
    从而堵住「换掉用户可写路径下的 exe → 触发任务 → 免 UAC 以管理员身份运行恶意代码」这条本地提权链。
    用众所周知 SID（与系统语言无关）。需管理员权限执行（安装时已提权）。"""
    if DRY_RUN:
        print(f"[DRY] 安装目录上 ACL 锁（仅管理员可写）: {path}")
        return True
    try:
        _run(["icacls", path, "/inheritance:r"])   # 断继承，去掉父目录带来的用户可写权限
        r = _run(["icacls", path, "/grant:r",
                  "*S-1-5-18:(OI)(CI)F",       # SYSTEM 完全控制
                  "*S-1-5-32-544:(OI)(CI)F",   # Administrators 完全控制
                  "*S-1-5-32-545:(OI)(CI)RX",  # Users 只读 + 执行
                  "/T", "/C"])
        return r.returncode == 0
    except Exception as e:
        _log(f"lock_dir_acl failed: {e}")
        return False


def _kill_running_exe(exe_path):
    """结束所有「从指定 exe 运行」的进程（更新时腾出被占用的文件）。
    按完整路径匹配、排除自身 PID：更新程序自身是从别处（如下载目录）运行的，路径不同 → 绝不误杀自己。
    仅对冻结 exe 有意义（脚本模式 .py 可直接覆盖）。需足够权限（更新时已提权）。"""
    if not exe_path:
        return
    if DRY_RUN:
        print(f"[DRY] 结束占用文件的运行实例: {exe_path}")
        return
    try:
        name = os.path.splitext(os.path.basename(exe_path))[0]
        ps = (f"Get-Process -Name '{_ps_quote(name)}' -ErrorAction SilentlyContinue | "
              f"Where-Object {{ $_.Path -eq '{_ps_quote(exe_path)}' -and $_.Id -ne {os.getpid()} }} | "
              f"Stop-Process -Force -ErrorAction SilentlyContinue")
        _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
        time.sleep(0.4)   # 等待句柄释放
    except Exception as e:
        _log(f"kill running exe failed: {e}")


def _copy_with_retry(src, dst, tries=6):
    """复制并少量重试，等待被结束的运行实例释放文件句柄。"""
    last = None
    for _ in range(tries):
        try:
            shutil.copy2(src, dst)
            return
        except OSError as e:
            last = e
            time.sleep(0.3)
    if last:
        raise last


def do_install(install_dir=None, desktop=True, launch=True):
    """执行安装。需管理员权限。返回 (成功?, 信息)。"""
    try:
        install_dir = (install_dir or APP_DIR).strip() or APP_DIR
        main_dst = os.path.join(install_dir, _main_name())
        if DRY_RUN:
            print(f"[DRY] 安装到 {install_dir}（desktop={desktop}, launch={launch}），写入 {INSTALL_FLAG}")
        else:
            os.makedirs(install_dir, exist_ok=True)
            src = _self_path()
            if os.path.abspath(src) != os.path.abspath(main_dst):
                if getattr(sys, "frozen", False):
                    _kill_running_exe(main_dst)   # 更新：先结束占用旧 exe 的实例，腾出文件
                try:
                    _copy_with_retry(src, main_dst)
                except OSError:
                    return False, ("更新/安装失败：目标文件被占用，无法覆盖。\n"
                                   "请手动关闭所有正在运行的 LockDevice 后重试。")
            if not getattr(sys, "frozen", False):
                ico = _icon_path()
                if ico:
                    try:
                        shutil.copy2(ico, os.path.join(install_dir, "lock_device.ico"))
                    except OSError:
                        pass
            os.makedirs(ROOT_DIR, exist_ok=True)
            with open(INSTALL_FLAG, "w", encoding="utf-8") as f:
                f.write(install_dir)
            with open(_version_file(), "w", encoding="utf-8") as f:
                f.write(VERSION)
        # 安装目录上 ACL 锁：普通用户只读，防非管理员病毒篡改被「最高权限任务」运行的 exe
        _lock_dir_acl(install_dir)
        ok, msg = create_autostart_tasks()
        create_shortcuts(desktop=desktop)
        if ok:
            if launch and not DRY_RUN:
                _run(["schtasks", "/run", "/tn", TASK_OPEN])
            return True, ("安装完成！\n\n"
                          f"· 安装位置：{install_dir}\n"
                          "· 打开程序与「定时关机」此后免管理员确认。\n"
                          "· 模式一锁定期间智能开机自启恢复。\n"
                          + ("· 已创建桌面 + 开始菜单快捷方式。" if desktop
                             else "· 已创建开始菜单快捷方式。"))
        if not DRY_RUN:   # 任务创建失败：回滚安装标记，避免半安装状态
            try:
                os.remove(INSTALL_FLAG)
            except OSError:
                pass
        return False, "计划任务创建失败（可能未获得管理员权限）：\n" + msg
    except Exception as e:
        return False, f"安装出错：{e}"


def do_uninstall():
    """卸载：删任务、快捷方式、安装文件。需管理员权限。返回 (成功?, 信息)。"""
    d = installed_dir()
    for t in (TASK_BOOT, TASK_OPEN, TASK_UNINSTALL, TASK_SHUTDOWN):
        _delete_task(t)
    _cleanup_plugins()   # 各插件清理自己的任务 + 删共享的插件开机自启任务
    remove_shortcuts()
    if DRY_RUN:
        print(f"[DRY] 删除安装目录 {d or APP_DIR}")
    else:
        try:
            os.remove(INSTALL_FLAG)
        except OSError:
            pass
        for target in {d, APP_DIR}:   # 删默认与自定义安装目录，但绝不删数据根目录
            if target and os.path.isdir(target) and os.path.abspath(target) != os.path.abspath(ROOT_DIR):
                shutil.rmtree(target, ignore_errors=True)
        try:
            os.remove(os.path.join(ROOT_DIR, "config.json"))
        except OSError:
            pass
    return True, "已卸载：计划任务、开机自启、快捷方式与安装文件均已移除。"


# ---- 绿色模式：无需管理员的登录自启（HKCU\Run） ----
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "LockDevice"


def set_run_key():
    """写入 HKCU\\Run 登录自启项（绿色模式重启后恢复锁定，无需管理员）。"""
    if DRY_RUN:
        print("[DRY] 写入 HKCU\\Run 自启项 -> --resume")
        return
    cmd, args = _action_for("--resume")
    line = f'"{cmd}" {args}'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
            winreg.SetValueEx(k, RUN_VALUE_NAME, 0, winreg.REG_SZ, line)
    except OSError:
        pass


def remove_run_key():
    if DRY_RUN:
        print("[DRY] 删除 HKCU\\Run 自启项")
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_VALUE_NAME)
    except OSError:
        pass


def run_key_exists():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as k:
            winreg.QueryValueEx(k, RUN_VALUE_NAME)
        return True
    except OSError:
        return False


# ---- 禁用任务管理器（锁定期间防止被结束进程；HKCU 策略，无需管理员） ----
POLICY_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"


def set_taskmgr_disabled(disabled):
    """锁定期间禁用任务管理器（连 Ctrl+Alt+Del 里的入口也会被禁）。
    写 Policies 键受 ACL 保护、需要管理员，故仅在已安装(提权运行)时生效；绿色/非提权模式无权设置。"""
    if not is_admin():
        return False   # 非提权（如绿色模式）无权写 Policies 键
    if DRY_RUN:
        print(f"[DRY] DisableTaskMgr={1 if disabled else 0}")
        return True
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, POLICY_KEY_PATH) as k:
            winreg.SetValueEx(k, "DisableTaskMgr", 0, winreg.REG_DWORD, 1 if disabled else 0)
        return True
    except OSError:
        return False


def clear_data():
    """清除绿色运行留下的数据与登录自启项（手动强制清除，会清掉保存的设置）。"""
    removed = []
    _cleanup_plugins()   # 先让各插件清掉自己建的任务（如自动锁机的每日任务）
    if run_key_exists() or DRY_RUN:
        remove_run_key()
        removed.append("HKCU\\Run\\LockDevice 自启项")
    if os.path.isdir(GREEN_CACHE_DIR) or DRY_RUN:
        if DRY_RUN:
            print(f"[DRY] 删除受保护缓存 {GREEN_CACHE_DIR}")
        else:
            _remove_protected_cache()
        if DRY_RUN or not os.path.isdir(GREEN_CACHE_DIR):
            removed.append(GREEN_CACHE_DIR + "（受保护缓存）")
    targets = [PORTABLE_DIR]
    if not is_installed():
        targets.append(ROOT_DIR)  # 未安装时整个目录都是绿色/垃圾数据
    for p in targets:
        if os.path.isdir(p):
            if DRY_RUN:
                print(f"[DRY] 删除 {p}")
            else:
                shutil.rmtree(p, ignore_errors=True)
            removed.append(p)
    return removed


def clear_lock_state():
    """锁定结束/过期后复位运行态：移除临时自启（绿色 run key / 已装 Boot 任务）+ 清
    lock_until，但保留用户设置。"""
    set_taskmgr_disabled(False)   # 恢复任务管理器
    remove_run_key()
    _delete_task(TASK_BOOT)       # 智能自启：空闲时段不应存在（提权才建、删除也需提权）
    _remove_protected_cache()     # 删除绿色模式受保护缓存副本（若有）
    cfg = load_config()
    if cfg.get("lock_until") is not None:
        cfg["lock_until"] = None
        save_config(cfg)


def tidy_portable_leftovers():
    """绿色模式启动时自动清理「已过期」的残留锁定态（如模式二关机窗口结束后遗留的）。
    只复位过期的锁定态、保留用户设置；未过期的留给恢复流程，已安装则完全不动。"""
    if is_installed():
        return
    lu = load_config().get("lock_until")
    if lu and time.time() >= lu:
        clear_lock_state()


# ------------------------------------------------------------------ 键盘钩子（模式一）
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
VK_TAB, VK_ESCAPE, VK_LWIN, VK_RWIN, VK_F4 = 0x09, 0x1B, 0x5B, 0x5C, 0x73
VK_MENU, VK_CONTROL = 0x12, 0x11

LRESULT = ctypes.c_ssize_t
ULONG_PTR = wintypes.WPARAM


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


LowLevelKeyboardProc = ctypes.CFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc,
                                     wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.GetAsyncKeyState.restype = ctypes.c_short


class KeyBlocker:
    """独立线程安装全局低级键盘钩子，拦截常见逃逸热键。
    注意：Ctrl+Alt+Del 是内核级安全组合键，用户态无法拦截。"""

    def __init__(self):
        self._hook = None
        self._thread = None
        self._thread_id = None
        self._proc = None  # 必须保持引用，否则回调被 GC 回收会崩溃

    def _handler(self, nCode, wParam, lParam):
        if nCode == 0:  # HC_ACTION
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            alt = user32.GetAsyncKeyState(VK_MENU) & 0x8000
            ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
            if (vk in (VK_LWIN, VK_RWIN)
                    or (vk == VK_TAB and alt)
                    or (vk == VK_ESCAPE and (alt or ctrl))
                    or (vk == VK_F4 and alt)):
                return 1  # 吞掉该按键
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _loop(self):
        self._thread_id = kernel32.GetCurrentThreadId()
        self._proc = LowLevelKeyboardProc(self._handler)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        msg = wintypes.MSG()
        while True:
            if user32.GetMessageW(ctypes.byref(msg), None, 0, 0) in (0, -1):
                break
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread_id = None


# ------------------------------------------------------------------ 进程互守（看门狗）
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

PROCESS_SYNCHRONIZE = 0x00100000
PROCESS_TERMINATE = 0x0001


def _process_alive(pid):
    if not pid:
        return False
    h = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, int(pid))
    if not h:
        return False
    try:
        return kernel32.WaitForSingleObject(h, 0) != 0  # 0=已退出，0x102=仍在跑
    finally:
        kernel32.CloseHandle(h)


def _kill_pid(pid):
    if not pid:
        return
    if DRY_RUN:
        print(f"[DRY] 结束进程 {pid}")
        return
    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
    if h:
        kernel32.TerminateProcess(h, 1)
        kernel32.CloseHandle(h)


def _locker_pidfile():
    return os.path.join(data_dir(), "locker.pid")


def _watchdog_pidfile():
    return os.path.join(data_dir(), "watchdog.pid")


def _read_pidfile(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _write_pidfile(path, pid):
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(pid))
    except OSError:
        pass


def _app_cmd(*extra):
    """构造重新拉起本程序的命令行（脚本或冻结 exe 都适用）。
    安全：用「当前正在运行的本体」(_self_path)，不从用户可写的 installed.flag 推断路径——
    避免病毒改写 flag 让提权实例重生（看门狗 / 中继）时去运行被替换的文件。"""
    m = _self_path()
    if getattr(sys, "frozen", False):
        return [m, *extra]
    return [_pythonw_path(), m, *extra]


def _spawn_detached(*app_args):
    """经一个立即退出的 Python 中继进程启动 pythonw script <app_args>，使 target 脱离当前进程树
    （任务管理器结束本进程时不牵连它）。纯 Python subprocess，中文路径安全。"""
    try:
        subprocess.Popen(_app_cmd("--relay", *app_args), creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def run_watchdog():
    """看门狗进程（--watch）：写自己 pid，监视 locker.pid；locker 死了就脱离进程树重启它；
    locker.pid 文件消失（锁定正常结束）则自退。"""
    _write_pidfile(_watchdog_pidfile(), os.getpid())
    try:
        while os.path.exists(_locker_pidfile()):
            lp = _read_pidfile(_locker_pidfile())
            if lp and not _process_alive(lp):
                _spawn_detached("--resume")   # 重生 locker（脱离本看门狗进程树）
                time.sleep(1.2)
            time.sleep(0.4)
    finally:
        try:
            os.remove(_watchdog_pidfile())
        except OSError:
            pass


# ------------------------------------------------------------------ GUI
def _make_root():
    if HAS_CTK:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        return ctk.CTk()
    return tk.Tk()


class App:
    def __init__(self):
        self.blocker = KeyBlocker()
        self.lock_win = None
        self.resumed = False
        self._end = 0.0
        self._suspend_top = False
        self._guard_on = False
        self._block_tm = False
        self._stopping = False
        self._dirty = False
        self._did_update = False
        self._shortcuts = []
        self.watchdog_pid = None
        self.watchdog_proc = None
        self.root = _make_root()
        self.root.title("LockDevice · 专注锁定")
        self.root.geometry("470x660")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.report_callback_exception = self._log_cb_exc
        _set_icon(self.root)
        self.content = None
        self.plugin_api = _build_plugin_api(self)   # 注入给插件的能力命名空间

    def _log_cb_exc(self, exc, val, tb):
        _log("CALLBACK 异常:\n" + "".join(traceback.format_exception(exc, val, tb)))
        try:
            messagebox.showerror("出错了", f"{val}\n\n详情已写入 error.log")
        except Exception:
            pass

    def run(self):
        try:
            self.root.mainloop()
        except tk.TclError as ex:
            _log(f"mainloop TclError: {ex}")

    # ---- 关闭拦截：未保存改动提醒 ----
    def _on_close(self):
        if getattr(self, "_dirty", False):
            ans = messagebox.askyesnocancel("未保存的更改", "设置有未保存的更改，是否保存后退出？")
            if ans is None:
                return
            if ans:
                self._save_all()
        self.root.destroy()

    def on_back(self):
        if getattr(self, "_dirty", False):
            ans = messagebox.askyesnocancel("未保存的更改", "设置有未保存的更改，是否保存？")
            if ans is None:          # 取消：留在设置页
                return
            if ans and not self._save_all():
                return               # 保存失败（如时长无效）：留在设置页
        self.show_launcher()

    def _mark_dirty(self, *_):
        self._dirty = True

    def _set_cb_enabled(self, cb, enabled):
        """启用/禁用复选框：禁用时连勾选框（边框/填充）一起置灰，而不只是文字。
        （customtkinter 默认禁用只改文字颜色、方框仍是高亮色，这里手动把方框也调灰。）"""
        if not hasattr(cb, "_cb_colors"):     # 首次调用记住原始（启用态）配色
            cb._cb_colors = (cb.cget("fg_color"), cb.cget("border_color"))
        if enabled:
            fg, bd = cb._cb_colors
            cb.configure(state="normal", fg_color=fg, border_color=bd)
        else:
            cb.configure(state="disabled", fg_color=COL_GRAY, border_color=COL_GRAY)

    def _on_mode_change(self):
        self._mark_dirty()
        is1 = self.mode_var.get() == 1
        self._set_cb_enabled(self.guard_cb, is1)
        self._set_cb_enabled(self.block_tm_cb, is1)
        self._set_cb_enabled(self.preboot_cb, not is1)
        self._set_cb_enabled(self.instant_cb, not is1)

    # ---- 通用组件 ----
    def _clear(self):
        if self.content is not None:
            self.content.destroy()
        if HAS_CTK:
            self.content = ctk.CTkFrame(self.root, fg_color="transparent")
        else:
            self.content = tk.Frame(self.root)
        self.content.pack(fill="both", expand=True, padx=22, pady=16)
        return self.content

    def _btn(self, parent, text, cmd, color=None, height=44):
        kw = {"fg_color": color} if color else {}
        return ctk.CTkButton(parent, text=text, command=cmd, height=height,
                             font=(FONT, 14, "bold"), corner_radius=10, **kw)

    def _bring_to_front(self):
        """把窗口拉到最前（schtasks 免 UAC 打开的实例常在后台/最小化，这里强制显示到最前）。"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    # ---------------- 启动器 ----------------
    def show_launcher(self):
        self.root.deiconify()
        c = self._clear()
        ctk.CTkLabel(c, text="LockDevice", font=(FONT, 26, "bold")).pack(pady=(16, 0))
        ctk.CTkLabel(c, text="专注锁定", font=(FONT, 13), text_color="gray").pack(pady=(0, 6))
        installed = is_installed()
        if installed and has_update():
            stext, scolor = f"● 已安装 v{installed_version()} · 有新版本 v{VERSION}", COL_ORANGE
        elif installed:
            stext, scolor = f"● 已安装 v{installed_version()} · 智能开机自启", COL_GREEN
        else:
            stext, scolor = f"○ 未安装 · 绿色 / 便携模式 · v{VERSION}", "gray"
        ctk.CTkLabel(c, text=stext, text_color=scolor, font=(FONT, 12)).pack(pady=(2, 20))
        if installed and has_update():
            self._btn(c, f"🔄  更新到 v{VERSION}", self.on_update, COL_ORANGE).pack(fill="x", pady=6)
        # 主操作：进入锁定设置（绿色 / 已安装同名「专注锁定」）
        self._btn(c, "🎯   专注锁定", self.show_main, COL_GREEN).pack(fill="x", pady=6)
        # 每个已识别插件一个按钮（插件只声明 SETTINGS/ACTIONS，本体渲染其单页）+ 统一「设置」入口。
        # 两模式都显示；插件多了改用 CTkScrollableFrame
        plugins = active_plugins()
        for meta, mod in plugins:
            if getattr(mod, "SETTINGS", None) or getattr(mod, "ACTIONS", None):
                label = meta.get("button") or meta.get("name") or meta.get("id")
                self._btn(c, label, (lambda mt=meta, md=mod: self._show_plugin(mt, md)),
                          COL_BLUE).pack(fill="x", pady=6)
        if any(getattr(mod, "SETTINGS", None) for _m, mod in plugins):
            self._btn(c, "⚙   设置", self.show_settings, COL_GRAY).pack(fill="x", pady=6)
        if load_plugins():
            self._btn(c, "🧩  插件管理（启用/关闭）", self.show_plugin_manage, COL_GRAY).pack(fill="x", pady=6)
        # 次要操作
        if installed:
            self._btn(c, "✖   卸载", self.on_uninstall, COL_RED).pack(fill="x", pady=6)
        else:
            self._btn(c, "⬇   安装到本机", self.on_install, COL_BLUE).pack(fill="x", pady=6)
            ctk.CTkLabel(c, text="安装 = 智能开机自启 + 重启恢复 + 此后免管理员（需一次授权）",
                         text_color="gray", font=(FONT, 11), wraplength=410).pack(pady=(2, 4))
            self._btn(c, "🧹  清除数据（清理绿色/便携残留）", self.on_clear_data, COL_GRAY).pack(fill="x", pady=6)
        self._bring_to_front()

    # ---------------- 插件统一设置页（单窗切换） ----------------
    def show_settings(self):
        self.root.deiconify()
        c = self._clear()
        ctk.CTkLabel(c, text="⚙  设置", font=(FONT, 22, "bold")).pack(pady=(4, 2))
        ctk.CTkLabel(c, text="插件设置 · 与本体共用配置、按插件分区", text_color="gray",
                     font=(FONT, 11)).pack(pady=(0, 8))
        bottom = ctk.CTkFrame(c, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        self._btn(bottom, "💾  保存", self._save_settings, COL_GREEN).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bottom, text="←  返回", fg_color=COL_GRAY,
                      command=self.show_launcher).pack(fill="x")
        box = ctk.CTkScrollableFrame(c, fg_color="transparent")
        box.pack(side="top", fill="both", expand=True)
        self._settings_vars = []   # [(pid, key, type, tk_var)]
        plugins = [(m, mod) for m, mod in active_plugins() if getattr(mod, "SETTINGS", None)]
        if not plugins:
            ctk.CTkLabel(box, text="（暂无可配置的插件）", text_color="gray").pack(pady=10)
        self._render_plugin_settings(box, plugins)
        self._bring_to_front()

    def _render_setting_field(self, box, pid, field, vals):
        key, ftype = field["key"], field.get("type", "str")
        cur = vals.get(key, field.get("default"))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=3)
        if ftype == "bool":
            var = tk.BooleanVar(value=bool(cur))
            ctk.CTkCheckBox(row, text=field.get("label", key), variable=var,
                            font=(FONT, 12)).pack(anchor="w")
        elif ftype == "choice":
            opts = [str(o) for o in field.get("options", [])]
            var = tk.StringVar(value=str(cur if cur is not None else (opts[0] if opts else "")))
            ctk.CTkLabel(row, text=field.get("label", key), font=(FONT, 12)).pack(side="left")
            ctk.CTkOptionMenu(row, variable=var, values=opts, width=150).pack(side="right")
        else:   # int / str
            var = tk.StringVar(value="" if cur is None else str(cur))
            ctk.CTkLabel(row, text=field.get("label", key), font=(FONT, 12)).pack(side="left")
            ctk.CTkEntry(row, textvariable=var, width=150, justify="center").pack(side="right")
        self._settings_vars.append((pid, key, ftype, var))

    def _save_settings(self):
        cfg = load_config()
        cfg.setdefault("plugins", {})
        touched = {}
        for pid, key, ftype, var in getattr(self, "_settings_vars", []):
            v = var.get()
            if ftype == "bool":
                v = bool(v)
            elif ftype == "int":
                try:
                    v = int(str(v).strip())
                except (ValueError, TypeError):
                    v = 0
            touched.setdefault(pid, {})[key] = v
        for pid, values in touched.items():
            merged = dict(cfg["plugins"].get(pid, {}))
            merged.update(values)
            cfg["plugins"][pid] = merged
        save_config(cfg)
        for meta, mod in load_plugins():
            if meta["id"] in touched and hasattr(mod, "on_settings_saved"):
                try:
                    mod.on_settings_saved(self.plugin_api, dict(cfg["plugins"].get(meta["id"], {})))
                except Exception:
                    _log("plugin on_settings_saved 失败 " + meta["id"] + "\n" + traceback.format_exc())
        messagebox.showinfo("已保存", "设置已保存。")
        self.show_settings()

    def _render_plugin_settings(self, box, plugins):
        """按各插件声明的 SETTINGS（前端 schema）渲染表单，填充 self._settings_vars。"""
        cfg = load_config()
        for meta, mod in plugins:
            pid = meta["id"]
            vals = cfg.get("plugins", {}).get(pid, {})
            ctk.CTkLabel(box, text=meta.get("name", pid), font=(FONT, 14, "bold"),
                         anchor="w").pack(fill="x", padx=4, pady=(10, 2))
            for field in getattr(mod, "SETTINGS", []):
                self._render_setting_field(box, pid, field, vals)

    def _show_plugin(self, meta, mod):
        """插件单页（单窗切换）：本体按插件声明的 SETTINGS + ACTIONS 渲染；插件只写后端。"""
        self.root.deiconify()
        c = self._clear()
        ctk.CTkLabel(c, text=meta.get("name", meta["id"]), font=(FONT, 22, "bold")).pack(pady=(4, 2))
        ctk.CTkLabel(c, text=f"v{meta.get('version', '')}", text_color="gray",
                     font=(FONT, 11)).pack(pady=(0, 8))
        bottom = ctk.CTkFrame(c, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        self._btn(bottom, "💾  保存", self._save_settings, COL_GREEN).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bottom, text="←  返回", fg_color=COL_GRAY,
                      command=self.show_launcher).pack(fill="x")
        box = ctk.CTkScrollableFrame(c, fg_color="transparent")
        box.pack(side="top", fill="both", expand=True)
        self._settings_vars = []
        self._render_plugin_settings(box, [(meta, mod)])
        # 动作按钮（ACTIONS 声明 → 本体渲染，点击调插件后端函数）
        for act in getattr(mod, "ACTIONS", []) or []:
            fn = getattr(mod, act.get("fn", ""), None)
            if callable(fn):
                self._btn(box, act.get("label", act.get("fn", "")),
                          (lambda f=fn: f(self.plugin_api)), COL_BLUE).pack(fill="x", padx=8, pady=(10, 2))
        self._bring_to_front()

    # ---------------- 插件管理（启用/关闭） ----------------
    def show_plugin_manage(self):
        self.root.deiconify()
        c = self._clear()
        ctk.CTkLabel(c, text="🧩  插件管理", font=(FONT, 20, "bold")).pack(pady=(4, 2))
        ctk.CTkLabel(c, text="开关启用 / 关闭插件（关闭后不加载运行、开机也不唤醒）",
                     text_color="gray", font=(FONT, 11)).pack(pady=(0, 8))
        bottom = ctk.CTkFrame(c, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        ctk.CTkButton(bottom, text="←  返回", fg_color=COL_GRAY,
                      command=self.show_launcher).pack(fill="x")
        box = ctk.CTkScrollableFrame(c, fg_color="transparent")
        box.pack(side="top", fill="both", expand=True)
        allp = load_plugins()
        if not allp:
            ctk.CTkLabel(box, text="（plugins/ 下暂无插件）", text_color="gray").pack(pady=10)
        dis = load_config().get("plugins_disabled", [])
        for meta, mod in allp:
            pid = meta["id"]
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=4)
            var = tk.BooleanVar(value=(pid not in dis))
            ctk.CTkLabel(row, text=f"{meta.get('name', pid)}  ·  v{meta.get('version', '')}",
                         anchor="w", font=(FONT, 13)).pack(side="left", fill="x", expand=True)
            ctk.CTkSwitch(row, text="", variable=var,
                          command=lambda p=pid, m=mod, v=var: self._toggle_plugin(p, m, v.get())).pack(side="right")
        self._bring_to_front()

    def _toggle_plugin(self, pid, mod, on):
        cfg = load_config()
        dis = [x for x in cfg.get("plugins_disabled", []) if x != pid]
        if on:
            cfg["plugins_disabled"] = dis
            save_config(cfg)
            if hasattr(mod, "on_settings_saved"):
                try:
                    mod.on_settings_saved(self.plugin_api, dict(cfg.get("plugins", {}).get(pid, {})))
                except Exception:
                    _log("on_settings_saved 失败\n" + traceback.format_exc())
        else:
            dis.append(pid)
            cfg["plugins_disabled"] = dis
            save_config(cfg)
            if hasattr(mod, "on_uninstall"):
                try:
                    mod.on_uninstall(self.plugin_api)
                except Exception:
                    _log("on_uninstall 失败\n" + traceback.format_exc())

    def on_install(self):
        self._install_dialog()

    def _install_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("安装到本机")
        _set_icon(dlg)
        dlg.geometry("470x330")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.after(60, dlg.grab_set)

        ctk.CTkLabel(dlg, text="安装到本机", font=(FONT, 16, "bold")).pack(pady=(16, 2))
        ctk.CTkLabel(dlg, text="一次管理员授权 → 开机自启 / 免 UAC / 定时关机",
                     text_color="gray", font=(FONT, 11)).pack()

        ctk.CTkLabel(dlg, text="安装位置", text_color="gray",
                     anchor="w").pack(fill="x", padx=22, pady=(14, 2))
        prow = ctk.CTkFrame(dlg, fg_color="transparent")
        prow.pack(fill="x", padx=22)
        dir_var = tk.StringVar(value=APP_DIR)
        ctk.CTkEntry(prow, textvariable=dir_var).pack(side="left", fill="x", expand=True)

        def browse():
            from tkinter import filedialog
            base = os.path.dirname(dir_var.get().rstrip("\\/")) or ROOT_DIR
            picked = filedialog.askdirectory(parent=dlg, initialdir=base)
            if picked:
                dir_var.set(os.path.join(picked, "LockDevice"))
        ctk.CTkButton(prow, text="浏览…", width=64, command=browse).pack(side="left", padx=(6, 0))

        desktop_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(dlg, text="创建桌面快捷方式",
                        variable=desktop_var).pack(anchor="w", padx=22, pady=(16, 4))
        launch_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(dlg, text="安装后立即启动", variable=launch_var).pack(anchor="w", padx=22)

        def start_install():
            opts = {"dir": dir_var.get().strip() or APP_DIR,
                    "desktop": bool(desktop_var.get()), "launch": bool(launch_var.get())}
            dlg.destroy()
            save_install_opts(opts)
            if DRY_RUN or is_admin():
                ok, msg = do_install(opts["dir"], opts["desktop"], opts["launch"])
                clear_install_opts()
                (messagebox.showinfo if ok else messagebox.showerror)("安装", msg)
                self.show_launcher()
            elif relaunch_as_admin("--install"):
                self.root.destroy()
            else:
                clear_install_opts()
                messagebox.showwarning("已取消", "未获得管理员权限，安装取消。")

        ctk.CTkButton(dlg, text="⬇  开始安装", fg_color=COL_BLUE, height=42,
                      font=(FONT, 14, "bold"), command=start_install).pack(fill="x", padx=22, pady=(20, 12))

    def on_uninstall(self):
        if not messagebox.askyesno(
                "卸载确认",
                "确定卸载 LockDevice 吗？\n将删除计划任务、开机自启、快捷方式与安装文件。"):
            return
        if DRY_RUN or is_admin():
            ok, msg = do_uninstall()
            messagebox.showinfo("卸载", msg)
            self.show_launcher()
        elif relaunch_as_admin("--uninstall"):
            self.root.destroy()
        else:
            messagebox.showwarning("已取消", "未获得管理员权限，卸载取消。")

    def on_update(self):
        d = installed_dir()
        if not d:
            return
        if not messagebox.askyesno(
                "更新",
                f"将已安装版本更新到 v{VERSION}（原地覆盖、保留你的所有设置）。\n\n"
                "· 会自动结束正在运行的旧版本实例以完成覆盖，更新后自动打开新版本。\n\n确定更新吗？"):
            return
        save_install_opts({"dir": d, "desktop": False, "launch": True})
        self._did_update = True   # 标记已走更新流程：外层分流不再另开已安装版
        if DRY_RUN or is_admin():
            ok, msg = do_install(d, desktop=False, launch=True)
            clear_install_opts()
            (messagebox.showinfo if ok else messagebox.showerror)("更新", msg)
            self.show_launcher()
        elif relaunch_as_admin("--install"):
            self.root.destroy()
        else:
            self._did_update = False
            clear_install_opts()
            messagebox.showwarning("已取消", "未获得管理员权限，更新取消。")

    def show_update_window(self):
        """新版文件在已安装机器上运行时的独立「发现更新」窗。
        此前已用最高权限任务免 UAC 打开了已安装（旧）版本；本窗只展示更新日志 + 提供更新按钮。
        不点更新 → 本进程未提权、零 UAC；点更新才提权覆盖（会自动结束旧实例后覆盖）。"""
        self.root.deiconify()
        self.root.title("LockDevice · 发现新版本")
        self.root.geometry("470x560")
        c = self._clear()
        ctk.CTkLabel(c, text="🔄  发现新版本", font=(FONT, 22, "bold")).pack(pady=(14, 2))
        ctk.CTkLabel(c, text=f"已安装 v{installed_version()}    →    新版本 v{VERSION}",
                     font=(FONT, 14, "bold"), text_color=COL_ORANGE).pack(pady=(0, 2))
        ctk.CTkLabel(c, text="已为你免管理员打开当前已安装的版本；如需升级点下方「更新」。",
                     font=(FONT, 11), text_color="gray", wraplength=420).pack(pady=(0, 10))

        ctk.CTkLabel(c, text="更新内容", anchor="w", text_color="gray",
                     font=(FONT, 12)).pack(fill="x")
        box = ctk.CTkScrollableFrame(c, fg_color=("gray90", "gray17"))
        box.pack(fill="both", expand=True, pady=(4, 12))
        logs = changelog_since(installed_version())
        if not logs:
            ctk.CTkLabel(box, text="（本版本未附更新说明）", text_color="gray",
                         font=(FONT, 12), anchor="w").pack(fill="x", padx=8, pady=6)
        content_lbls = []

        def _fit_wrap():
            # 布局完成后按「内容框实宽」把正文换行宽度调到位（一次性；不绑 <Configure> 到标签本身，
            # 免得滚动条一出现→标签变窄→反复触发→抖动甚至 Tcl 递归崩溃）。
            try:
                n = max(300, self.content.winfo_width() - 76)
            except Exception:
                return
            for w in content_lbls:
                if int(w.cget("wraplength")) != n:
                    w.configure(wraplength=n)

        for ver, notes in logs:
            ctk.CTkLabel(box, text=f"v{ver}", font=(FONT, 13, "bold"),
                         anchor="w").pack(fill="x", padx=8, pady=(8, 0))
            for line in notes:
                # 圆点单独一列（顶对齐）+ 正文单独一个可换行标签：既不会把「·」断到单独一行，
                # 续行也会挂起缩进对齐到正文左侧。wraplength 先给保守值，布局完成后再按实宽调宽。
                row = ctk.CTkFrame(box, fg_color="transparent")
                row.pack(fill="x", padx=8, pady=1)
                ctk.CTkLabel(row, text="·", font=(FONT, 12), width=14,
                             anchor="nw").pack(side="left", anchor="n", padx=(4, 2))
                lbl = ctk.CTkLabel(row, text=line, font=(FONT, 12), justify="left",
                                   anchor="w", wraplength=300)
                lbl.pack(side="left", fill="x", expand=True)
                content_lbls.append(lbl)
        self.root.after(80, _fit_wrap)
        self.root.after(500, _fit_wrap)

        self._btn(c, f"🔄  更新到 v{VERSION}", self.on_update, COL_ORANGE).pack(fill="x", pady=(0, 6))
        brow = ctk.CTkFrame(c, fg_color="transparent")
        brow.pack(fill="x")
        self._btn(brow, "稍后再说", self.root.destroy, COL_GRAY).pack(side="left", fill="x", expand=True)
        self._btn(brow, "跳过此版本", self._skip_version, COL_GRAY).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ctk.CTkLabel(c, text="「稍后再说」下次仍会提示；「跳过此版本」则此版本不再提示（出现更高版本时仍会提示）。",
                     text_color="gray", font=(FONT, 10), wraplength=424, justify="left").pack(pady=(6, 0))
        self._bring_to_front()
        # 已安装版启动器是另一进程（schtasks 冷启动可能 1~2s 后才出现并自置顶），
        # 开头几秒多抢几次前台，确保本「发现更新」窗叠在启动器之上、不被盖住；随后交还控制权。
        for _delay in (1200, 3000):
            self.root.after(_delay, self._bring_to_front)

    def _skip_version(self):
        """记住「跳过此版本」：写入 config.skip_version = 当前版本；
        下次打开同一新版本时不再弹更新窗（出现更高版本仍会提示）。"""
        cfg = load_config()
        cfg["skip_version"] = VERSION
        save_config(cfg)
        self.root.destroy()

    def on_clear_data(self):
        if not messagebox.askyesno(
                "清除数据",
                "将删除绿色运行留下的配置（含已保存的设置）与缓存，确定？"):
            return
        # 崩溃残留的受保护缓存目录已上 ACL 锁，非管理员删不掉 → 自动提权后清除
        if os.path.isdir(GREEN_CACHE_DIR) and not is_admin() and not DRY_RUN:
            if relaunch_as_admin("--cleardata"):
                self.root.destroy()
                return
            messagebox.showwarning(
                "需要管理员",
                "受保护缓存需管理员权限才能清除；未获授权，将只清除其它数据。")
        removed = clear_data()
        messagebox.showinfo("清除数据",
                            "已清除：\n" + ("\n".join(removed) if removed else "（没有需要清除的数据）"))
        self.show_launcher()

    # ---------------- 主界面（设置 + 控制） ----------------
    def show_main(self):
        self.root.deiconify()
        c = self._clear()
        cfg = load_config()
        self._shortcuts = [dict(s) for s in cfg.get("shortcuts", []) if isinstance(s, dict)]

        ctk.CTkLabel(c, text="专注锁定", font=(FONT, 20, "bold")).pack(pady=(2, 6))

        # 底部固定操作区（先 pack 到底部，快捷再多也始终可见）
        bottom = ctk.CTkFrame(c, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        self._btn(bottom, "🔒  开始锁定", self.on_start, COL_ORANGE).pack(fill="x", pady=(0, 6))
        barrow = ctk.CTkFrame(bottom, fg_color="transparent")
        barrow.pack(fill="x")
        ctk.CTkButton(barrow, text="💾 保存设置", width=120, command=self.on_save).pack(side="left")
        ctk.CTkButton(barrow, text="← 返回", width=90, fg_color=COL_GRAY,
                      command=self.on_back).pack(side="right")
        if _task_exists(TASK_SHUTDOWN):
            ctk.CTkButton(bottom, text="⚠ 解除已存在的关机计划", fg_color=COL_RED,
                          command=self.on_remove_shutdown).pack(fill="x", pady=(6, 0))

        # 上部设置区（固定）
        sf = ctk.CTkFrame(c, fg_color="transparent")
        sf.pack(side="top", fill="x")
        ctk.CTkLabel(sf, text="锁定方式", text_color="gray", anchor="w").pack(fill="x")
        self.mode_var = tk.IntVar(value=cfg.get("mode", 1))
        ctk.CTkRadioButton(sf, text="① 全屏锁定（软）· 遮罩 + 拦截热键",
                           variable=self.mode_var, value=1,
                           command=self._on_mode_change).pack(anchor="w", pady=3)
        # 模式一专属附加项（缩进；选模式二时置灰）。⚠ 新增此类选项时，务必同步到快捷键
        #   （DEFAULT_CONFIG / _save_all / _launch_shortcut / _add_shortcut_dialog / 快捷字典字段）
        self.guard_var = tk.BooleanVar(value=bool(cfg.get("guard", True)))
        self.guard_cb = ctk.CTkCheckBox(sf, text="🛡 防止结束进程（双进程互守）",
                                        variable=self.guard_var, command=self._mark_dirty,
                                        font=(FONT, 12))
        self.guard_cb.pack(anchor="w", padx=(30, 0), pady=(2, 0))
        self.block_tm_var = tk.BooleanVar(value=bool(cfg.get("block_taskmgr", False)))
        self.block_tm_cb = ctk.CTkCheckBox(sf, text="🚫 禁用任务管理器（更强 · 绿色模式会弹一次 UAC）",
                                           variable=self.block_tm_var, command=self._mark_dirty,
                                           font=(FONT, 12))
        self.block_tm_cb.pack(anchor="w", padx=(30, 0), pady=(2, 0))
        ctk.CTkRadioButton(sf, text="② 定时关机（硬）· 时间段内反复自动关机",
                           variable=self.mode_var, value=2,
                           command=self._on_mode_change).pack(anchor="w", pady=(8, 3))
        # 模式二专属附加项（登录前关机；选模式一时置灰）。⚠ 新增此类选项同样要同步到快捷键那几处
        self.preboot_var = tk.BooleanVar(value=bool(cfg.get("mode2_preboot", False)))
        self.preboot_cb = ctk.CTkCheckBox(
            sf, text="🛡 加强防护：登录前关机（更硬 · 绿色模式弹一次 UAC）",
            variable=self.preboot_var, command=self._mark_dirty, font=(FONT, 12))
        self.preboot_cb.pack(anchor="w", padx=(30, 0), pady=(2, 0))
        self.instant_var = tk.BooleanVar(value=bool(cfg.get("mode2_instant", False)))
        self.instant_cb = ctk.CTkCheckBox(
            sf, text="⚡ 开始后立即关机（不留 25 秒缓冲，防中途清数据逃脱）",
            variable=self.instant_var, command=self._mark_dirty, font=(FONT, 12))
        self.instant_cb.pack(anchor="w", padx=(30, 0), pady=(2, 0))
        self._on_mode_change()

        drow = ctk.CTkFrame(sf, fg_color="transparent")
        drow.pack(fill="x", pady=(12, 2))
        ctk.CTkLabel(drow, text="时长(分钟)", text_color="gray").pack(side="left")
        self.minutes_var = tk.StringVar(value=str(cfg.get("minutes", 30)))
        self.minutes_var.trace_add("write", self._mark_dirty)
        ctk.CTkEntry(drow, textvariable=self.minutes_var, width=66,
                     justify="center").pack(side="left", padx=8)
        for m in (15, 30, 60, 90):
            ctk.CTkButton(drow, text=str(m), width=40,
                          command=lambda v=m: self.minutes_var.set(str(v))).pack(side="left", padx=2)

        ctk.CTkLabel(sf, text="自定义快捷（单击一键启动）", text_color="gray",
                     anchor="w").pack(fill="x", pady=(12, 2))
        # 快捷列表：滚动区（多了才滚动，不挤压下方固定按钮）
        self.sc_frame = ctk.CTkScrollableFrame(c, fg_color="transparent")
        self.sc_frame.pack(side="top", fill="both", expand=True)
        self._render_shortcuts()

        self._dirty = False

    # ---- 自定义快捷 ----
    def _sc_label(self, sc):
        return sc.get("label") or f"{'关机' if sc.get('mode') == 2 else '锁定'} {sc.get('minutes')} 分钟"

    def _render_shortcuts(self):
        for w in self.sc_frame.winfo_children():
            w.destroy()
        for i, sc in enumerate(self._shortcuts):
            rowf = ctk.CTkFrame(self.sc_frame, fg_color="transparent")
            rowf.pack(fill="x", pady=2)
            tag = "②" if sc.get("mode") == 2 else "①"
            ctk.CTkButton(rowf, text=f"▶  {tag} {self._sc_label(sc)}", anchor="w",
                          command=lambda s=dict(sc): self._launch_shortcut(s)).pack(
                              side="left", fill="x", expand=True)
            ctk.CTkButton(rowf, text="✕", width=34, fg_color=COL_GRAY,
                          command=lambda idx=i: self._del_shortcut(idx)).pack(side="left", padx=(6, 0))
        ctk.CTkButton(self.sc_frame, text="＋ 添加快捷", fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90"),
                      command=self._add_shortcut_dialog).pack(fill="x", pady=(4, 0))

    def _del_shortcut(self, idx):
        if 0 <= idx < len(self._shortcuts):
            del self._shortcuts[idx]
            self._mark_dirty()
            self._render_shortcuts()

    def _launch_shortcut(self, sc):
        try:
            minutes = int(sc.get("minutes", 30))
        except (ValueError, TypeError):
            return
        mode = 2 if sc.get("mode") == 2 else 1
        # 应用快捷记住的设置（含模式一附加开关）。⚠ 新增模式一选项时，这里也要加一行。
        self.mode_var.set(mode)
        self.minutes_var.set(str(minutes))
        self.guard_var.set(bool(sc.get("guard", True)))
        self.block_tm_var.set(bool(sc.get("block_taskmgr", False)))
        self.preboot_var.set(bool(sc.get("mode2_preboot", False)))
        self.instant_var.set(bool(sc.get("mode2_instant", False)))
        self._save_all()
        if mode == 2:
            self.start_mode2_lock(minutes)
        else:
            self.start_mode1_lock(minutes * 60)

    def _add_shortcut_dialog(self):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("添加快捷")
        _set_icon(dlg)
        dlg.geometry("340x500")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.after(50, dlg.grab_set)  # ctk Toplevel 需稍延迟再抢焦点

        ctk.CTkLabel(dlg, text="标签（可选）").pack(pady=(16, 2))
        label_var = tk.StringVar()
        ctk.CTkEntry(dlg, textvariable=label_var, width=240).pack()
        ctk.CTkLabel(dlg, text="时长（分钟）").pack(pady=(10, 2))
        min_var = tk.StringVar(value=self.minutes_var.get() or "30")
        ctk.CTkEntry(dlg, textvariable=min_var, width=240).pack()
        ctk.CTkLabel(dlg, text="锁定方式").pack(pady=(10, 2))
        d_mode = tk.IntVar(value=self.mode_var.get())
        ctk.CTkRadioButton(dlg, text="① 全屏锁定", variable=d_mode, value=1,
                           command=lambda: _sync()).pack(anchor="w", padx=56, pady=2)
        # 模式一附加开关（缩进在①正下方）—— 新增此类选项时，这里/_launch_shortcut/快捷字典都要同步
        d_guard = tk.BooleanVar(value=bool(self.guard_var.get()))
        d_guard_cb = ctk.CTkCheckBox(dlg, text="🛡 防止结束进程", variable=d_guard, font=(FONT, 12))
        d_guard_cb.pack(anchor="w", padx=82, pady=(2, 0))
        d_block = tk.BooleanVar(value=bool(self.block_tm_var.get()))
        d_block_cb = ctk.CTkCheckBox(dlg, text="🚫 禁用任务管理器", variable=d_block, font=(FONT, 12))
        d_block_cb.pack(anchor="w", padx=82, pady=(2, 0))
        ctk.CTkRadioButton(dlg, text="② 定时关机", variable=d_mode, value=2,
                           command=lambda: _sync()).pack(anchor="w", padx=56, pady=(4, 2))
        d_preboot = tk.BooleanVar(value=bool(self.preboot_var.get()))
        d_preboot_cb = ctk.CTkCheckBox(dlg, text="🛡 加强防护：登录前关机", variable=d_preboot,
                                       font=(FONT, 12))
        d_preboot_cb.pack(anchor="w", padx=82, pady=(2, 0))
        d_instant = tk.BooleanVar(value=bool(self.instant_var.get()))
        d_instant_cb = ctk.CTkCheckBox(dlg, text="⚡ 开始后立即关机", variable=d_instant,
                                       font=(FONT, 12))
        d_instant_cb.pack(anchor="w", padx=82, pady=(2, 0))

        def _sync():
            is1 = d_mode.get() == 1
            self._set_cb_enabled(d_guard_cb, is1)
            self._set_cb_enabled(d_block_cb, is1)
            self._set_cb_enabled(d_preboot_cb, not is1)
            self._set_cb_enabled(d_instant_cb, not is1)
        _sync()

        def confirm():
            try:
                mins = int(min_var.get())
            except (ValueError, tk.TclError):
                messagebox.showerror("错误", "请输入有效的分钟数", parent=dlg)
                return
            if mins < 1:
                messagebox.showerror("错误", "时长至少 1 分钟", parent=dlg)
                return
            self._shortcuts.append({"label": label_var.get().strip(), "minutes": mins,
                                    "mode": d_mode.get(), "guard": bool(d_guard.get()),
                                    "block_taskmgr": bool(d_block.get()),
                                    "mode2_preboot": bool(d_preboot.get()),
                                    "mode2_instant": bool(d_instant.get())})
            self._mark_dirty()
            self._render_shortcuts()
            dlg.destroy()

        ctk.CTkButton(dlg, text="确定添加", command=confirm).pack(pady=16)

    # ---- 收集 / 保存 ----
    def _collect(self):
        try:
            minutes = int(self.minutes_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("错误", "请输入有效的分钟数")
            return None
        if minutes < 1:
            messagebox.showerror("错误", "锁定时长至少 1 分钟")
            return None
        return self.mode_var.get(), minutes

    def _save_all(self):
        got = self._collect()
        if not got:
            return False
        mode, minutes = got
        cfg = load_config()
        cfg["mode"], cfg["minutes"] = mode, minutes
        cfg["guard"] = bool(self.guard_var.get())
        cfg["block_taskmgr"] = bool(self.block_tm_var.get())
        cfg["mode2_preboot"] = bool(self.preboot_var.get())
        cfg["mode2_instant"] = bool(self.instant_var.get())
        cfg["shortcuts"] = self._shortcuts
        save_config(cfg)
        self._dirty = False
        return True

    def on_save(self):
        if self._save_all():
            messagebox.showinfo("已保存", "设置已保存。")

    def on_start(self):
        got = self._collect()
        if not got:
            return
        mode, minutes = got
        self._save_all()
        if mode == 2:
            self.start_mode2_lock(minutes)
        else:
            self.start_mode1_lock(minutes * 60)

    def on_remove_shutdown(self):
        ok, msg = remove_shutdown_task()
        if ok:
            messagebox.showinfo("已解除", "关机计划任务已删除。")
        else:
            messagebox.showerror("解除失败", (msg or "") + "\n若因权限失败，请以管理员身份运行。")
        self.show_main()

    # ---------------- 模式一：全屏锁定 ----------------
    def start_mode1_lock(self, seconds, resumed=False, confirmed=False):
        cfg = load_config()
        block_tm = bool(cfg.get("block_taskmgr", False))
        if not resumed and not confirmed:
            mins = max(1, seconds // 60)
            extra = ("" if is_installed() else
                     "\n（绿色模式：锁定期间重启会自动恢复，结束后自动清除自启）")
            if block_tm and not is_admin():
                extra += "\n（已勾选「禁用任务管理器」：将弹一次 UAC 获取管理员）"
            if not messagebox.askyesno(
                    "确认锁定",
                    f"即将全屏锁定电脑 {mins} 分钟。\n"
                    "锁定期间常用快捷键被拦截，倒计时结束自动解锁。" + extra +
                    "\n\n确定开始吗？"):
                return
        # 需禁用任务管理器但未提权（绿色模式）→ 提权后由新实例接管整个锁定
        if block_tm and not is_admin() and not DRY_RUN and not resumed:
            if relaunch_as_admin(f"--startlock {int(seconds)}"):
                self.root.destroy()
                return
            if not messagebox.askyesno(
                    "未获得管理员权限",
                    "无法禁用任务管理器（需要管理员）。\n是否不禁用、继续锁定？"):
                return
            block_tm = False
        self.resumed = resumed
        cfg["mode"] = 1
        cfg["lock_until"] = time.time() + seconds
        save_config(cfg)
        # 智能自启：仅锁定期间启用。★按「是否提权」而非「是否安装」决定：
        # 提权时用「最高权限」计划任务 → 重启后提权恢复（能重新禁用任务管理器、看门狗更硬）；
        # 非提权（绿色未提权）用 HKCU Run → 重启后非提权恢复。
        if is_admin():
            create_boot_task()
        else:
            set_run_key()

        self._guard_on = bool(cfg.get("guard", True))
        self._block_tm = block_tm
        self.root.withdraw()
        try:
            self.blocker.start()
            self._show_lock_screen(seconds)
            if self._block_tm:
                set_taskmgr_disabled(True)
            if self._guard_on:
                self._start_guard()
        except Exception as ex:
            _log("start_mode1_lock 失败:\n" + traceback.format_exc())
            self.blocker.stop()
            clear_lock_state()
            self.root.deiconify()
            messagebox.showerror("锁定失败", f"启动锁定时出错：\n{ex}\n\n详情见 error.log")
            self.show_main()

    def _show_lock_screen(self, seconds):
        self._end = time.monotonic() + seconds
        w = self.lock_win = tk.Toplevel(self.root)
        _set_icon(w)
        w.attributes("-fullscreen", True)
        w.attributes("-topmost", True)
        w.configure(bg="#0a0a0a")  # 不隐藏光标：锁屏上有「关机」按钮需要点击
        w.protocol("WM_DELETE_WINDOW", lambda: None)
        w.bind("<Key>", lambda e: "break")

        self.clock_lbl = tk.Label(w, text="", fg="#5a5a5a", bg="#0a0a0a",
                                  font=("Consolas", 30))
        self.clock_lbl.pack(pady=(120, 0))
        self.count_lbl = tk.Label(w, text="", fg="#ffffff", bg="#0a0a0a",
                                  font=("Consolas", 110, "bold"))
        self.count_lbl.pack(pady=18)
        btnrow = tk.Frame(w, bg="#0a0a0a")
        btnrow.pack(pady=30)
        tk.Button(btnrow, text="🌙  息屏", font=(FONT, 12),
                  bg="#2a2a2a", fg="#d0d0d0", relief="flat", padx=16, pady=6,
                  activebackground="#3a3a3a", activeforeground="#ffffff",
                  command=self._screen_off).pack(side="left", padx=10)
        tk.Button(btnrow, text="⏻  关机", font=(FONT, 12),
                  bg="#2a2a2a", fg="#d0d0d0", relief="flat", padx=16, pady=6,
                  activebackground="#3a3a3a", activeforeground="#ffffff",
                  command=self._lock_shutdown).pack(side="left", padx=10)

        self._keep_on_top()
        self._tick_clock()
        self._tick_count()
        # 抵消 ctk 启动时的延迟 deiconify：恢复锁定时确保根窗口保持隐藏
        self.root.after(600, self.root.withdraw)

    def _keep_on_top(self):
        if self.lock_win and self.lock_win.winfo_exists():
            if not self._suspend_top:
                self.lock_win.lift()
                self.lock_win.attributes("-topmost", True)
                self.lock_win.focus_force()
            self.lock_win.after(300, self._keep_on_top)

    def _tick_clock(self):
        if self.lock_win and self.lock_win.winfo_exists():
            self.clock_lbl.config(text=time.strftime("%H:%M:%S", time.localtime()))
            self.lock_win.after(1000, self._tick_clock)

    def _tick_count(self):
        if not (self.lock_win and self.lock_win.winfo_exists()):
            return
        remaining = int(round(self._end - time.monotonic()))
        if remaining <= 0:
            self._finish()
            return
        h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
        self.count_lbl.config(text=(f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"))
        self.lock_win.after(250, self._tick_count)

    def _lock_shutdown(self):
        self._suspend_top = True
        try:
            ok = messagebox.askyesno(
                "关机", "确定要关机吗？\n（锁定尚未结束，重启后会自动继续锁定）",
                parent=self.lock_win)
        finally:
            self._suspend_top = False
        if ok:
            self._stopping = True  # 停止看门狗轮询；关机后整机下线，恢复时再互守
            do_shutdown(0, "LockDevice：关机")

    def _screen_off(self):
        """息屏：仅熄灭显示器（防烧屏），不锁屏、不做别的。点击后延迟 1 秒再息屏——
        避免点击那一下的鼠标移动/输入立刻又把屏幕唤醒。息屏后任意鼠标/键盘动作会自然亮屏，
        黑色锁屏与倒计时仍在。"""
        def _off():
            try:
                # 广播 WM_SYSCOMMAND(0x0112) + SC_MONITORPOWER(0xF170)，lParam=2 关显示器；
                # 用带超时的发送，避免个别无响应窗口拖住 GUI 线程。
                ctypes.windll.user32.SendMessageTimeoutW(
                    0xFFFF, 0x0112, 0xF170, 2, 0x0002, 1000, None)
            except Exception:
                pass
        self.root.after(1000, _off)

    # ---- 双进程互守（看门狗 = wscript/vbs，与 python 不同组），仅模式一 ----
    def _spawn_watchdog(self):
        if DRY_RUN:
            print("[DRY] 启动看门狗 (python --watch, 分离进程树)")
            return
        _write_pidfile(_watchdog_pidfile(), 0)   # 先清零，避免旧 pid 触发重复重启
        _spawn_detached("--watch")               # 经中继脱离本进程树；看门狗自己写 pid
        self.watchdog_pid = None
        self.watchdog_proc = None

    def _start_guard(self):
        _write_pidfile(_locker_pidfile(), os.getpid())   # 供 vbs 看门狗监视
        wd = _read_pidfile(_watchdog_pidfile())
        if wd and _process_alive(wd):
            self.watchdog_pid = wd   # 被看门狗拉起：接管现有 vbs
        else:
            self._spawn_watchdog()
        self._watch_tick()

    def _watch_tick(self):
        if self._stopping or not (self.lock_win and self.lock_win.winfo_exists()):
            return
        if self._guard_on:
            wd = _read_pidfile(_watchdog_pidfile())
            if wd > 0:
                if _process_alive(wd):
                    self.watchdog_pid = wd
                else:
                    self._spawn_watchdog()   # 看门狗死了 → 反挂重启（会先清零 pid）
            # wd == 0：看门狗正在启动/尚未写入自己 pid，宽限不重启
        self.lock_win.after(500, self._watch_tick)

    def _stop_guard(self):
        self._stopping = True
        try:
            os.remove(_locker_pidfile())   # vbs 见 locker.pid 消失即自退
        except OSError:
            pass
        _kill_pid(self.watchdog_pid or _read_pidfile(_watchdog_pidfile()))
        try:
            os.remove(_watchdog_pidfile())
        except OSError:
            pass
        self.watchdog_pid = None
        self.watchdog_proc = None

    def _finish(self):
        self._stop_guard()
        self.blocker.stop()
        clear_lock_state()  # 复位 lock_until + 移除临时自启（保留用户设置）
        if self.lock_win and self.lock_win.winfo_exists():
            self.lock_win.destroy()
        self.lock_win = None
        if self.resumed or getattr(self, "oneshot", False):
            self.root.destroy()     # 恢复态 / 一次性锁定（--startlock）：结束即退出，不再弹 tkinter 主界面
        else:
            messagebox.showinfo("完成", "锁定结束，专注辛苦啦！🎉")
            self.show_main()

    # ---------------- 模式二：定时关机 ----------------
    def start_mode2_lock(self, minutes, preboot=None, instant=None, confirmed=False):
        _c = load_config()
        if preboot is None:
            preboot = bool(_c.get("mode2_preboot", False))
        if instant is None:
            instant = bool(_c.get("mode2_instant", False))
        if not confirmed:
            first = ("【立即关机、不留缓冲——请确保文件已保存！】" if instant
                     else f"约 {SHUTDOWN_DELAY} 秒后关机（留出保存文件的时间）")
            if preboot:
                when = f"2. 未来 {minutes} 分钟内，【每次开机在登录前就自动关机】"
                extra = ("\n（登录前关机需管理员创建 SYSTEM 任务；绿色模式会弹一次 UAC）"
                         if not is_admin() else "")
            else:
                when = f"2. 未来 {minutes} 分钟内，【每次登录后自动关机】"
                extra = ("\n（登录后关机：无需管理员、不弹 UAC；但登录后才触发，"
                         "可被换账户/及时解除绕过，拦截弱于「登录前」）")
            if not messagebox.askyesno(
                    "⚠️ 高风险确认",
                    f"【定时关机 · {'登录前' if preboot else '登录后'}{' · 立即' if instant else ''}】将会：\n\n"
                    f"1. {first}\n"
                    f"{when}\n"
                    f"3. 时间到后自动解除\n\n"
                    f"⚠️ 期间几乎无法使用电脑。紧急恢复：开机进入安全模式，\n"
                    f"   运行本程序点『解除/卸载』。" + extra + "\n\n确定继续吗？"):
                return

        # 登录前 = SYSTEM 任务，需管理员；绿色未提权 → 提权后一步直达（--startshutdown）
        if preboot and not is_admin() and not DRY_RUN:
            if messagebox.askyesno(
                    "需要管理员权限",
                    "「登录前关机」需要管理员权限来创建 SYSTEM 计划任务。\n"
                    "（安装到本机后即可免此步）\n\n是否以管理员身份继续？"):
                if relaunch_as_admin(f"--startshutdown {int(minutes)}"):
                    self.root.destroy()
                    return
            if not messagebox.askyesno(
                    "未获得管理员权限",
                    "无法创建「登录前关机」（需要管理员）。\n"
                    "是否改用「登录后关机」（较弱、但无需管理员）继续？"):
                return
            preboot = False

        end = time.time() + minutes * 60
        ok, msg = create_shutdown_task(end, preboot)
        if not ok:
            messagebox.showerror("创建计划任务失败", msg or "未知错误")
            return
        cfg = load_config()
        cfg["mode"] = 2
        cfg["lock_until"] = end
        save_config(cfg)
        kind = "登录前" if preboot else "登录后"
        delay = 0 if instant else SHUTDOWN_DELAY
        if not instant:
            messagebox.showinfo(
                "已启动定时关机",
                f"已创建「{kind}关机」计划，电脑将在约 {SHUTDOWN_DELAY} 秒后关机。\n"
                f"未来 {minutes} 分钟内每次{'开机(登录前)' if preboot else '登录后'}自动关机，到点自动解除。\n\n专注学习吧！🎯")
        do_shutdown(delay, "LockDevice 专注锁定：电脑即将关机，请保存文件")
        self.root.destroy()

    # ---------------- 恢复（开机自启） ----------------
    def resume_or_exit(self):
        cfg = load_config()
        lu = cfg.get("lock_until")
        if cfg.get("mode", 1) == 1 and lu and time.time() < lu:
            self.start_mode1_lock(int(lu - time.time()), resumed=True)
            self.run()
        else:
            # 无活跃锁定：让 vbs 看门狗自退并清理 pid 文件
            try:
                os.remove(_locker_pidfile())
            except OSError:
                pass
            _kill_pid(_read_pidfile(_watchdog_pidfile()))
            try:
                os.remove(_watchdog_pidfile())
            except OSError:
                pass
            clear_lock_state()  # 复位残留运行态（保留设置）
        # 模式二由关机任务负责


# ------------------------------------------------------------------ 入口
def main():
    argv = sys.argv[1:]
    _hide_console()
    _log(f"launch argv={argv} exe={sys.executable} HAS_CTK={HAS_CTK} "
         f"admin={is_admin()} installed={is_installed()}")

    if "--guard" in argv:
        try:
            epoch = float(argv[argv.index("--guard") + 1])
        except (IndexError, ValueError):
            sys.exit(1)
        run_guard(epoch)
        return

    if "--relay" in argv:
        # 中继：立即拉起目标并退出，使目标脱离本进程树（Unicode 安全，无 cmd）
        try:
            subprocess.Popen(_app_cmd(*argv[argv.index("--relay") + 1:]),
                             creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass
        return

    if "--watch" in argv:
        run_watchdog()
        return

    if "--print-xml" in argv:
        try:
            mins = int(argv[argv.index("--print-xml") + 1])
        except (IndexError, ValueError):
            mins = 30
        print(build_shutdown_xml(mins)[0])
        return

    if "--install" in argv:
        opts = load_install_opts()
        ok, msg = do_install(opts.get("dir"), opts.get("desktop", True), opts.get("launch", True))
        clear_install_opts()
        _dialog("安装", msg, "info" if ok else "error")
        return

    if "--uninstall" in argv:
        if not is_admin() and not DRY_RUN:
            if not relaunch_as_admin("--uninstall"):
                _dialog("卸载", "未获得管理员权限，卸载取消。", "warn")
            return
        ok, msg = do_uninstall()
        _dialog("卸载", msg, "info" if ok else "error")
        return

    if "--cleardata" in argv:   # 提权清除（含删除上了 ACL 锁的受保护缓存）
        removed = clear_data()
        _dialog("清除数据",
                "已清除：\n" + ("\n".join(removed) if removed else "（没有需要清除的数据）"), "info")
        return

    if "--resume" in argv:
        watched_by = None
        if "--watched-by" in argv:
            try:
                watched_by = int(argv[argv.index("--watched-by") + 1])
            except (IndexError, ValueError):
                watched_by = None
        app = App()
        app.watchdog_pid = watched_by
        app.resume_or_exit()
        return

    if "--startlock" in argv:
        try:
            secs = int(argv[argv.index("--startlock") + 1])
        except (IndexError, ValueError):
            return
        app = App()
        app.oneshot = True          # 一次性锁定（Qt/自启/计划任务拉起）：结束后进程退出，不弹 tkinter 界面
        app.start_mode1_lock(secs, confirmed=True)
        app.run()
        return

    if "--startshutdown" in argv:   # 提权后一步直达：直接创建「登录前关机」计划
        try:
            mins = int(argv[argv.index("--startshutdown") + 1])
        except (IndexError, ValueError):
            return
        app = App()
        app.root.withdraw()
        app.start_mode2_lock(mins, preboot=True, confirmed=True)
        return

    if "--plugin-boot" in argv:   # 插件开机自启任务触发 → 调各声明需要自启的插件 on_boot
        api = _build_plugin_api(None)
        for pid in load_config().get("plugins_autostart", []):
            if plugin_disabled(pid):
                continue
            _m, mod = _find_plugin(pid)
            if mod is not None and hasattr(mod, "on_boot"):
                try:
                    mod.on_boot(api)
                except Exception:
                    _log("plugin on_boot 失败 " + str(pid) + "\n" + traceback.format_exc())
        return

    if "--plugin" in argv:   # 计划任务回调路由：--plugin <id> [...] → 插件 handle_cli
        try:
            pid = argv[argv.index("--plugin") + 1]
        except IndexError:
            return
        _m, mod = _find_plugin(pid)
        if mod is not None and hasattr(mod, "handle_cli"):
            try:
                mod.handle_cli(argv, _build_plugin_api(None))
            except Exception:
                _log("plugin handle_cli 失败 " + str(pid) + "\n" + traceback.format_exc())
        return

    if "--list-plugins" in argv:   # 诊断：打印已识别插件（也用于验证冻结态 _MEIPASS 加载）
        for meta, _mod in load_plugins():
            print(f"{meta.get('id')}\t{meta.get('name', '')}\tv{meta.get('version', '')}")
        return

    if "--gui-mode" in argv:       # 诊断：打印将采用的界面（qt / tk），验证冻结态自动切换
        print("qt" if _qt_available() else "tk")
        return

    if "--selftest" in argv:       # 诊断：离屏构造 Qt 主窗口，验证瘦身后 Qt 库/qfluentwidgets 资源齐全（无需显示器）
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            from gui.app import MainWindow
            _app = QApplication.instance() or QApplication([])
            _w = MainWindow()
            print("GUI_OK", _w.metaObject().className())
        except Exception as _e:
            print("GUI_FAIL:", repr(_e))
        return

    # --open（提权打开）或无参数：显示启动器
    tidy_portable_leftovers()
    set_taskmgr_disabled(False)  # 未在锁定中：确保任务管理器可用（含崩溃恢复）
    # 打开「本体」时若已安装但未提权 → 交给已安装的最高权限任务打开（免 UAC）：
    #  · 正常同版本：转交已安装任务打开后退出（免 UAC）。
    #  · 当前是更高版本（可更新）：同样转交已安装任务免 UAC 打开「已安装的旧版」，
    #    再由本进程（新版、未提权）弹一个「发现更新」窗（更新日志 + 更新按钮）。
    #    → 平时启动新版文件零 UAC；只有点「更新」才提权覆盖。免 UAC 打开的始终是
    #    已安装的可信 exe（非本新文件），故不构成「借权限跑任意文件」的提权漏洞。
    if "--open" not in argv and is_installed() and not is_admin() and not DRY_RUN:
        if has_update() and load_config().get("skip_version") != VERSION:
            # 新版文件：免 UAC 打开已安装版启动器，并「同时」弹独立「发现更新」窗——两窗并存，
            # 不再要求先关更新窗才出启动器。启动器是另一个（已提权）进程，先拉起它；
            # 「发现更新」窗随后多抢几次前台，稳定叠在启动器之上（见 show_update_window）。
            _run(["schtasks", "/run", "/tn", TASK_OPEN])
            if HAS_CTK:
                app = App()
                app.show_update_window()
                app.run()
            return
        # 正常同版本 / 已「跳过此版本」：转交已安装任务打开后退出（免 UAC，不再弹更新窗）
        if _run(["schtasks", "/run", "/tn", TASK_OPEN]).returncode == 0:
            return
    if _qt_available():   # 有 gui 文件夹 + PySide6/qfluentwidgets → 用 Qt 现代界面
        try:
            from gui.app import run as _qt_run
            _qt_run()
            return
        except Exception:
            _log("Qt 界面启动失败，回退 tkinter：\n" + traceback.format_exc())
    if not HAS_CTK:
        _dialog("需要 customtkinter",
                "本程序界面需要 customtkinter。\n请运行：\n\n    pip install customtkinter\n\n安装后重新打开。",
                "error")
        return
    app = App()
    app.show_launcher()
    app.run()


if __name__ == "__main__":
    def _excepthook(t, v, tb):
        _log("UNCAUGHT:\n" + "".join(traceback.format_exception(t, v, tb)))
        sys.__excepthook__(t, v, tb)
    sys.excepthook = _excepthook
    main()
