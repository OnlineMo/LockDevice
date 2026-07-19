# -*- coding: utf-8 -*-
"""LockDevice · PySide6 + qfluentwidgets 界面（Fluent 风格）。

复用本体 lock_device 的后端（配置 / 计划任务 / 插件 / 锁机 / 安装卸载），只重写前端。
tkinter 版仍保留在 lock_device.py（可单文件独立运行）；本 Qt 版为增强前端。

导航：专注锁定、每个启用的插件各一个入口、插件（开关管理）、设置（安装/卸载/清除/更新/关于）。
锁屏 Qt 化见 docs/GUI_QT_MIGRATION.md（下一步）。
"""
import os
import sys
import time
import subprocess

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (FluentWindow, NavigationItemPosition, FluentIcon as FIF,
                            setTheme, Theme, TitleLabel, SubtitleLabel, BodyLabel,
                            PrimaryPushButton, PushButton, SpinBox, SwitchButton, ComboBox,
                            LineEdit, InfoBar, InfoBarPosition, ScrollArea, MessageBox,
                            SettingCardGroup, SwitchSettingCard, PushSettingCard,
                            PrimaryPushSettingCard)

_main = sys.modules.get("__main__")
if _main is not None and hasattr(_main, "load_plugins") and hasattr(_main, "_build_plugin_api"):
    core = _main                    # 由 lock_device.py 作入口启动时直接复用它（不重复导入本体）
else:
    import lock_device as core      # 独立导入 gui 时

_CREATE_NO_WINDOW = 0x08000000


def _spawn(*args):
    exe = core._self_path()
    cmd = [exe, *args] if getattr(sys, "frozen", False) else [core._pythonw_path(), exe, *args]
    subprocess.Popen(cmd, creationflags=_CREATE_NO_WINDOW)


def _themed_body(area, name):
    area.setObjectName(name)
    area.setWidgetResizable(True)
    try:
        area.enableTransparentBackground()
    except Exception:
        pass
    area.setStyleSheet("QScrollArea{border:none;background:transparent}")
    try:
        area.viewport().setStyleSheet("background:transparent")
    except Exception:
        pass
    view = QWidget()
    view.setObjectName(name + "View")
    view.setStyleSheet(f"#{name}View{{background:transparent}}")
    area.setWidget(view)
    lay = QVBoxLayout(view)
    lay.setContentsMargins(36, 24, 36, 24)
    lay.setSpacing(14)
    return lay


def _row(v, label, widget):
    r = QHBoxLayout()
    r.addWidget(BodyLabel(label))
    r.addStretch(1)
    r.addWidget(widget)
    v.addLayout(r)
    return widget


def _field(v, store, pid, f, vals):
    """按声明渲染一个设置控件，把 (pid,key,type,getter) 追加进 store。"""
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
    _row(v, f.get("label", key), wdg)
    store.append((pid, key, ftype, getter))


def _save_fields(win, fields):
    """把 fields 的值写回 config（按插件分区）并回调 on_settings_saved。"""
    cfg = core.load_config()
    cfg.setdefault("plugins", {})
    touched = {}
    for pid, key, ftype, getter in fields:
        val = getter()
        if ftype == "int":
            try:
                val = int(str(val).strip())
            except (ValueError, TypeError):
                val = 0
        touched.setdefault(pid, {})[key] = val
    for pid, vals in touched.items():
        m = dict(cfg["plugins"].get(pid, {}))
        m.update(vals)
        cfg["plugins"][pid] = m
    core.save_config(cfg)
    for meta, mod in core.load_plugins():
        if meta["id"] in touched and hasattr(mod, "on_settings_saved"):
            try:
                mod.on_settings_saved(win.plugin_api, dict(cfg["plugins"].get(meta["id"], {})))
            except Exception:
                core._log("on_settings_saved 失败\n" + core.traceback.format_exc())
    InfoBar.success("已保存", "设置已保存", parent=win, position=InfoBarPosition.TOP)


# ---------------------------------------------------------------- 专注锁定
class HomeInterface(ScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = _themed_body(self, "home")
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

        grp = SettingCardGroup("附加选项")
        self.guard = SwitchSettingCard(FIF.PEOPLE, "防止结束进程", "双进程互守，结束其一另一个立即拉起")
        self.block = SwitchSettingCard(FIF.HIDE, "禁用任务管理器", "锁定期间任务管理器打不开（绿色模式弹一次 UAC）")
        self.preboot = SwitchSettingCard(FIF.CERTIFICATE, "加强防护 · 登录前关机", "SYSTEM + 开机触发，登录前就关（更硬）")
        self.instant = SwitchSettingCard(FIF.POWER_BUTTON, "开始后立即关机", "不留 25 秒缓冲，开始即关")
        self.guard.switchButton.setChecked(bool(cfg.get("guard", True)))
        self.block.switchButton.setChecked(bool(cfg.get("block_taskmgr", False)))
        self.preboot.switchButton.setChecked(bool(cfg.get("mode2_preboot", False)))
        self.instant.switchButton.setChecked(bool(cfg.get("mode2_instant", False)))
        for c in (self.guard, self.block, self.preboot, self.instant):
            grp.addSettingCard(c)
        v.addWidget(grp)
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()

        v.addStretch(1)
        start = PrimaryPushButton("🔒  开始锁定")
        start.clicked.connect(self._start)
        v.addWidget(start)

    def _sync(self):
        m1 = self.mode.currentIndex() == 0
        self.guard.setEnabled(m1)
        self.block.setEnabled(m1)
        self.preboot.setEnabled(not m1)
        self.instant.setEnabled(not m1)

    def _start(self):
        cfg = core.load_config()
        cfg.update({
            "mode": 2 if self.mode.currentIndex() == 1 else 1,
            "minutes": int(self.minutes.value()),
            "guard": self.guard.switchButton.isChecked(),
            "block_taskmgr": self.block.switchButton.isChecked(),
            "mode2_preboot": self.preboot.switchButton.isChecked(),
            "mode2_instant": self.instant.switchButton.isChecked(),
        })
        core.save_config(cfg)
        minutes = cfg["minutes"]
        if cfg["mode"] == 1:
            _spawn("--startlock", str(minutes * 60))
            InfoBar.success("已开始", f"全屏锁定 {minutes} 分钟", parent=self.win,
                            position=InfoBarPosition.TOP)
        else:
            self._start_mode2(minutes, cfg["mode2_preboot"], cfg["mode2_instant"])

    def _start_mode2(self, minutes, preboot, instant):
        kind = "登录前" if preboot else "登录后"
        first = "立即关机、不留缓冲" if instant else f"约 {core.SHUTDOWN_DELAY} 秒后关机"
        box = MessageBox(
            "⚠️ 高风险确认",
            f"【定时关机 · {kind}】将会：\n1. {first}（请先保存文件）\n"
            f"2. 未来 {minutes} 分钟内每次{'开机(登录前)' if preboot else '登录后'}自动关机\n"
            f"3. 到点自动解除\n\n紧急恢复：开机进安全模式解除。确定继续吗？", self.win)
        if not box.exec():
            return
        if preboot and not core.is_admin() and not core.DRY_RUN:
            if core.relaunch_as_admin(f"--startshutdown {minutes}"):
                self.win.close()
            return
        end = time.time() + minutes * 60
        ok, msg = core.create_shutdown_task(end, preboot)
        if not ok:
            InfoBar.error("创建失败", msg or "未知错误", parent=self.win, position=InfoBarPosition.TOP)
            return
        cfg = core.load_config()
        cfg["mode"] = 2
        cfg["lock_until"] = end
        core.save_config(cfg)
        InfoBar.success("已启动", f"「{kind}关机」已设定", parent=self.win, position=InfoBarPosition.TOP)
        core.do_shutdown(0 if instant else core.SHUTDOWN_DELAY, "LockDevice：电脑即将关机，请保存文件")


# ---------------------------------------------------------------- 每个插件一页
class PluginPageInterface(ScrollArea):
    def __init__(self, win, meta, mod):
        super().__init__()
        self.win = win
        self.meta = meta
        self.mod = mod
        v = _themed_body(self, "plugin_" + meta["id"])
        v.addWidget(TitleLabel(meta.get("name", meta["id"])))
        v.addWidget(BodyLabel(f"v{meta.get('version', '')}"))
        self._fields = []
        vals = core.load_config().get("plugins", {}).get(meta["id"], {})
        for f in getattr(mod, "SETTINGS", []):
            _field(v, self._fields, meta["id"], f, vals)
        for act in getattr(mod, "ACTIONS", []) or []:
            fn = getattr(mod, act.get("fn", ""), None)
            if callable(fn):
                b = PushButton(act.get("label", act.get("fn", "")))
                b.clicked.connect(lambda _=False, f=fn: self._action(f))
                v.addWidget(b)
        v.addStretch(1)
        if getattr(mod, "SETTINGS", None):
            save = PrimaryPushButton("💾  保存")
            save.clicked.connect(lambda: _save_fields(self.win, self._fields))
            v.addWidget(save)

    def _action(self, fn):
        try:
            fn(self.win.plugin_api)
        except Exception:
            core._log("plugin action 失败\n" + core.traceback.format_exc())


# ---------------------------------------------------------------- 插件管理（开关）
class PluginManageInterface(ScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = _themed_body(self, "pluginmanage")
        v.addWidget(TitleLabel("插件"))
        v.addWidget(BodyLabel("开关启用 / 关闭插件（关闭后不加载运行、开机也不唤醒；侧栏入口重启后更新）"))
        allp = core.load_plugins()
        if not allp:
            v.addWidget(BodyLabel("（plugins/ 下暂无插件）"))
        else:
            grp = SettingCardGroup("已安装插件")
            dis = core.load_config().get("plugins_disabled", [])
            for meta, mod in allp:
                pid = meta["id"]
                card = SwitchSettingCard(FIF.APPLICATION, meta.get("name", pid),
                                         f"v{meta.get('version', '')} · {pid}")
                card.switchButton.setChecked(pid not in dis)
                card.switchButton.checkedChanged.connect(
                    lambda on, mt=meta, md=mod: self._toggle(mt, md, on))
                grp.addSettingCard(card)
            v.addWidget(grp)
        v.addStretch(1)

    def _toggle(self, meta, mod, on):
        pid = meta["id"]
        cfg = core.load_config()
        dis = [x for x in cfg.get("plugins_disabled", []) if x != pid]
        api = self.win.plugin_api
        if on:
            cfg["plugins_disabled"] = dis
            core.save_config(cfg)
            if hasattr(mod, "on_settings_saved"):
                try:
                    mod.on_settings_saved(api, dict(cfg.get("plugins", {}).get(pid, {})))
                except Exception:
                    pass
            self.win.add_plugin_nav(meta, mod)      # 立即加回侧栏入口
        else:
            dis.append(pid)
            cfg["plugins_disabled"] = dis
            core.save_config(cfg)
            if hasattr(mod, "on_uninstall"):
                try:
                    mod.on_uninstall(api)           # 关闭时清掉它建的任务 / 自启
                except Exception:
                    pass
            self.win.remove_plugin_nav(pid)         # 立即移除侧栏入口（不提示）


# ---------------------------------------------------------------- 设置（本机管理）
class SettingsInterface(ScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = _themed_body(self, "settings")
        v.addWidget(TitleLabel("设置"))

        grp = SettingCardGroup("本机")
        if core.is_installed():
            if core.has_update():
                up = PrimaryPushSettingCard("更新", FIF.UPDATE, f"更新到 v{core.VERSION}", "原地覆盖、保留设置")
                up.clicked.connect(self._update)
                grp.addSettingCard(up)
            un = PushSettingCard("卸载", FIF.DELETE, "卸载 LockDevice", "删除任务 / 自启 / 快捷方式 / 安装文件")
            un.clicked.connect(self._uninstall)
            grp.addSettingCard(un)
        else:
            inst = PrimaryPushSettingCard("安装", FIF.DOWNLOAD, "安装到本机",
                                          "开机自启 + 此后免 UAC + 定时关机（需一次授权）")
            inst.clicked.connect(self._install)
            grp.addSettingCard(inst)
            clr = PushSettingCard("清除数据", FIF.BROOM, "清除绿色 / 便携残留", "配置（含设置）、缓存、自启项")
            clr.clicked.connect(self._clear)
            grp.addSettingCard(clr)
        v.addWidget(grp)

        about = SettingCardGroup("关于")
        about.addSettingCard(PushSettingCard("v" + core.VERSION, FIF.INFO, "LockDevice · 专注锁定",
                                             "界面 PySide6 + qfluentwidgets（重构中）；tkinter 版仍可单文件运行"))
        v.addWidget(about)
        v.addStretch(1)

    def _install(self):
        core.save_install_opts({"dir": core.APP_DIR, "desktop": True, "launch": True})
        if core.relaunch_as_admin("--install"):
            self.win.close()

    def _uninstall(self):
        if MessageBox("卸载确认", "确定卸载 LockDevice？将删除计划任务、开机自启、快捷方式与安装文件。", self.win).exec():
            if core.relaunch_as_admin("--uninstall"):
                self.win.close()

    def _clear(self):
        if not MessageBox("清除数据", "将删除绿色运行的配置（含已保存的设置）与缓存，确定？", self.win).exec():
            return
        if os.path.isdir(core.GREEN_CACHE_DIR) and not core.is_admin() and not core.DRY_RUN:
            core.relaunch_as_admin("--cleardata")
            return
        core.clear_data()
        InfoBar.success("已清除", "绿色 / 便携残留已清理", parent=self.win, position=InfoBarPosition.TOP)

    def _update(self):
        d = core.installed_dir()
        if not d:
            return
        logs = "\n".join(f"· {x}" for _v, notes in core.changelog_since(core.installed_version())
                         for x in notes)
        if not MessageBox(f"更新到 v{core.VERSION}", (logs or "更新内容见发布页") + "\n\n原地覆盖、保留设置。确定？",
                          self.win).exec():
            return
        core.save_install_opts({"dir": d, "desktop": False, "launch": True})
        if core.relaunch_as_admin("--install"):
            self.win.close()


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LockDevice · 专注锁定")
        self.resize(920, 640)
        self.plugin_api = core._build_plugin_api(None)
        self.plugin_pages = {}
        self.home = HomeInterface(self)
        self.addSubInterface(self.home, FIF.HOME, "专注锁定")
        for meta, mod in core.active_plugins():
            self.add_plugin_nav(meta, mod)
        self.pmanage = PluginManageInterface(self)
        self.addSubInterface(self.pmanage, FIF.APPLICATION, "插件", NavigationItemPosition.BOTTOM)
        self.settings = SettingsInterface(self)
        self.addSubInterface(self.settings, FIF.SETTING, "设置", NavigationItemPosition.BOTTOM)

    def add_plugin_nav(self, meta, mod):
        """给一个启用的插件加侧栏入口（幂等）。"""
        if not (getattr(mod, "SETTINGS", None) or getattr(mod, "ACTIONS", None)):
            return
        pid = meta["id"]
        if pid in self.plugin_pages:
            return
        page = PluginPageInterface(self, meta, mod)
        self.addSubInterface(page, FIF.APPLICATION, meta.get("button") or meta.get("name") or pid)
        self.plugin_pages[pid] = page

    def remove_plugin_nav(self, pid):
        page = self.plugin_pages.pop(pid, None)
        if page is not None:
            try:
                self.removeInterface(page)
            except Exception:
                pass


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    setTheme(Theme.DARK)
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    run()
