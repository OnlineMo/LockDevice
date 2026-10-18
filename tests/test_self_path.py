# -*- coding: utf-8 -*-
"""独立自测：_self_path() 在冻结(onefile)态下必须返回「真实存在」的入口 exe。

背景：Nuitka onefile 里 sys.executable 指向解压目录中的虚拟 python.exe（磁盘上并不存在），
而引导层保留的原始入口路径在 sys.argv[0]（真实、存在）。relaunch_as_admin / _spawn /
do_install / 任务动作等都依赖 _self_path()——指到幽灵路径时会静默失败
（典型症状：「更新到新版本」按钮点了没反应）。

运行：python tests\\test_self_path.py
"""
import os
import shutil
import sys
import tempfile
import unittest.mock as mock


def main():
    tmp = tempfile.mkdtemp(prefix="ld_selfpath_test_")
    # import 前把目录环境指到临时区
    os.environ["LOCALAPPDATA"] = tmp
    os.environ["ProgramFiles"] = os.path.join(tmp, "PF")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    failures = []
    try:
        import lock_device as ld

        real_entry = os.path.join(tmp, "Downloads", "LockDevice-1.6.2-qt.exe")
        os.makedirs(os.path.dirname(real_entry), exist_ok=True)
        open(real_entry, "w").close()

        phantom = os.path.join(tmp, "cache", "LockDevice", "bin", "1.6.2.0", "python.exe")
        os.makedirs(os.path.dirname(phantom), exist_ok=True)   # 目录在、文件不在（模拟解压目录）

        def same(a, b):
            return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

        with mock.patch.object(ld, "IS_FROZEN", True):
            # 用例1：onefile 幽灵 sys.executable → 应回退到 argv[0]（真实入口）
            with mock.patch.object(ld.sys, "executable", phantom), \
                 mock.patch.object(ld.sys, "argv", [real_entry, "--selftest"]):
                got = ld._self_path()
                if not same(got, real_entry):
                    failures.append("幽灵 exec 未回退 argv[0]：期望 %s，实际 %s" % (real_entry, got))

            # 用例2：sys.executable 真实存在 → 保持原样（如安装目录 app\\ 副本 / 旧格式）
            real_exe = os.path.join(tmp, "PF", "LockDevice", "app", "LockDevice.exe")
            os.makedirs(os.path.dirname(real_exe), exist_ok=True)
            open(real_exe, "w").close()
            with mock.patch.object(ld.sys, "executable", real_exe), \
                 mock.patch.object(ld.sys, "argv", [os.path.join(tmp, "elsewhere.exe")]):
                got = ld._self_path()
                if not same(got, real_exe):
                    failures.append("真实 exec 被错误替换：期望 %s，实际 %s" % (real_exe, got))

            # 用例3：都不可用 → 保持旧行为（返回 sys.executable）
            with mock.patch.object(ld.sys, "executable", phantom), \
                 mock.patch.object(ld.sys, "argv", [os.path.join(tmp, "missing.exe")]):
                got = ld._self_path()
                if not same(got, phantom):
                    failures.append("全缺失时应保持旧行为：期望 %s，实际 %s" % (phantom, got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("FAIL:")
        for m in failures:
            print("  -", m)
        sys.exit(1)
    print("PASS: _self_path 行为正确")


if __name__ == "__main__":
    main()
