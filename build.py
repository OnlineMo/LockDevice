# -*- coding: utf-8 -*-
"""LockDevice 一键打包为单文件 exe（PyInstaller）。

用法：
  · 双击 build.bat（推荐，自动用 .venv）
  · 或在 venv 下运行：  python build.py

产物：dist\\LockDevice-<版本>.exe
  · 文件名自动带版本号；exe 属性（右键→详细信息）也写入版本信息。
  · 版本号自动从 lock_device.py 的 VERSION 读取，无需在这里手动改。
"""
import os
import re
import sys
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
VER_FILE = "_version_info.txt"  # 临时生成的版本资源，打包后自动删除


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


def write_version_info(v):
    """生成 Windows 版本资源文件，让 exe 属性里显示文件/产品版本。"""
    fv = version_tuple(v)
    text = f"""# UTF-8 - PyInstaller 版本资源（build.py 自动生成）
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={fv}, prodvers={fv},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404b0', [
      StringStruct('CompanyName', 'LockDevice'),
      StringStruct('FileDescription', 'LockDevice 专注锁定'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'LockDevice'),
      StringStruct('OriginalFilename', 'LockDevice.exe'),
      StringStruct('ProductName', 'LockDevice 专注锁定'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x0804, 1200])])])
"""
    with open(VER_FILE, "w", encoding="utf-8") as f:
        f.write(text)


VERSION = read_version()
OUT_NAME = f"{NAME}-{VERSION}.exe"   # 最终分发文件名，带版本号

print("=" * 50)
print("  LockDevice · 一键打包")
print("=" * 50)
print("解释器:", PY)
print("版本号:", VERSION, "（自动读取自 lock_device.py）")

if not os.path.exists(ICON):
    print(f"⚠ 找不到图标 {ICON}，将不带图标打包。")

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
    return ["customtkinter", "pyinstaller"]


def installed_pkgs():
    """pip list 里已安装的发行包名（规范化）集合。"""
    r = subprocess.run([PY, "-m", "pip", "list", "--format=freeze"],
                       capture_output=True, text=True)
    return {_norm(re.split(r"[=@ ]", ln, maxsplit=1)[0])
            for ln in (r.stdout or "").splitlines() if ln.strip()}


UPGRADE = any(a in ("--upgrade", "-U", "upgrade") for a in sys.argv[1:])
if UPGRADE:
    print("\n[1/2] 升级所有依赖到最新版（--upgrade，不管是否已安装）...")
    args = ["-r", REQ] if os.path.exists(REQ) else required_pkgs()
    subprocess.run([PY, "-m", "pip", "install", "--upgrade", *args])
else:
    print("\n[1/2] 检测依赖（pip list，只装缺失的；加 --upgrade 可强制全升级）...")
    _missing = [p for p in required_pkgs() if _norm(p) not in installed_pkgs()]
    if _missing:
        print("  缺少：" + ", ".join(_missing) + " → 安装中 ...")
        subprocess.run([PY, "-m", "pip", "install", *_missing])
    else:
        print("  依赖已齐全，跳过安装。")

write_version_info(VERSION)

# 4 个变体：(后缀, 含 Qt 界面, 含插件, 说明)
VARIANTS = [
    ("tk",         False, False, "tkinter · 无插件（最小）"),
    ("tk-plugins", False, True,  "tkinter · 全插件"),
    ("qt-plugins", True,  True,  "Qt · 全插件"),
    ("qt",         True,  False, "Qt · 无插件"),
]
_names = {s for s, *_ in VARIANTS}
_only = [a for a in sys.argv[1:] if a in _names]   # python build.py qt / tk-plugins ...（不指定则全打）
_todo = [v for v in VARIANTS if not _only or v[0] in _only]


def build_one(suffix, with_gui, with_plugins, desc):
    print(f"\n===== 构建 {suffix} · {desc} =====")
    a = [PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
         "--name", NAME, "--version-file", VER_FILE]
    if with_gui:    # Qt 现代界面：只收 gui 模块 + qfluentwidgets 资源；PySide6 交给自动分析（不 collect-all）
        a += ["--hidden-import", "gui.app", "--hidden-import", "gui.lock",
              "--collect-all", "qfluentwidgets",
              # qt 版彻底不含 tk：模式一锁屏走 gui.lock（Qt 原生），故排除 customtkinter 与 tkinter 本身
              "--exclude-module", "customtkinter",
              "--exclude-module", "tkinter", "--exclude-module", "_tkinter"]
        # qfluentwidgets 是纯 QWidget 组件，排除这些重型 Qt 模块（仅 WebEngine 就上百 MB）→ 大幅瘦身
        for m in ("QtWebEngineCore", "QtWebEngineWidgets", "QtWebEngineQuick", "QtWebChannel",
                  "QtQml", "QtQuick", "QtQuick3D", "QtQuickWidgets", "QtQuickControls2",
                  "Qt3DCore", "Qt3DRender", "Qt3DExtras", "QtCharts", "QtDataVisualization",
                  "QtMultimedia", "QtMultimediaWidgets", "QtPdf", "QtPdfWidgets", "QtSensors",
                  "QtSerialPort", "QtBluetooth", "QtPositioning", "QtLocation",
                  "QtDesigner", "QtHelp", "QtTest"):
            a += ["--exclude-module", "PySide6." + m]
    else:           # tkinter：收 customtkinter，排除 Qt，体积最小
        a += ["--collect-all", "customtkinter",
              "--exclude-module", "PySide6", "--exclude-module", "qfluentwidgets",
              "--exclude-module", "shiboken6", "--exclude-module", "gui"]
    if with_plugins and os.path.isdir("plugins"):
        a += ["--add-data", "plugins" + os.pathsep + "plugins"]
    if os.path.exists(ICON):
        a += ["--icon", ICON, "--add-data", f"{ICON}{os.pathsep}."]
    a.append(SRC)
    ret = subprocess.run(a).returncode
    built = os.path.join("dist", NAME + ".exe")
    out = os.path.join("dist", f"{NAME}-{VERSION}-{suffix}.exe")
    if ret == 0 and os.path.exists(built):
        try:
            if os.path.exists(out):
                os.remove(out)
            os.replace(built, out)
            return out
        except OSError as e:
            print("⚠ 重命名失败：", e)
            return built
    return None


print(f"\n[2/2] 打包（{len(_todo)} 个变体，首次较慢）...")
results = [(s, d, build_one(s, g, p, d)) for s, g, p, d in _todo]

try:
    os.remove(VER_FILE)
except OSError:
    pass

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
