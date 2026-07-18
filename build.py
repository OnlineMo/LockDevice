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

print("\n[2/2] 打包中（首次较慢，请耐心等待）...")
args = [
    PY, "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--onefile",                       # 打成单个 exe
    "--windowed",                      # GUI 程序，无控制台黑框
    "--name", NAME,
    "--version-file", VER_FILE,        # 版本信息写入 exe 属性
    "--collect-all", "customtkinter",  # 打包 customtkinter 的主题/资源（必须）
    SRC,
]
if os.path.exists(ICON):
    args[args.index(SRC):args.index(SRC)] = [
        "--icon", ICON, "--add-data", f"{ICON};.",  # 程序图标 + 内嵌供窗口使用
    ]

ret = subprocess.run(args).returncode

# 打包出的是 dist\LockDevice.exe，改名为带版本号的最终文件
built = os.path.join("dist", NAME + ".exe")
out = os.path.join("dist", OUT_NAME)
if ret == 0 and os.path.exists(built):
    try:
        if os.path.exists(out):
            os.remove(out)
        os.replace(built, out)
    except OSError as e:
        print("⚠ 重命名为带版本号文件失败：", e)
        out = built

try:
    os.remove(VER_FILE)
except OSError:
    pass

print("\n" + "=" * 50)
if ret == 0 and os.path.exists(out):
    size = os.path.getsize(out) / (1024 * 1024)
    print(f"✅ 打包成功！({size:.1f} MB)  v{VERSION}")
    print("   exe 路径:", os.path.abspath(out))
    print("   文件名已带版本号；右键属性→详细信息 也可看到版本。")
    print("   双击即用，无需 Python / venv。")
    print("   提示：想安装到本机（开机自启/免UAC/定时关机），在程序里点「安装到本机」即可。")
else:
    print("❌ 打包失败，请往上翻看错误输出。")
print("=" * 50)
