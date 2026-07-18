# -*- coding: utf-8 -*-
"""LockDevice 插件 · 自动锁机 auto_lock v1.0.0（最小版）

每天固定时间自动锁机一段时长：建一个「每日触发」计划任务，到点复用本体的全屏锁定
（--startlock）。本插件**只写后端 + 声明前端**（PLUGIN / SETTINGS / ACTIONS 都是纯数据），
界面完全由本体按声明渲染——不 import 本体、不碰任何 GUI 组件（本体日后从 tkinter 换 Qt
本插件零改动）。

它靠自己建的每日计划任务持久（重启后照常触发），所以 autostart=False——即「不需要本体开机自启」
的示例。后续方向：跳过节假日、节假日特设、按周循环、按月循环。
"""

PLUGIN = {
    "id": "auto_lock",
    "name": "自动锁机",
    "version": "1.0.0",
    "button": "⏰  自动锁机",
    "autostart": False,   # 靠自建的每日计划任务持久，不需要本体开机自启
}

# 前端声明：本体据此渲染统一表单
SETTINGS = [
    {"key": "enabled", "label": "启用每日自动锁机", "type": "bool", "default": False},
    {"key": "time",    "label": "每天锁机时间 (HH:MM)", "type": "str", "default": "22:00"},
    {"key": "minutes", "label": "锁机时长（分钟）", "type": "int", "default": 30},
]

# 前端声明：本体渲染成按钮，点击调下面同名后端函数
ACTIONS = [
    {"label": "🔒  立即锁一次", "fn": "lock_now"},
]

_TASK = "LockDevice_Plugin_autolock"


def _parse_hhmm(s):
    try:
        hh, mm = str(s).strip().split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        pass
    return None


def _minutes(vals):
    try:
        return max(1, int(vals.get("minutes", 30)))
    except (ValueError, TypeError):
        return 30


def on_settings_saved(api, values):
    """保存设置后：启用 → 建/更新每日任务；停用 → 删除。"""
    if not values.get("enabled"):
        api.delete_task(_TASK)
        return
    hhmm = _parse_hhmm(values.get("time", "22:00"))
    if not hhmm:
        api.error("锁机时间格式应为 HH:MM（如 22:00）。")
        return
    minutes = _minutes(values)
    ok, msg = api.register_task(_TASK, api.daily_trigger(*hhmm), api.lock_command(minutes),
                                desc="LockDevice 自动锁机（每日定时）")
    if ok:
        api.info(f"已设定：每天 {hhmm[0]:02d}:{hhmm[1]:02d} 自动全屏锁定 {minutes} 分钟。")
    else:
        api.error("创建每日锁机任务失败：\n" + (msg or "未知错误"))


def on_uninstall(api):
    api.delete_task(_TASK)


def lock_now(api):
    """立即锁一次（时长取当前配置，默认 30 分钟）。"""
    minutes = _minutes(api.get_settings("auto_lock"))
    if api.confirm(f"立即全屏锁定 {minutes} 分钟？"):
        api.start_lock(minutes)
