# -*- coding: utf-8 -*-
"""LockDevice 一键打包为单文件 exe（Nuitka）。

用法：
  · 双击 build.bat（推荐，自动用 .venv）
  · 或在 venv 下运行：  python build.py
       python build.py tk qt         # 只打指定变体
       python build.py --upgrade     # 先把依赖升到最新再打包
       python build.py --clean       # 丢弃上次构建缓存（编译更慢）
       python build.py --mingw64     # 强制用 MinGW64 编译（本机无 MSVC 时）

产物：dist\\LockDevice-<版本>-<变体>.exe
  · 文件名自动带版本号；exe 属性（右键→详细信息）也写入版本信息。
  · 版本号自动从 lock_device.py 的 VERSION 读取，无需在这里手动改。

为什么用 Nuitka（替代 PyInstaller）：
  · onefile 支持「解压缓存」：--onefile-cache-mode=cached + 固定 tempdir-spec，
    解压内容跨次复用、不再每次启动都解压（PyInstaller 官方明确不做）。
  · 支持 onefile 启动图（--onefile-windows-splash-screen-image），盖住首启解压空窗。
  · 编译后跑得更快；产物直接是 C 编译的可执行文件。

运行时约定（lock_device.py 已适配，见其顶部「Nuitka 兼容层」）：
  · 冻结判定：Nuitka 不设 sys.frozen —— 本体用 "__compiled__" in globals() 识别，
    并在导入早期补齐 sys.frozen/_MEIPASS 兼容 shim。
  · 界面变体：各 exe 里打进 "_lockdevice_variant.txt"（qt / tk），本体读它决定界面，
    避免在后台命令（--guard/--watch/--plugin 等）里白白导入 PySide6。
"""
import os
import re
import sys
import shutil
import subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PY = sys.executable
NAME = "LockDevice"            # 内部名；安装到本机后固定为 LockDevice.exe
ICON = "lock_device.ico"
SRC = "lock_device.py"
SPLASH = "splash.png"          # onefile 启动图（缺失时自动用 scripts/make_splash.py 生成）
SPLASH_TOOL = os.path.join("scripts", "make_splash.py")
BUILD_ROOT = os.path.join("build_nuitka")   # Nuitka 的输出中间目录（按变体分子目录）


def read_version():
    """从 lock_device.py 读取 VERSION，保证与程序内版本号一致。"""
    try:
        with open(SRC, encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "0.0.0"


def version_tuple(v):
    parts = [int(x) for x in re.findall(r"\d+", v)][:4]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


VERSION = read_version()
VER4 = ".".join(str(x) for x in version_tuple(VERSION))   # 1.5.2 -> 1.5.2.0（exe 版本资源要 4 段）

print("=" * 50)
print("  LockDevice · 一键打包（Nuitka）")
print("=" * 50)
print("解释器:", PY, f"(Python {sys.version_info.major}.{sys.version_info.minor})")
print("版本号:", VERSION, "（自动读取自 lock_device.py）")

if not os.path.exists(ICON):
    print(f"⚠ 找不到图标 {ICON}，将不带图标打包。")
# onefile 启动图：没有就调 scripts/make_splash.py 生成（需要 Pillow；失败则不带启动图）
if not os.path.exists(SPLASH):
    if os.path.exists(SPLASH_TOOL):
        print("启动图缺失，尝试生成", SPLASH, "...")
        try:
            r = subprocess.run([PY, SPLASH_TOOL], capture_output=True, text=True)
            if r.returncode != 0:
                print("⚠ 生成失败（可 pip install pillow 后重试）：", (r.stderr or "").strip()[-200:])
        except OSError as e:
            print("⚠ 生成失败：", e)
    if not os.path.exists(SPLASH):
        print("⚠ 无启动图，onefile 首启解压期间将没有提示。")

REQ = "requirements.txt"


def _norm(name):
    """PEP 503 包名规范化，便于比对。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def required_pkgs():
    """从 requirements.txt 读需要的包名（去掉注释/版本号）；无文件则用默认。"""
    if os.path.exists(REQ):
        out = []
        for line in open(REQ, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if line:
                out.append(re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip())
        return [n for n in out if n]
    return ["customtkinter", "nuitka"]


def installed_pkgs():
    """pip list 里已安装的发行包名（规范化）集合。"""
    r = subprocess.run([PY, "-m", "pip", "list", "--format=freeze"],
                       capture_output=True, text=True)
    return {_norm(re.split(r"[=@ ]", ln, maxsplit=1)[0])
            for ln in (r.stdout or "").splitlines() if ln.strip()}


def ensure_build_env():
    """确保 nuitka 已安装；--upgrade 时把所有依赖升到最新。"""
    upgrade = any(a in ("--upgrade", "-U", "upgrade") for a in sys.argv[1:])
    if upgrade:
        print("\n[1/2] 升级所有依赖到最新版（--upgrade，不管是否已安装）...")
        args = ["-r", REQ] if os.path.exists(REQ) else required_pkgs()
        subprocess.run([PY, "-m", "pip", "install", "--upgrade", *args])
    else:
        print("\n[1/2] 检测依赖（pip list，只装缺失的；加 --upgrade 可强制全升级）...")
        have = installed_pkgs()
        _missing = [p for p in required_pkgs() if _norm(p) not in have]
        if _missing:
            print("  缺少：" + ", ".join(_missing) + " → 安装中 ...")
            subprocess.run([PY, "-m", "pip", "install", *_missing])
        else:
            print("  依赖已齐全，跳过安装。")
    r = subprocess.run([PY, "-m", "nuitka", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        print("❌ 无法运行 Nuitka：", (r.stderr or "").strip()[:300])
        sys.exit(1)


# 4 个变体：(后缀, 含 Qt 界面, 含插件, 说明)
VARIANTS = [
    ("tk",         False, False, "tkinter · 无插件（最小）"),
    ("tk-plugins", False, True,  "tkinter · 全插件"),
    ("qt-plugins", True,  True,  "Qt · 全插件"),
    ("qt",         True,  False, "Qt · 无插件"),
]
_names = {s for s, *_ in VARIANTS}
_flags = {a for a in sys.argv[1:] if a.startswith("-")}
_only = [a for a in sys.argv[1:] if a in _names]   # python build.py qt / tk-plugins ...（不指定则全打）
_todo = [v for v in VARIANTS if not _only or v[0] in _only]


def write_variant_marker(path, suffix):
    """把变体标注写进打包内容：本体据此直接选界面（不必导入 PySide6 探测）。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("qt" if suffix.startswith("qt") else "tk")


def build_one(suffix, with_gui, with_plugins, desc):
    print(f"\n===== 构建 {suffix} · {desc} =====")
    out_dir = os.path.join(BUILD_ROOT, suffix)
    marker = os.path.join(out_dir, "_variant_marker")
    os.makedirs(out_dir, exist_ok=True)
    write_variant_marker(marker, suffix)

    a = [PY, "-m", "nuitka",
         "--mode=onefile",
         "--assume-yes-for-downloads",       # 缺编译器时自动下载 MinGW64（有 MSVC 则不用）
         "--windows-console-mode=disable",   # 等价 PyInstaller 的 --windowed
         "--output-dir=" + out_dir,
         "--output-filename=" + f"{NAME}-{VERSION}-{suffix}.exe",
         # exe 属性（右键→详细信息）：与 PyInstaller 时期的版本资源等价
         "--company-name=" + NAME,
         "--product-name=LockDevice 专注锁定",
         "--file-version=" + VER4,
         "--product-version=" + VER4,
         # onefile 解压缓存：解压内容留在固定目录、跨次复用（首启解压一次，之后不再解压）
         "--onefile-cache-mode=cached",
         "--onefile-tempdir-spec={CACHE_DIR}/LockDevice/bin/{VERSION}",
         # 变体标注 + 插件目录（插件按数据文件原样带，保留「热添加/覆盖」能力）
         "--include-data-files=" + f"{marker}=_lockdevice_variant.txt",
    ]
    if with_plugins and os.path.isdir("plugins"):
        # 插件按「数据文件」原样带（保留热添加/热覆盖能力）。
        # 注意：Nuitka 默认不收 .py 作为数据文件（视为代码），必须用显式文件模式强制；
        # 用绝对路径 + *.py 通配，避免把 __pycache__ 等带进去。
        _plug_pat = os.path.join(os.path.abspath("plugins"), "*.py")
        a += ["--include-data-files=" + _plug_pat + "=plugins/"]
        # 文件夹插件（plugins/<目录>/plugin.py + 图标等资源）：逐目录原样带
        for _name in sorted(os.listdir("plugins")):
            _p = os.path.join("plugins", _name)
            if (_name.startswith(("_", ".")) or _name == "__pycache__"
                    or not os.path.isdir(_p) or not os.path.isfile(os.path.join(_p, "plugin.py"))):
                continue
            a += ["--include-data-dir=" + os.path.abspath(_p) + "=plugins/" + _name]
    if os.path.exists(ICON):
        a += ["--windows-icon-from-ico=" + ICON,
              "--include-data-files=" + f"{ICON}={ICON}"]
    if os.path.exists(SPLASH):
        a += ["--onefile-windows-splash-screen-image=" + SPLASH]
    if "--mingw64" in _flags:
        a += ["--mingw64"]
    if "--clean" in _flags:
        a += ["--remove-output"]

    if with_gui:    # Qt 现代界面：PySide6/qfluentwidgets；qt 变体彻底不含 tk
        a += ["--enable-plugin=pyside6",
              "--include-package-data=qfluentwidgets",
              "--nofollow-import-to=tkinter",
              "--nofollow-import-to=customtkinter"]
    else:           # tkinter：收 customtkinter（含主题/字体数据），排除 Qt
        a += ["--enable-plugin=tk-inter",
              "--include-package-data=customtkinter",
              "--nofollow-import-to=PySide6",
              "--nofollow-import-to=qfluentwidgets",
              "--nofollow-import-to=shiboken6",
              "--nofollow-import-to=gui"]
    a.append(SRC)
    ret = subprocess.run(a).returncode
    built = os.path.join(out_dir, f"{NAME}-{VERSION}-{suffix}.exe")
    out = os.path.join("dist", f"{NAME}-{VERSION}-{suffix}.exe")
    if ret == 0 and os.path.exists(built):
        os.makedirs("dist", exist_ok=True)
        try:
            if os.path.exists(out):
                os.remove(out)
            os.replace(built, out)
            return out
        except OSError as e:
            print("⚠ 移动到 dist 失败：", e)
            return built
    return None


ensure_build_env()

print(f"\n[2/2] 打包（{len(_todo)} 个变体，Nuitka 首次编译较慢，之后有缓存加速）...")
results = [(s, d, build_one(s, g, p, d)) for s, g, p, d in _todo]

print("\n" + "=" * 58)
print(f"  LockDevice v{VERSION} · 打包结果（dist\\）")
print("=" * 58)
for suffix, desc, out in results:
    if out and os.path.exists(out):
        size = os.path.getsize(out) / (1024 * 1024)
        print(f"  ✅ {size:5.1f} MB  {os.path.basename(out):<30} {desc}")
    else:
        print(f"  ❌ 失败        {NAME}-{VERSION}-{suffix}.exe   {desc}")
print("=" * 58)
