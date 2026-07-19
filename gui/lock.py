# -*- coding: utf-8 -*-
"""LockDevice · Qt 原生全屏锁屏（模式一），完全不依赖 tkinter。

窗口与计时用 Qt；锁定后端全部复用 lock_device 里「工具箱无关」的能力：
KeyBlocker（低层键盘钩子）、双进程互守看门狗（pidfile）、智能自启、
禁用任务管理器、息屏、关机、clear_lock_state。tkinter 版锁屏仍在本体里，保持不变。
"""
import os
import sys
import time
import ctypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton)

_main = sys.modules.get("__main__")
if _main is not None and hasattr(_main, "KeyBlocker") and hasattr(_main, "clear_lock_state"):
    core = _main                    # 由 lock_device.py 作入口启动时直接复用它
else:
    import lock_device as core      # 独立导入时


class LockWindow(QWidget):
    """全屏黑幕锁屏：顶部时钟 + 巨大倒计时 + 息屏/关机按钮。"""

    def __init__(self, seconds, guard_on=True, block_tm=False, _test=False):
        super().__init__()
        self._end = time.monotonic() + seconds
        self._guard_on = guard_on
        self._block_tm = block_tm
        self._test = _test
        self._finished = False
        self._stopping = False
        self._suspend_top = False
        self.watchdog_pid = None
        self.blocker = None

        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet("background:#0a0a0a;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(2)
        self.clock = QLabel("", alignment=Qt.AlignCenter)
        self.clock.setStyleSheet("color:#5a5a5a;background:transparent;")
        self.clock.setFont(QFont("Consolas", 30))
        lay.addWidget(self.clock)
        self.count = QLabel("", alignment=Qt.AlignCenter)
        f = QFont("Consolas", 110)
        f.setBold(True)
        self.count.setFont(f)
        self.count.setStyleSheet("color:#ffffff;background:transparent;")
        lay.addWidget(self.count)

        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        row.setSpacing(20)
        btn_css = ("QPushButton{background:#2a2a2a;color:#d0d0d0;border:none;"
                   "padding:8px 20px;border-radius:6px;font-size:14px}"
                   "QPushButton:hover{background:#3a3a3a;color:#ffffff}")
        b_off = QPushButton("🌙  息屏")
        b_off.setStyleSheet(btn_css)
        b_off.setCursor(Qt.PointingHandCursor)
        b_off.clicked.connect(self._screen_off)
        b_sd = QPushButton("⏻  关机")
        b_sd.setStyleSheet(btn_css)
        b_sd.setCursor(Qt.PointingHandCursor)
        b_sd.clicked.connect(self._shutdown)
        row.addWidget(b_off)
        row.addWidget(b_sd)
        lay.addSpacing(30)
        lay.addLayout(row)
        lay.addStretch(3)

        if not self._test:
            self.showFullScreen()
            self.raise_()
            self.activateWindow()
            try:
                self.grabKeyboard()
            except Exception:
                pass
            self._start_backend()

        self._t_clock = QTimer(self)
        self._t_clock.timeout.connect(self._tick_clock)
        self._t_count = QTimer(self)
        self._t_count.timeout.connect(self._tick_count)
        self._t_top = None
        self._t_watch = None
        if not self._test:
            self._t_clock.start(1000)
            self._t_count.start(250)
            self._t_top = QTimer(self)
            self._t_top.timeout.connect(self._keep_top)
            self._t_top.start(400)
            if self._guard_on:
                self._t_watch = QTimer(self)
                self._t_watch.timeout.connect(self._watch_tick)
                self._t_watch.start(500)
        self._tick_clock()
        self._tick_count()

    # ---- 后端：键盘拦截 + 禁用任务管理器 + 看门狗 ----
    def _start_backend(self):
        try:
            self.blocker = core.KeyBlocker()
            self.blocker.start()
            if self._block_tm:
                core.set_taskmgr_disabled(True)
            if self._guard_on:
                self._start_guard()
        except Exception:
            core._log("Qt 锁屏后端启动失败：\n" + core.traceback.format_exc())

    # ---- 阻止关闭（Alt+F4 等）直到倒计时结束；吞掉按键 ----
    def closeEvent(self, e):
        if self._finished:
            e.accept()
        else:
            e.ignore()

    def keyPressEvent(self, e):
        e.accept()

    # ---- 计时 ----
    def _tick_clock(self):
        self.clock.setText(time.strftime("%H:%M:%S", time.localtime()))

    def _tick_count(self):
        remaining = int(round(self._end - time.monotonic()))
        if remaining <= 0:
            self._finish()
            return
        h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
        self.count.setText(f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")

    def _keep_top(self):
        if not self._finished and not self._suspend_top:
            self.raise_()
            self.activateWindow()

    # ---- 息屏：延迟 1 秒再熄灭显示器（避开点击那下的输入把屏幕唤醒）----
    def _screen_off(self):
        def _off():
            try:
                ctypes.windll.user32.SendMessageTimeoutW(
                    0xFFFF, 0x0112, 0xF170, 2, 0x0002, 1000, None)
            except Exception:
                pass
        QTimer.singleShot(1000, _off)

    def _shutdown(self):
        from qfluentwidgets import MessageBox
        self._suspend_top = True
        box = MessageBox("关机", "确定要关机吗？\n（锁定尚未结束，重启后会自动继续锁定）", self)
        ok = box.exec()
        self._suspend_top = False
        if ok:
            self._stopping = True   # 停止看门狗轮询；关机后整机下线，恢复时再互守
            core.do_shutdown(0, "LockDevice：关机")

    # ---- 双进程互守（复用本体的 pidfile 级函数，仅计时器换 QTimer）----
    def _spawn_watchdog(self):
        if core.DRY_RUN:
            print("[DRY] 启动看门狗 (--watch)")
            return
        core._write_pidfile(core._watchdog_pidfile(), 0)
        core._spawn_detached("--watch")
        self.watchdog_pid = None

    def _start_guard(self):
        core._write_pidfile(core._locker_pidfile(), os.getpid())
        wd = core._read_pidfile(core._watchdog_pidfile())
        if wd and core._process_alive(wd):
            self.watchdog_pid = wd          # 被看门狗拉起：接管现有 vbs
        else:
            self._spawn_watchdog()

    def _watch_tick(self):
        if self._stopping or self._finished:
            return
        wd = core._read_pidfile(core._watchdog_pidfile())
        if wd > 0:
            if core._process_alive(wd):
                self.watchdog_pid = wd
            else:
                self._spawn_watchdog()      # 看门狗死了 → 反挂重启

    def _stop_guard(self):
        self._stopping = True
        try:
            os.remove(core._locker_pidfile())   # vbs 见 locker.pid 消失即自退
        except OSError:
            pass
        core._kill_pid(self.watchdog_pid or core._read_pidfile(core._watchdog_pidfile()))
        try:
            os.remove(core._watchdog_pidfile())
        except OSError:
            pass
        self.watchdog_pid = None

    # ---- 结束：停看门狗 + 解键盘钩子 + 复位状态 + 退出进程 ----
    def _finish(self):
        if self._finished:
            return
        self._finished = True
        for t in (self._t_count, self._t_top, self._t_watch):
            if t is not None:
                t.stop()
        if self._guard_on:
            self._stop_guard()
        if self.blocker is not None:
            self.blocker.stop()
        if self._block_tm:
            try:
                core.set_taskmgr_disabled(False)
            except Exception:
                pass
        core.clear_lock_state()
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()


def run_lock(seconds, resumed=False, watched_by=None):
    """`--startlock` / `--resume`(模式一活跃) 的 Qt 实现：后端准备 + 显示 Qt 全屏锁屏。

    与本体 App.start_mode1_lock 的后端保持一致：需禁用任务管理器却未提权 → 先提权由新实例接管；
    落 lock_until；按是否提权布置「锁定期间」的智能自启（重启后 --resume 续锁）。
    """
    cfg = core.load_config()
    block_tm = bool(cfg.get("block_taskmgr", False))
    if block_tm and not core.is_admin() and not core.DRY_RUN and not resumed:
        if core.relaunch_as_admin(f"--startlock {int(seconds)}"):
            return
        block_tm = False
    cfg["mode"] = 1
    cfg["lock_until"] = time.time() + seconds
    core.save_config(cfg)
    if core.is_admin():
        core.create_boot_task()     # 提权：最高权限计划任务，重启后提权续锁
    else:
        core.set_run_key()          # 非提权：HKCU Run
    guard_on = bool(cfg.get("guard", True))

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        from qfluentwidgets import setTheme, Theme
        setTheme(Theme.DARK)        # 让「关机」确认框走深色
    except Exception:
        pass
    win = LockWindow(seconds, guard_on=guard_on, block_tm=block_tm)
    if resumed and watched_by:
        win.watchdog_pid = watched_by   # 恢复态：接管拉起自己的看门狗
    app.exec()
