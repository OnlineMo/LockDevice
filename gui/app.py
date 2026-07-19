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

from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog)
from PySide6.QtGui import QIcon
from qfluentwidgets import (FluentWindow, NavigationItemPosition, FluentIcon as FIF,
                            setTheme, Theme, TitleLabel, SubtitleLabel, BodyLabel,
                            PrimaryPushButton, PushButton, SpinBox, SwitchButton, ComboBox,
                            LineEdit, InfoBar, InfoBarPosition, ScrollArea, MessageBox,
                            MessageBoxBase, CheckBox,
                            SettingCardGroup, SwitchSettingCard, PushSettingCard,
                            PrimaryPushSettingCard)

_main = sys.modules.get("__main__")
if _main is not None and hasattr(_main, "load_plugins") and hasattr(_main, "_build_plugin_api"):
    core = _main                    # 由 lock_device.py 作入口启动时直接复用它（不重复导入本体）
else:
    import lock_device as core      # 独立导入 gui 时

_CREATE_NO_WINDOW = 0x08000000


def _app_icon():
    """本体的 .ico（任务栏/标题栏图标）；进程 AppUserModelID 已由 lock_device 设好。"""
    try:
        p = core._icon_path()
        return QIcon(p) if p else QIcon()
    except Exception:
        return QIcon()


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


# ---------------------------------------------------------------- 对话框：添加快捷 / 安装
class ShortcutDialog(MessageBoxBase):
    """添加「自定义快捷」——记住 时长 / 模式 / 附加开关，单击一键启动。"""

    def __init__(self, parent, home):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("添加快捷"))
        self.label = LineEdit()
        self.label.setPlaceholderText("标签（可选，不填自动生成）")
        self.viewLayout.addWidget(self.label)
        self.minutes = SpinBox()
        self.minutes.setRange(1, 24 * 60)
        self.minutes.setValue(int(home.minutes.value()))
        _row(self.viewLayout, "时长（分钟）", self.minutes)
        self.mode = ComboBox()
        self.mode.addItems(["① 全屏锁定（软）", "② 定时关机（硬）"])
        self.mode.setCurrentIndex(home.mode.currentIndex())
        _row(self.viewLayout, "锁定方式", self.mode)
        self.guard = SwitchButton()
        self.guard.setChecked(home.guard.switchButton.isChecked())
        self.block = SwitchButton()
        self.block.setChecked(home.block.switchButton.isChecked())
        self.preboot = SwitchButton()
        self.preboot.setChecked(home.preboot.switchButton.isChecked())
        self.instant = SwitchButton()
        self.instant.setChecked(home.instant.switchButton.isChecked())
        _row(self.viewLayout, "🛡 防止结束进程", self.guard)
        _row(self.viewLayout, "🚫 禁用任务管理器", self.block)
        _row(self.viewLayout, "🛡 登录前关机", self.preboot)
        _row(self.viewLayout, "⚡ 开始后立即关机", self.instant)
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()
        self.yesButton.setText("添加")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(380)

    def _sync(self):
        m1 = self.mode.currentIndex() == 0
        self.guard.setEnabled(m1)
        self.block.setEnabled(m1)
        self.preboot.setEnabled(not m1)
        self.instant.setEnabled(not m1)

    def values(self):
        return {"label": self.label.text().strip(), "minutes": int(self.minutes.value()),
                "mode": 2 if self.mode.currentIndex() == 1 else 1,
                "guard": self.guard.isChecked(), "block_taskmgr": self.block.isChecked(),
                "mode2_preboot": self.preboot.isChecked(), "mode2_instant": self.instant.isChecked()}


class InstallDialog(MessageBoxBase):
    """安装到本机：选择安装目录 + 桌面快捷 + 装后启动。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("安装到本机"))
        self.viewLayout.addWidget(BodyLabel("一次管理员授权 → 开机自启 / 此后免 UAC / 定时关机"))
        self.viewLayout.addWidget(BodyLabel("安装位置"))
        row = QHBoxLayout()
        self.dir_edit = LineEdit()
        self.dir_edit.setText(core.APP_DIR)
        browse = PushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        self.viewLayout.addLayout(row)
        self.desktop = CheckBox("创建桌面快捷方式")
        self.desktop.setChecked(True)
        self.launch = CheckBox("安装后立即启动")
        self.launch.setChecked(True)
        self.viewLayout.addWidget(self.desktop)
        self.viewLayout.addWidget(self.launch)
        self.yesButton.setText("开始安装")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(440)

    def _browse(self):
        base = os.path.dirname(self.dir_edit.text().rstrip("\\/")) or core.ROOT_DIR
        picked = QFileDialog.getExistingDirectory(self, "选择安装位置", base)
        if picked:
            self.dir_edit.setText(os.path.join(picked, "LockDevice"))

    def opts(self):
        return {"dir": self.dir_edit.text().strip() or core.APP_DIR,
                "desktop": self.desktop.isChecked(), "launch": self.launch.isChecked()}


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

        v.addWidget(BodyLabel("自定义快捷（单击一键启动）"))
        self.sc_box = QWidget()
        self.sc_lay = QVBoxLayout(self.sc_box)
        self.sc_lay.setContentsMargins(0, 0, 0, 0)
        self.sc_lay.setSpacing(6)
        v.addWidget(self.sc_box)
        add_sc = PushButton("＋ 添加快捷")
        add_sc.clicked.connect(self._add_shortcut)
        v.addWidget(add_sc)
        self._render_shortcuts()

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
        self._do_start(2 if self.mode.currentIndex() == 1 else 1, int(self.minutes.value()),
                       self.guard.switchButton.isChecked(), self.block.switchButton.isChecked(),
                       self.preboot.switchButton.isChecked(), self.instant.switchButton.isChecked())

    def _do_start(self, mode, minutes, guard, block_tm, preboot, instant):
        cfg = core.load_config()
        cfg.update({"mode": mode, "minutes": minutes, "guard": guard, "block_taskmgr": block_tm,
                    "mode2_preboot": preboot, "mode2_instant": instant})
        core.save_config(cfg)
        if mode == 1:
            _spawn("--startlock", str(minutes * 60))
            InfoBar.success("已开始", f"全屏锁定 {minutes} 分钟", parent=self.win,
                            position=InfoBarPosition.TOP)
        else:
            self._start_mode2(minutes, preboot, instant)

    # ---- 自定义快捷（一键启动预设，与 tkinter 版共用 config["shortcuts"]）----
    def _render_shortcuts(self):
        while self.sc_lay.count():
            it = self.sc_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        scs = core.load_config().get("shortcuts", [])
        if not scs:
            self.sc_lay.addWidget(BodyLabel("（暂无，点下方「添加快捷」）"))
            return
        for i, sc in enumerate(scs):
            mode = 2 if sc.get("mode") == 2 else 1
            text = sc.get("label") or f"{'②定时关机' if mode == 2 else '①全屏锁定'} · {sc.get('minutes', 30)} 分钟"
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            go = PrimaryPushButton(text)
            go.clicked.connect(lambda _=False, s=dict(sc): self._launch_shortcut(s))
            dele = PushButton("删除")
            dele.clicked.connect(lambda _=False, idx=i: self._del_shortcut(idx))
            h.addWidget(go, 1)
            h.addWidget(dele)
            self.sc_lay.addWidget(row)

    def _del_shortcut(self, idx):
        cfg = core.load_config()
        scs = list(cfg.get("shortcuts", []))
        if 0 <= idx < len(scs):
            del scs[idx]
            cfg["shortcuts"] = scs
            core.save_config(cfg)
            self._render_shortcuts()

    def _add_shortcut(self):
        dlg = ShortcutDialog(self.win, self)
        if not dlg.exec():
            return
        cfg = core.load_config()
        scs = list(cfg.get("shortcuts", []))
        scs.append(dlg.values())
        cfg["shortcuts"] = scs
        core.save_config(cfg)
        self._render_shortcuts()

    def _launch_shortcut(self, sc):
        try:
            minutes = int(sc.get("minutes", 30))
        except (ValueError, TypeError):
            return
        mode = 2 if sc.get("mode") == 2 else 1
        guard = bool(sc.get("guard", True))
        block_tm = bool(sc.get("block_taskmgr", False))
        preboot = bool(sc.get("mode2_preboot", False))
        instant = bool(sc.get("mode2_instant", False))
        self.mode.setCurrentIndex(1 if mode == 2 else 0)   # 同步到界面，让用户看到采用的设置
        self.minutes.setValue(minutes)
        self.guard.switchButton.setChecked(guard)
        self.block.switchButton.setChecked(block_tm)
        self.preboot.switchButton.setChecked(preboot)
        self.instant.switchButton.setChecked(instant)
        self._do_start(mode, minutes, guard, block_tm, preboot, instant)

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
        dlg = InstallDialog(self.win)
        if not dlg.exec():
            return
        opts = dlg.opts()
        core.save_install_opts(opts)
        if core.DRY_RUN or core.is_admin():
            ok, msg = core.do_install(opts["dir"], opts["desktop"], opts["launch"])
            core.clear_install_opts()
            (InfoBar.success if ok else InfoBar.error)(
                "安装", msg, parent=self.win, position=InfoBarPosition.TOP)
        elif core.relaunch_as_admin("--install"):
            self.win.close()
        else:
            core.clear_install_opts()
            InfoBar.warning("已取消", "未获得管理员权限，安装取消。", parent=self.win,
                            position=InfoBarPosition.TOP)

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
        ico = _app_icon()
        if not ico.isNull():
            self.setWindowIcon(ico)
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
    ico = _app_icon()
    if not ico.isNull():
        app.setWindowIcon(ico)
    setTheme(Theme.DARK)
    w = MainWindow()
    w.show()
    app.exec()


if __name__ == "__main__":
    run()
