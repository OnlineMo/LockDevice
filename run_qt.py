# -*- coding: utf-8 -*-
"""启动 PySide6 + qfluentwidgets 版界面（重构中）。

    python run_qt.py

后端仍复用 lock_device.py；本文件只是新前端的入口。
"""
from gui_qt.app import run

if __name__ == "__main__":
    run()
