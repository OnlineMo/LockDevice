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
import threading
import subprocess

from PySide6.QtCore import QObject, Signal, QTime, Qt, QByteArray, QRect, QTimer
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFileDialog)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor
from qfluentwidgets import (FluentWindow, NavigationItemPosition, FluentIcon as FIF,
                            setTheme, Theme, TitleLabel, SubtitleLabel, BodyLabel,
                            PrimaryPushButton, PushButton, SpinBox, SwitchButton, ComboBox,
                            LineEdit, TimeEdit, InfoBar, InfoBarPosition, ScrollArea, MessageBox,
                            MessageBoxBase, CheckBox,
                            SettingCardGroup, SwitchSettingCard, PushSettingCard,
                            PrimaryPushSettingCard)

_main = sys.modules.get("__main__")
_FROZEN = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
if _main is not None and hasattr(_main, "load_plugins") and hasattr(_main, "_build_plugin_api"):
    core = _main                    # 由 lock_device.py 作入口启动时直接复用它（不重复导入本体）
else:
    import lock_device as core      # 独立导入 gui 时
    _FROZEN = bool(getattr(core, "IS_FROZEN", _FROZEN))

_CREATE_NO_WINDOW = 0x08000000


class _UiBridge(QObject):
    """把工作线程里的回调调度回 GUI 线程执行（emit 信号 → Qt 自动排队到对象所在线程）。

    插件回调（批量重建计划任务等，实测 5-6 秒）在工作线程跑、界面不卡；
    对话框/侧栏增删等 UI 操作经这里回到主线程。
    """
    _invoke = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gui_ident = threading.get_ident()   # 构造即在 GUI 主线程：记下主线程标识
        self._closing = False
        self._invoke.connect(self._run)

    def begin_close(self):
        """进入退出流程：需要对话框结果（wait=True）的插件回调立即返回 None，
        不再阻塞退出（窗口已关，弹窗已无意义）。"""
        self._closing = True

    def _run(self, fn):
        try:
            fn()
        except Exception:
            try:
                core._log("UI 回调失败\n" + core.traceback.format_exc())
            except Exception:
                pass

    def call(self, fn, wait=False, timeout=120):
        """在主线程执行 fn；已在线程内则直接执行。
        wait=True 时阻塞等待返回值（工作线程里要对话框结果时用）；
        退出流程中直接返回 None；窗口 C++ 对象已销毁时静默丢弃。"""
        if threading.get_ident() == self._gui_ident:
            return fn()
        if wait and self._closing:
            return None
        if not wait:
            try:
                self._invoke.emit(fn)
            except RuntimeError:
                pass
            return None
        done = threading.Event()
        box = {}

        def _w():
            try:
                box["r"] = fn()
            except Exception as e:
                box["e"] = e
            finally:
                done.set()
        try:
            self._invoke.emit(_w)
        except RuntimeError:
            return None   # 窗口已销毁（退出中）
        if not done.wait(timeout):
            raise TimeoutError("UI 回调等待超时")
        if "e" in box:
            raise box["e"]
        return box.get("r")


def _app_icon():
    """本体的 .ico（任务栏/标题栏图标）；进程 AppUserModelID 已由 lock_device 设好。"""
    try:
        p = core._icon_path()
        return QIcon(p) if p else QIcon()
    except Exception:
        return QIcon()


def _spawn(*args):
    exe = core._self_path()
    cmd = [exe, *args] if _FROZEN else [core._pythonw_path(), exe, *args]
    subprocess.Popen(cmd, creationflags=_CREATE_NO_WINDOW)


def _force_foreground_win(w, retry=False):
    """把窗口强制拉到前台（Windows；其它平台/失败时静默）。

    免 UAC 链路的正规入口是计划任务：Task Scheduler 启动的进程**没有前台激活权限**，
    窗口默认开在后台——要手动点任务栏才能出来。这里用「附加输入队列」技巧：临时把
    本线程挂到当前前台窗口的输入队列上，SetForegroundWindow 即被放行；并兜底
    BringWindowToTop。retry=True 供延迟补枪：已在前台就跳过，不做无谓抢焦点。"""
    try:
        import ctypes
        u = ctypes.windll.user32
    except Exception:
        return
    try:
        hwnd = int(w.winId())
    except Exception:
        return
    try:
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)               # SW_RESTORE：从最小化恢复
        if retry and u.GetForegroundWindow() == hwnd:
            return
        try:
            w.raise_()
            w.activateWindow()
        except Exception:
            pass
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_me = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = False
        if tid_fg and tid_fg != tid_me:
            attached = bool(u.AttachThreadInput(tid_me, tid_fg, True))
        try:
            u.SetForegroundWindow(hwnd)
            u.BringWindowToTop(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(tid_me, tid_fg, False)
    except Exception:
        pass


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


def _dispatch_item(win, pid, mod, fn_name, index=None):
    """items 回调：工作线程执行（插件通常在其中弹 prompt + 保存 + 刷新），
    与开关/保存/动作共用 plugin_op_lock 串行。"""
    def work():
        try:
            with core.plugin_op_lock(pid):
                core._plugin_items_cb(mod, win.plugin_api, fn_name, index)
        except Exception:
            core._log("plugin items 回调失败\n" + core.traceback.format_exc())
    core.run_plugin_op(work)


def _render_items_qt(v, win, pid, f, vals, mod):
    """items 字段（Qt）：条目列表（display 模板）+ 每项「删除」+ 底部「添加」；
    点击/删除 → mod.<fn>(api, index)，添加 → mod.<fn>(api)。本体只回调——
    插件应在回调里用 api.prompt 收集输入、api.save_settings 写回、api.refresh 刷新列表。"""
    items = vals.get(f.get("key"), f.get("default") or [])
    if not isinstance(items, list):
        items = []
    click_fn, remove_fn, add_fn = f.get("click"), f.get("remove"), f.get("add")
    if not (click_fn or remove_fn or add_fn):
        return
    tpl = f.get("display") or "{name}"
    v.addWidget(BodyLabel(f.get("label", "条目")))
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        if click_fn:
            go = PrimaryPushButton(core._fmt_item(tpl, item))
            go.clicked.connect(lambda _=False, x=i: _dispatch_item(win, pid, mod, click_fn, x))
        else:
            go = PushButton(core._fmt_item(tpl, item))
            go.setEnabled(False)    # 无点击回调：仅展示
        h.addWidget(go, 1)
        if remove_fn:
            dele = PushButton("删除")
            dele.clicked.connect(lambda _=False, x=i: _dispatch_item(win, pid, mod, remove_fn, x))
            h.addWidget(dele)
        v.addWidget(row)
    if add_fn:
        add = PrimaryPushButton(f.get("add_label", "＋ 添加"))
        add.clicked.connect(lambda _=False: _dispatch_item(win, pid, mod, add_fn))
        v.addWidget(add)


def _field(v, store, pid, f, vals, mod=None, win=None):
    """按声明渲染一个设置控件，把 (pid,key,type,getter) 追加进 store。
    类型：bool / choice / int / str（原有）+ time / int+min/max/step / status / items（新增）；
    status / items 是展示型控件（不入 store，需要 mod、items 还需要 win/页面上下文）。"""
    key, ftype = f.get("key", ""), f.get("type", "str")
    cur = vals.get(key, f.get("default"))

    if ftype == "status":       # 展示型：渲染时调插件函数取动态文本
        if mod is None or win is None:
            return
        fn = getattr(mod, f.get("fn", ""), None)
        text = "（未声明 fn）"
        if callable(fn):
            try:
                text = str(fn(win.plugin_api))
            except Exception:
                core._log("status 字段读取失败\n" + core.traceback.format_exc())
                text = "（读取失败，详见 error.log）"
        lbl = BodyLabel(text)
        try:
            lbl.setTextColor("#8a8a8a", "#9a9a9a")
        except Exception:
            pass
        _row(v, f.get("label", "状态"), lbl)
        return

    if ftype == "items":        # 展示型：条目列表（可点/可删/可加，全部回调插件）
        if mod is None or win is None:
            return
        _render_items_qt(v, win, pid, f, vals, mod)
        return

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
    elif ftype == "time":       # HH:MM 时间点（存 "HH:MM" 字符串）
        wdg = TimeEdit()
        t = QTime.fromString(str(cur if cur is not None else f.get("default") or "00:00"), "HH:mm")
        wdg.setTime(t if t.isValid() else QTime(0, 0))
        getter = lambda: wdg.time().toString("HH:mm")
    elif ftype == "int" and any(k in f for k in ("min", "max", "step")):
        wdg = SpinBox()
        wdg.setRange(int(f.get("min", 0)), int(f.get("max", 999999)))
        wdg.setSingleStep(int(f.get("step", 1)))
        try:
            wdg.setValue(int(cur))
        except (ValueError, TypeError):
            wdg.setValue(int(f.get("min", 0)))
        getter = wdg.value
    else:
        wdg = LineEdit()
        wdg.setText("" if cur is None else str(cur))
        wdg.setFixedWidth(180)
        getter = wdg.text
    _row(v, f.get("label", key), wdg)
    store.append((pid, key, ftype, getter))


def _save_fields(win, fields):
    """把 fields 的值写回 config（按插件分区）并回调 on_settings_saved。
    回调可能很慢（如批量重建计划任务）——放工作线程，界面不卡；提示经 ui_bridge 回主线程。"""
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

    def work():
        for meta, mod in core.load_plugins():
            if meta["id"] in touched and hasattr(mod, "on_settings_saved"):
                try:
                    with core.plugin_op_lock(meta["id"]):
                        mod.on_settings_saved(win.plugin_api,
                                              dict(cfg["plugins"].get(meta["id"], {})))
                except Exception:
                    core._log("on_settings_saved 失败\n" + core.traceback.format_exc())
        win.ui_bridge.call(lambda: InfoBar.success(
            "已保存", "设置已保存", parent=win, position=InfoBarPosition.TOP))
    core.run_plugin_op(work)


# ---------------------------------------------------------------- 插件图标（Qt 渲染）
_EMOJI_ICONS = {}


def _emoji_icon(ch, px=64):
    """emoji 字符 → QIcon：画到透明底 pixmap（缓存）。Windows 下 Qt 对 emoji 做单色
    渲染（用画笔颜色），而 Qt 端恒为深色主题（setTheme(Theme.DARK)），用浅灰 #e8e8e8。"""
    key = (ch, px)
    ico = _EMOJI_ICONS.get(key)
    if ico is not None:
        return ico
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        f = QFont("Segoe UI Emoji")
        f.setPixelSize(int(px * 0.8))
        p.setFont(f)
        p.setPen(QColor("#e8e8e8"))
        p.drawText(QRect(0, 0, px, px), Qt.AlignCenter, ch)
    finally:
        p.end()
    ico = QIcon(pm)
    _EMOJI_ICONS[key] = ico
    return ico


def _fif_by_name(name):
    """按名字（不区分大小写，匹配成员名或 value）找 FluentIcon 成员；找不到返回 None。"""
    try:
        for m in FIF:
            if m.name.lower() == name.lower() or str(getattr(m, "value", "")).lower() == name.lower():
                return m
    except Exception:
        pass
    return None


def _plugin_icon_qt(meta, mod=None):
    """插件图标声明 → QIcon | FluentIcon | None（None → 调用处回退 FIF.APPLICATION）。
    形态见本体 plugin_icon_source：emoji 字符串 / {"base64"} / {"file"} / {"fluent"}。"""
    kind, val = core.plugin_icon_source(meta, mod)
    try:
        if kind == "emoji":
            return _emoji_icon(val)
        if kind == "base64":
            pm = QPixmap()
            if pm.loadFromData(QByteArray.fromBase64(val.encode("ascii"))):
                return QIcon(pm)
        elif kind == "file":
            pm = QPixmap(val)
            if not pm.isNull():
                return QIcon(pm)
        elif kind == "fluent":
            return _fif_by_name(val)
    except Exception:
        core._log("插件图标渲染失败（Qt）：\n" + core.traceback.format_exc())
    return None


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
        self.cancel_sd = PushButton("⚠  解除已存在的关机计划")
        self.cancel_sd.clicked.connect(self._cancel_shutdown)
        v.addWidget(self.cancel_sd)
        self._refresh_cancel_shutdown()

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
        self._refresh_cancel_shutdown()
        core.do_shutdown(0 if instant else core.SHUTDOWN_DELAY, "LockDevice：电脑即将关机，请保存文件")

    def _refresh_cancel_shutdown(self):
        """存在定时关机任务时才显示「解除」按钮（对应 tk show_main 的同款按钮）。"""
        try:
            exists = bool(core._task_exists(core.TASK_SHUTDOWN))
        except Exception:
            exists = False
        self.cancel_sd.setVisible(exists)

    def _cancel_shutdown(self):
        ok, msg = core.remove_shutdown_task()
        if ok:
            InfoBar.success("已解除", "关机计划任务已删除。", parent=self.win, position=InfoBarPosition.TOP)
        else:
            InfoBar.error("解除失败", (msg or "") + " 若因权限失败请以管理员运行。",
                          parent=self.win, position=InfoBarPosition.TOP, duration=-1)
        self._refresh_cancel_shutdown()


# ---------------------------------------------------------------- 每个插件一页
class PluginPageInterface(ScrollArea):
    def __init__(self, win, meta, mod):
        super().__init__()
        self.win = win
        self.meta = meta
        self.mod = mod
        self._fields = []
        self._build()

    def _build(self):
        """（重）构建页面内容：SETTINGS 表单 + ACTIONS 按钮 + 保存（api.refresh 会再调本函数）。"""
        v = _themed_body(self, "plugin_" + self.meta["id"])
        v.addWidget(TitleLabel(self.meta.get("name", self.meta["id"])))
        v.addWidget(BodyLabel(f"v{self.meta.get('version', '')}"))
        self._fields = []
        pid = self.meta["id"]
        vals = core.load_config().get("plugins", {}).get(pid, {})
        for f in getattr(self.mod, "SETTINGS", []):
            _field(v, self._fields, pid, f, vals, mod=self.mod, win=self.win)
        for act in getattr(self.mod, "ACTIONS", []) or []:
            fn = getattr(self.mod, act.get("fn", ""), None)
            if callable(fn):
                b = PushButton(act.get("label", act.get("fn", "")))
                b.clicked.connect(lambda _=False, f=fn: self._action(f))
                v.addWidget(b)
        v.addStretch(1)
        if getattr(self.mod, "SETTINGS", None):
            save = PrimaryPushButton("💾  保存")
            save.clicked.connect(lambda: _save_fields(self.win, self._fields))
            v.addWidget(save)

    def rebuild(self):
        """重渲染本页（插件 api.refresh() 的实现路径）。仅主线程调用。"""
        self._build()

    def _current_values(self):
        """当前表单值（含未保存改动）→ {key: value}。仅主线程调用（读控件）。"""
        out = {}
        for _pid, key, ftype, getter in self._fields:
            try:
                v = getter()
            except Exception:
                continue
            if ftype == "int":
                try:
                    v = int(str(v).strip())
                except (ValueError, TypeError):
                    v = 0
            out[key] = v
        return out

    def _action(self, fn):
        """插件动作按钮：主线程取当前表单值 → 工作线程执行（可能含慢操作），
        对话框经 ui_bridge 自动回主线程；与开关/保存共用 plugin_op_lock。
        动作函数签名：`fn(api, values)` 或 `fn(api)` 均可（签名探测）。"""
        values = self._current_values()

        def work():
            try:
                with core.plugin_op_lock(self.meta["id"]):
                    core._call_plugin_action(fn, self.win.plugin_api, values)
            except Exception:
                core._log("plugin action 失败\n" + core.traceback.format_exc())
        core.run_plugin_op(work)


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
                card = SwitchSettingCard(_plugin_icon_qt(meta, mod) or FIF.APPLICATION,
                                         meta.get("name", pid),
                                         f"v{meta.get('version', '')} · {pid}")
                card.switchButton.setChecked(pid not in dis)
                card.switchButton.checkedChanged.connect(
                    lambda on, mt=meta, md=mod, sw=card.switchButton: self._toggle(mt, md, on, sw))
                grp.addSettingCard(card)
            v.addWidget(grp)
        v.addStretch(1)

    def _toggle(self, meta, mod, on, switch=None):
        """开关插件。插件回调（on_settings_saved / on_uninstall）可能很慢
        （如批量重建计划任务实测 5-6 秒），放工作线程执行、界面不卡；
        侧栏入口增删与开关恢复经 ui_bridge 回到主线程。"""
        pid = meta["id"]
        if switch is not None:
            switch.setEnabled(False)   # 处理中禁点；完成后恢复

        def work():
            try:
                with core.plugin_op_lock(pid):
                    cfg = core.load_config()
                    dis = [x for x in cfg.get("plugins_disabled", []) if x != pid]
                    if on:
                        cfg["plugins_disabled"] = dis
                        core.save_config(cfg)
                        if hasattr(mod, "on_settings_saved"):
                            try:
                                mod.on_settings_saved(self.win.plugin_api,
                                                      dict(cfg.get("plugins", {}).get(pid, {})))
                            except Exception:
                                core._log("on_settings_saved 失败\n" + core.traceback.format_exc())
                    else:
                        dis.append(pid)
                        cfg["plugins_disabled"] = dis
                        core.save_config(cfg)
                        if hasattr(mod, "on_uninstall"):
                            try:
                                mod.on_uninstall(self.win.plugin_api)
                            except Exception:
                                core._log("on_uninstall 失败\n" + core.traceback.format_exc())
            except Exception:
                core._log("插件开关失败\n" + core.traceback.format_exc())
            finally:
                def done():
                    try:
                        if switch is not None:
                            switch.setEnabled(True)
                        if on:
                            self.win.add_plugin_nav(meta, mod)      # 立即加回侧栏入口
                        else:
                            self.win.remove_plugin_nav(pid)         # 立即移除侧栏入口（不提示）
                    except Exception:
                        core._log("插件开关收尾失败\n" + core.traceback.format_exc())
                self.win.ui_bridge.call(done)

        core.run_plugin_op(work)


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
        self.ui_bridge = _UiBridge(self)   # 插件慢回调的线程调度桥（工作线程 → GUI 线程）
        self.plugin_api = core._build_plugin_api(None)
        _ui = self.ui_bridge.call
        # 插件对话框走 Qt（否则 app=None 时只 _log、confirm 恒 True——弹窗成了 tk 专属）；
        # 经 _ui 调度：从工作线程（插件慢回调）调用时自动回到 GUI 线程弹。
        self.plugin_api.info = lambda msg, title="LockDevice": _ui(
            lambda: InfoBar.success(title, msg, parent=self, position=InfoBarPosition.TOP, duration=4000))
        self.plugin_api.error = lambda msg, title="LockDevice": _ui(
            lambda: InfoBar.error(title, msg, parent=self, position=InfoBarPosition.TOP, duration=-1))
        self.plugin_api.confirm = lambda msg, title="LockDevice": bool(_ui(
            lambda: MessageBox(title, msg, self).exec(), wait=True))
        # 插件 API 2.0：动态刷新当前插件页 / 通用表单弹窗（都经线程桥调度）
        self.plugin_api.refresh = lambda: _ui(self.refresh_current_plugin)
        self.plugin_api.prompt = lambda title="输入", fields=None: _ui(
            lambda: self._prompt_dialog(title, fields or []), wait=True)
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
        self.addSubInterface(page, _plugin_icon_qt(meta, mod) or FIF.APPLICATION,
                             meta.get("button") or meta.get("name") or pid)
        self.plugin_pages[pid] = page

    def remove_plugin_nav(self, pid):
        page = self.plugin_pages.pop(pid, None)
        if page is not None:
            try:
                self.removeInterface(page)
            except Exception:
                pass

    def refresh_current_plugin(self):
        """重渲染当前显示的插件页（插件 api.refresh() 的实现路径）。仅主线程调用。"""
        try:
            cur = self.stackedWidget.currentWidget()
        except Exception:
            cur = None
        if isinstance(cur, PluginPageInterface):
            cur.rebuild()

    def _prompt_dialog(self, title, fields):
        """本体渲染的通用输入弹窗（插件 api.prompt 的实现）。仅主线程调用。
        字段定义与 SETTINGS 同款（bool/choice/int/str/time；status/items 不适用于弹窗）。
        点「确定」返回 {key: value}；取消返回 None。"""
        class _PromptDialog(MessageBoxBase):
            def __init__(self, parent):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel(title)
                self.viewLayout.addWidget(self.titleLabel)
                self._store = []
                for f in fields:
                    if f.get("type") in ("status", "items"):
                        continue        # 页面专属控件，弹窗里不适用
                    _field(self.viewLayout, self._store, "_prompt", f, {})
                self.yesButton.setText("确定")
                self.cancelButton.setText("取消")
                self.widget.setMinimumWidth(420)

            def values(self):
                out = {}
                for _p, key, ftype, getter in self._store:
                    try:
                        v = getter()
                    except Exception:
                        continue
                    if ftype == "int":
                        try:
                            v = int(str(v).strip())
                        except (ValueError, TypeError):
                            v = 0
                    out[key] = v
                return out

        dlg = _PromptDialog(self)
        if dlg.exec():
            return dlg.values()
        return None


# ---------------------------------------------------------------- 发现新版本（Qt 版更新窗）
class UpdateWindow(QWidget):
    """新版文件在已装机器上运行时的独立「发现更新」窗（对应 tkinter 的 show_update_window）。
    此前已用最高权限任务免 UAC 打开了已安装（旧）版本；本窗只展示更新日志 + 更新/稍后/跳过。"""

    def __init__(self):
        super().__init__()
        # 深色主题背景：run_update_prompt()/run() 强制深色主题，而本窗是普通 QWidget
        # （不像 FluentWindow 自带主题底色），浅色系统上会“浅底浅字”看不清——
        # 与 LockWindow 同款做法：显式给窗口补上背景色。
        self.setStyleSheet("background:#202020;")
        self.setWindowTitle("LockDevice · 发现新版本")
        ico = _app_icon()
        if not ico.isNull():
            self.setWindowIcon(ico)
        self.resize(480, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 18)
        root.setSpacing(10)
        root.addWidget(TitleLabel("🔄  发现新版本"))
        root.addWidget(SubtitleLabel(f"已安装 v{core.installed_version()}  →  新版本 v{core.VERSION}"))
        tip = BodyLabel("已为你免管理员打开当前已安装的版本；如需升级点下方「更新」。")
        tip.setWordWrap(True)
        root.addWidget(tip)
        root.addWidget(BodyLabel("更新内容"))

        area = ScrollArea()
        area.setWidgetResizable(True)
        try:
            area.enableTransparentBackground()
        except Exception:
            pass
        area.setStyleSheet("QScrollArea{border:none;background:transparent}")
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(4, 2, 20, 2)   # 右侧留白给叠加式滚动条，免得遮住正文最后一个字
        logs = core.changelog_since(core.installed_version())
        if not logs:
            il.addWidget(BodyLabel("（本版本未附更新说明）"))
        for ver, notes in logs:
            il.addWidget(SubtitleLabel(f"v{ver}"))
            for line in notes:
                bl = BodyLabel("·  " + line)
                bl.setWordWrap(True)
                il.addWidget(bl)
        il.addStretch(1)
        area.setWidget(inner)
        root.addWidget(area, 1)

        up = PrimaryPushButton(f"🔄  更新到 v{core.VERSION}")
        up.clicked.connect(self._update)
        root.addWidget(up)
        brow = QHBoxLayout()
        later = PushButton("稍后再说")
        later.clicked.connect(self.close)
        skip = PushButton("跳过此版本")
        skip.clicked.connect(self._skip)
        brow.addWidget(later, 1)
        brow.addWidget(skip, 1)
        root.addLayout(brow)
        hint = BodyLabel("「稍后再说」下次仍提示；「跳过此版本」则此版本不再提示（有更高版本仍会提示）。")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def _update(self):
        d = core.installed_dir()
        if not d:
            return
        core.save_install_opts({"dir": d, "desktop": False, "launch": True})
        if core.relaunch_as_admin("--install"):
            self.close()
        else:
            MessageBox("更新", "启动更新程序失败（未获得管理员权限或文件缺失）。\n"
                               "可稍后手动双击新版 exe 重新尝试。", self).exec()

    def _skip(self):
        cfg = core.load_config()
        cfg["skip_version"] = core.VERSION
        core.save_config(cfg)
        self.close()


def run_update_prompt():
    """launcher 分流：新版文件在已装机器上运行时，弹 Qt「发现更新」窗（不提权、零 UAC）。"""
    app = QApplication.instance() or QApplication(sys.argv)
    ico = _app_icon()
    if not ico.isNull():
        app.setWindowIcon(ico)
    setTheme(Theme.DARK)
    w = UpdateWindow()
    w.show()
    _force_foreground_win(w)   # 与启动器实例并存时也稳定到前台（替代裸 raise/activate）
    QTimer.singleShot(800, lambda: _force_foreground_win(w, retry=True))
    app.exec()


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    ico = _app_icon()
    if not ico.isNull():
        app.setWindowIcon(ico)
    setTheme(Theme.DARK)
    w = MainWindow()
    w.show()
    # 免 UAC 链路（计划任务）启动的实例没有前台权限：窗口会被开在后台，用户得点任务栏。
    # 立即强制前置 + 两次延迟补枪（已在前台则自动跳过；提权实例常在 1 秒内才显示完）。
    _force_foreground_win(w)
    QTimer.singleShot(600, lambda: _force_foreground_win(w, retry=True))
    QTimer.singleShot(1400, lambda: _force_foreground_win(w, retry=True))
    app.exec()
    # 退出收尾：窗口已关——标记关闭（工作线程里的对话框调用不再等待），
    # 等进行中的插件操作把「建/删任务」等做完再让进程退出
    # （防点完开关立刻关窗留下半成品状态；超时兜底、登录 on_boot 自愈）。
    try:
        w.ui_bridge.begin_close()
        core.wait_plugin_ops(30)
    except Exception:
        pass


if __name__ == "__main__":
    run()
