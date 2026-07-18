# -*- coding: utf-8 -*-
"""LockDevice · PySide6 + qfluentwidgets 界面（Fluent 风格）—— 界面重构，迁移中。

复用本体 lock_device 的后端（配置 / 计划任务 / 插件 / 锁机），只重写前端。
当前为迁移基座：Home（专注锁定）+ 设置（按插件声明式渲染）+ 关于 已可用；
锁屏 Qt 化、各对话框、打包切换等见 docs/GUI_QT_MIGRATION.md。

注：本体的锁机能力通过复用现有 CLI（--startlock / --open）驱动，前后端解耦。
"""
import sys
import subprocess

from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout)
from qfluentwidgets import (FluentWindow, NavigationItemPosition, FluentIcon as FIF,
                            setTheme, Theme, TitleLabel, SubtitleLabel, BodyLabel,
                            PrimaryPushButton, SpinBox, SwitchButton, ComboBox, LineEdit,
                            InfoBar, InfoBarPosition, ScrollArea)

import lock_device as core   # 复用本体后端（源码态可直接 import；不触发 main）

_CREATE_NO_WINDOW = 0x08000000


def _spawn(*args):
    """脱离本进程拉起本体做某事（复用现有 CLI，如 --startlock）。"""
    exe = core._self_path()
    cmd = [exe, *args] if getattr(sys, "frozen", False) else [core._pythonw_path(), exe, *args]
    subprocess.Popen(cmd, creationflags=_CREATE_NO_WINDOW)


def _scroll(name):
    area = ScrollArea()
    area.setObjectName(name)
    w = QWidget()
    area.setWidget(w)
    area.setWidgetResizable(True)
    v = QVBoxLayout(w)
    v.setContentsMargins(36, 24, 36, 24)
    v.setSpacing(14)
    return area, v


def _row(v, label, widget):
    r = QHBoxLayout()
    r.addWidget(BodyLabel(label))
    r.addStretch(1)
    r.addWidget(widget)
    v.addLayout(r)
    return widget


class HomeInterface(ScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("home")
        w = QWidget()
        self.setWidget(w)
        self.setWidgetResizable(True)
        v = QVBoxLayout(w)
        v.setContentsMargins(36, 24, 36, 24)
        v.setSpacing(14)
        cfg = core.load_config()

        v.addWidget(TitleLabel("专注锁定"))
        self.mode = ComboBox()
        self.mode.addItems(["① 全屏锁定（软）", "② 定时关机（硬）"])
        self.mode.setCurrentIndex(1 if cfg.get("mode") == 2 else 0)
        _row(v, "锁定方式", self.mode)

        self.minutes = SpinBox()
        self.minutes.setRange(1, 24 * 60)
        self.minutes.setValue(int(cfg.get("minutes", 30) or 30))
        _row(v, "时长（分钟）", self.minutes)

        self.guard = SwitchButton()
        self.guard.setChecked(bool(cfg.get("guard", True)))
        _row(v, "防止结束进程（双进程互守）", self.guard)

        self.block = SwitchButton()
        self.block.setChecked(bool(cfg.get("block_taskmgr", False)))
        _row(v, "禁用任务管理器", self.block)

        v.addStretch(1)
        start = PrimaryPushButton("🔒  开始锁定")
        start.clicked.connect(self._start)
        v.addWidget(start)

    def _start(self):
        cfg = core.load_config()
        mode = 2 if self.mode.currentIndex() == 1 else 1
        minutes = int(self.minutes.value())
        cfg.update({"mode": mode, "minutes": minutes,
                    "guard": self.guard.isChecked(), "block_taskmgr": self.block.isChecked()})
        core.save_config(cfg)
        if mode == 1:
            _spawn("--startlock", str(minutes * 60))
            InfoBar.success("已开始", f"全屏锁定 {minutes} 分钟", parent=self.win,
                            position=InfoBarPosition.TOP)
        else:
            _spawn("--open")   # 定时关机暂走现有确认流程（Qt 版稍后接管）
            InfoBar.info("定时关机", "请在弹出的窗口中确认", parent=self.win,
                         position=InfoBarPosition.TOP)


class SettingsInterface(ScrollArea):
    """按各插件声明的 SETTINGS 渲染 Fluent 控件——声明式前端让迁移零成本。"""
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("settings")
        w = QWidget()
        self.setWidget(w)
        self.setWidgetResizable(True)
        self.v = QVBoxLayout(w)
        self.v.setContentsMargins(36, 24, 36, 24)
        self.v.setSpacing(12)
        self.v.addWidget(TitleLabel("设置"))
        self._fields = []   # (pid, key, type, getter)
        cfg = core.load_config()
        plugins = [(m, mod) for m, mod in core.load_plugins() if getattr(mod, "SETTINGS", None)]
        if not plugins:
            self.v.addWidget(BodyLabel("（暂无可配置的插件）"))
        for meta, mod in plugins:
            pid = meta["id"]
            vals = cfg.get("plugins", {}).get(pid, {})
            self.v.addWidget(SubtitleLabel(meta.get("name", pid)))
            for f in mod.SETTINGS:
                self._field(pid, f, vals)
        self.v.addStretch(1)
        save = PrimaryPushButton("💾  保存")
        save.clicked.connect(self._save)
        self.v.addWidget(save)

    def _field(self, pid, f, vals):
        key, ftype = f["key"], f.get("type", "str")
        cur = vals.get(key, f.get("default"))
        if ftype == "bool":
            wdg = SwitchButton()
            wdg.setChecked(bool(cur))
            getter = wdg.isChecked
        elif ftype == "choice":
            wdg = ComboBox()
            opts = [str(o) for o in f.get("options", [])]
            wdg.addItems(opts)
            if cur is not None and str(cur) in opts:
                wdg.setCurrentText(str(cur))
            getter = wdg.currentText
        else:
            wdg = LineEdit()
            wdg.setText("" if cur is None else str(cur))
            wdg.setFixedWidth(180)
            getter = wdg.text
        _row(self.v, f.get("label", key), wdg)
        self._fields.append((pid, key, ftype, getter))

    def _save(self):
        cfg = core.load_config()
        cfg.setdefault("plugins", {})
        touched = {}
        for pid, key, ftype, getter in self._fields:
            v = getter()
            if ftype == "int":
                try:
                    v = int(str(v).strip())
                except (ValueError, TypeError):
                    v = 0
            touched.setdefault(pid, {})[key] = v
        for pid, vals in touched.items():
            m = dict(cfg["plugins"].get(pid, {}))
            m.update(vals)
            cfg["plugins"][pid] = m
        core.save_config(cfg)
        api = core._build_plugin_api(None)
        for meta, mod in core.load_plugins():
            if meta["id"] in touched and hasattr(mod, "on_settings_saved"):
                try:
                    mod.on_settings_saved(api, dict(cfg["plugins"].get(meta["id"], {})))
                except Exception:
                    pass
        InfoBar.success("已保存", "设置已保存", parent=self.win, position=InfoBarPosition.TOP)


class AboutInterface(ScrollArea):
    def __init__(self, win):
        super().__init__()
        self.setObjectName("about")
        w = QWidget()
        self.setWidget(w)
        self.setWidgetResizable(True)
        v = QVBoxLayout(w)
        v.setContentsMargins(36, 24, 36, 24)
        v.setSpacing(10)
        v.addWidget(TitleLabel("LockDevice · 专注锁定"))
        v.addWidget(BodyLabel(f"版本 v{core.VERSION}"))
        v.addWidget(BodyLabel("界面正在从 tkinter 迁移到 PySide6 + qfluentwidgets。"))
        v.addWidget(BodyLabel("插件采用声明式前端，迁移零改动。详见 docs/GUI_QT_MIGRATION.md。"))
        v.addStretch(1)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LockDevice · 专注锁定")
        self.resize(920, 640)
        self.home = HomeInterface(self)
        self.settings = SettingsInterface(self)
        self.about = AboutInterface(self)
        self.addSubInterface(self.home, FIF.HOME, "专注锁定")
        self.addSubInterface(self.settings, FIF.SETTING, "设置", NavigationItemPosition.BOTTOM)
        self.addSubInterface(self.about, FIF.INFO, "关于", NavigationItemPosition.BOTTOM)


def run():
    setTheme(Theme.DARK)
    app = QApplication.instance() or QApplication(sys.argv)
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    run()
