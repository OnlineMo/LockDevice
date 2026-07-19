# -*- coding: utf-8 -*-
"""LockDevice 插件 · 自动锁机 auto_lock v1.0.1（时间窗口版）

设定「每天 HH:MM 起、锁 N 分钟」= 一个每日时间窗口 [start, start+N)。
**由插件在每次登录时自己检查**（本体的插件开机自启机制回调 on_boot）：
- 当前在窗口内 → 锁「剩余时间」（迟到开机只锁剩下的）；
- 已过窗口 → 不锁。
不用 Windows 定时任务在固定点直接触发固定时长的锁定（那样迟到开机会锁满 N 分钟、过点还会锁，都错）。

因此本插件 **需要开机自启**（autostart=True）：启用时向本体登记，登录时被回调检查窗口。
只写后端 + 声明前端（SETTINGS/ACTIONS 纯数据），不 import 本体、不碰 GUI。
后续方向：跳过节假日、节假日特设、按周 / 按月。
"""
import time

PLUGIN = {
    "id": "auto_lock",
    "name": "自动锁机",
    "version": "1.0.1",
    "button": "⏰  自动锁机",
    "autostart": True,   # 需要：每次登录检查时间窗口、锁剩余时间
}

SETTINGS = [
    {"key": "enabled", "label": "启用每日自动锁机", "type": "bool", "default": False},
    {"key": "time",    "label": "每天开始时间 (HH:MM)", "type": "str", "default": "22:00"},
    {"key": "minutes", "label": "锁机时长（分钟）", "type": "int", "default": 30},
]

ACTIONS = [
    {"label": "🔒  立即锁一次", "fn": "lock_now"},
]


def _window(vals):
    """解析出 (起始当天分钟数, 时长分钟)；非法返回 None。"""
    try:
        hh, mm = map(int, str(vals.get("time", "22:00")).strip().split(":"))
        dur = max(1, int(vals.get("minutes", 30)))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 60 + mm, dur
    except Exception:
        pass
    return None


def _remaining(vals):
    """现在若在今天的窗口内，返回剩余分钟；否则 None。"""
    w = _window(vals)
    if not w:
        return None
    start, dur = w
    lt = time.localtime()
    now = lt.tm_hour * 60 + lt.tm_min
    end = start + dur
    return (end - now) if (start <= now < end) else None


def on_settings_saved(api, values):
    """保存设置：启用 → 登记开机自启（登录时 on_boot 检查窗口）；停用 → 注销。不建定时触发任务。"""
    enabled = bool(values.get("enabled"))
    api.set_autostart("auto_lock", enabled)
    w = _window(values)
    if enabled and w:
        api.info(f"已启用：每天 {w[0] // 60:02d}:{w[0] % 60:02d} 起锁 {w[1]} 分钟。\n"
                 f"在此时段内开机会自动锁定「剩余时间」；过点开机则不锁。")
    elif enabled:
        api.error("开始时间格式应为 HH:MM（如 22:00）。")
    else:
        api.info("已停用每日自动锁机。")


def on_boot(api):
    """每次登录被本体回调：在窗口内就锁「剩余时间」。"""
    vals = api.get_settings("auto_lock")
    if not vals.get("enabled"):
        return
    rem = _remaining(vals)
    if rem:
        api.log(f"[auto_lock] 在窗口内，锁定剩余 {rem} 分钟")
        api.start_lock(rem)


def on_uninstall(api):
    api.set_autostart("auto_lock", False)


def lock_now(api):
    """立即锁一次（整段时长，默认 30 分钟）。"""
    try:
        m = max(1, int(api.get_settings("auto_lock").get("minutes", 30)))
    except (ValueError, TypeError):
        m = 30
    if api.confirm(f"立即全屏锁定 {m} 分钟？"):
        api.start_lock(m)
