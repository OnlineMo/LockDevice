# LockDevice 插件开发指南

> 后续所有插件都按本文档编写。

## 一、概览

- 插件 = `plugins/` 目录下的一个 `.py` 模块，程序启动时**自动识别加入**；打包时整个 `plugins/` 打进 exe（默认包含所有插件）。
- 插件**只做两件事**：① 实现**后端逻辑**（用 api 锁机 / 提权、读写配置，按自己的逻辑判断…）；② **声明前端**（`SETTINGS` / `ACTIONS` 都是纯数据 schema）。
- **界面完全由本体渲染**，插件不碰任何 GUI 组件。好处：本体日后从 tkinter 换成 Qt，插件**零改动**。
- **铁律**：不 `import lock_device`、不 `import customtkinter`/不建任何窗口、只用**标准库 + 注入的 `api`**。
  （PyInstaller onefile 下入口以 `__main__` 运行，`import` 本体会失败/重复执行——所以本体把能力打包成 `api` 注入。）

## 设计原则：功能逻辑归插件，本体只给「通用能力」

**给插件足够的自由——「什么时候做、怎么做、做多久」由插件自己决定，本体不替它写死。**

- 本体只提供**通用能力**（`api`：锁机 / 建删任务 / 读写配置 / 开机自启回调 等），**不内置任何某功能专属的逻辑**。
- 插件用这些能力**自己实现完整功能**。例：`auto_lock` 自己算「是否在时间窗口内、锁剩余多久」；将来「跳过节假日 / 按周 / 按月 / 番茄钟」等也**全写在插件里**，本体一行都不用改。
- ⚠ **反面教材**：让本体用「固定时间的计划任务」去替插件触发锁定——逻辑被写死在本体、插件失去自由，还处理不了「23:00 锁 30 分钟，23:05 才开机应只锁 25 分钟，23:35 开机则不该锁」这类情况。正确做法是插件在 `on_boot` 里按当前时间自己算（见第六、七节）。

## 二、放哪

两种格式（可混用；`_` / `.` 开头的文件与目录会被忽略）：

1. **单文件插件**：`plugins/<你的插件 id>.py`——一个 .py 走天下（推荐；图标可用 emoji / base64 内嵌图片）。
2. **文件夹插件**：`plugins/<目录>/plugin.py`（可附带资源文件，如 `icon.png`）——适合需要图片资源的插件；
   打包（`python build.py`）会整目录带上，热添加（exe 同级 `plugins/`）同样识别。

调试是否被识别：`python lock_device.py --list-plugins`（打包后 `LockDevice.exe --list-plugins` 同样可用，用来验证冻结态加载）。

## 三、契约（模块要暴露的东西）

### 1. `PLUGIN`（必需，dict）
```python
PLUGIN = {
    "id": "auto_lock",        # 唯一标识：配置命名空间 / CLI 路由 / 任务名都用它
    "name": "自动锁机",        # 显示名
    "version": "1.0.0",
    "button": "⏰  自动锁机",   # 主页按钮文字（缺省用 name）
    "icon": "⏰",              # 插件图标（可选），见下
    "autostart": False,       # 是否需要「本体开机自启」，见第六节
}
```

**`icon`（可选）——插件图标**，四种形态（失败不影响加载，只是显示层）：

| 形态 | 写法 | 效果 |
|---|---|---|
| emoji | `"icon": "⏰"` | Qt 侧栏/管理页画成图标；tk 端作文字前缀 —— **双端一致，推荐** |
| 内嵌图片 | `"icon": {"base64": "<PNG/GIF 的 base64>"}` | 单文件插件零依赖带图（**双端一致**；也接受 `data:image/png;base64,` 前缀） |
| 图片文件 | `"icon": {"file": "icon.png"}` | 相对**插件文件所在目录**（配合文件夹插件放资源） |
| FluentIcon | `"icon": {"fluent": "Camera"}` | Qt 原生风格（名字不区分大小写，如 `Camera` / `CAMERA`）；tk 端回退为无图标 |

> 图片建议方形、≥28px；tk 端走 Tk 原生图片（仅 **PNG/GIF**），想全格式统一建议用 PNG。

### 2. `SETTINGS`（可选，list）——前端声明，本体渲染成统一表单
```python
SETTINGS = [
    {"key": "enabled", "label": "启用",         "type": "bool",   "default": False},
    {"key": "time",    "label": "开始时间",      "type": "time",   "default": "22:00"},
    {"key": "minutes", "label": "时长（分钟）",   "type": "int",    "default": 30,
     "min": 1, "max": 1440, "step": 5},
    {"key": "mode",    "label": "方式",         "type": "choice", "default": "锁屏",
     "options": ["锁屏", "关机"]},
    {"key": "note",    "label": "备注",         "type": "str",    "default": ""},
    {"label": "状态",  "type": "status", "fn": "get_status"},
    {"key": "items",   "label": "条目", "type": "items", "default": [],
     "display": "{name} · {time}", "click": "run_item", "add": "add_item", "remove": "remove_item"},
]
```

| `type` | 渲染（Qt / tk） | 存储 |
|---|---|---|
| `bool` | 开关 | bool |
| `int` / `str` | 文本输入框 | int / str |
| `int` + `min`/`max`/`step` | **数字框**（SpinBox） | int |
| `choice` | 下拉框（需 `options`） | str |
| `time` | **时间选择器**（TimeEdit / 时+分下拉；存 `"HH:MM"` 字符串） | str |
| `status` | 只读动态文本：渲染时调 `fn(api)` 显示返回字符串（需 `fn`，可无 `key`） | 不存储 |
| `items` | **条目列表**：每项按 `display` 模板显示；`click`/`remove` 回调 `fn(api, index)`、`add` 回调 `fn(api)`（均可选） | `list[dict]` |

- 值存在**与本体共用**的 `config.json` 里的 `cfg["plugins"][<id>][<key>]`，按插件分区。
- `items` 的增删改**全归插件**：回调里用 `api.prompt()` 收集输入、`api.save_settings()` 写回、**`api.refresh()` 让列表立刻刷新**（本体只回调，不替你改数据）。
- 主页会给有 `SETTINGS`/`ACTIONS` 的插件放一个按钮（进入该插件单页）；另有统一「⚙ 设置」页聚合所有插件的 `SETTINGS`。
- `api.prompt()` 弹窗支持同样的字段定义（`status` / `items` 除外）。

### 3. `ACTIONS`（可选，list）——声明按钮，本体渲染，点击调同名后端函数
```python
ACTIONS = [{"label": "🔒  立即锁一次", "fn": "lock_now"}]

def lock_now(api, values):      # 可选收「当前表单值」（含未保存的改动）
    ...                          # 只要 fn(api) 也可以（签名探测，两种都支持）
```

## 四、后端函数（都可选，签名固定）

| 函数 | 何时调用 | 典型用途 |
|---|---|---|
| `on_settings_saved(api, values)` | 用户在设置页/插件页点「保存」后 | `values` = 该插件最新设置；据此登记/注销开机自启、或即时生效 |
| `on_uninstall(api)` | 卸载 / 清除数据时 | `api.set_autostart(id, False)` 等清理 |
| `on_boot(api)` | 每次登录（仅当 `autostart=True` 且已登记） | 按**当前时间**判断该不该做、做多久（如 auto_lock 检查时间窗口） |
| `handle_cli(argv, api)` | `api.run_admin` 提权后回调 | 执行需管理员的操作（此时已是管理员） |
| `<action fn>(api[, values])` | 点击 `ACTIONS` 里声明的按钮 | 任意即时动作；`values` = 当前表单值（含未保存改动），可选 |

## 五、`api`（本体注入的能力，你**唯一**的依赖）

> **本体对插件只提供三类核心能力：锁机 + 唤醒 + 提权。** 其余（何时锁、锁多久、怎么判断…）都由插件自己实现。

**① 锁机**
- `api.start_lock(minutes, mode=1)`：锁定 `minutes` 分钟（`mode=1` 全屏锁 / `mode=2` 定时关机）。GUI 上下文直接锁；`on_boot` 等 CLI 上下文会自动拉起新进程锁定。

**② 唤醒（开机自启）**
- `api.set_autostart(id, on)`：登记/注销「登录时唤醒本插件」。登记后每次登录本体回调你的 `on_boot(api)`，你在里面**自己判断**该不该做、做多久。见第六节。

**③ 提权（继承本体管理员权限）**
- `api.is_admin() -> bool`：当前是否管理员。
- `api.run_admin(id, *args)`：需要管理员时调用——已是管理员返回 `True`（当场做）；否则提权重启并回调你的 `handle_cli(argv, api)`（`argv` 含 `--plugin <id> *args`），返回是否已发起提权。

**支持能力**
- 配置（共用 `config.json`，按插件分区）：`api.get_settings(id) -> dict` / `api.save_settings(id, dict)`
- 对话框（工具箱无关，别用 tkinter）：`api.info(msg[,title])` / `api.confirm(msg[,title]) -> bool` / `api.error(msg[,title])`
- **通用输入弹窗**：`api.prompt(title, fields) -> dict | None`——`fields` 与 `SETTINGS` 同款字段定义（`bool`/`choice`/`int`/`str`/`time`）；用户取消返回 `None`。配 `items` 控件做「添加条目」就是它。
- **动态刷新**：`api.refresh()`——重渲染「当前显示的插件页」（把最新配置立刻显示出来）。`items` 回调里改完数据后调用它，列表即刻更新。
- **规范入口与任务动作**：`api.self_path()`（本体规范 exe：安装态 = 安装目录 `app\`、绿色 = 真实入口 exe）/ `api.action_for(extra_args)`（计划任务 `(Command, Arguments)`，含源码态处理）。
  ⚠ **建计划任务 / 拉起本体时必须用它，别用 `sys.executable`**：编译版（Nuitka onefile）下 `sys.executable` 指向解压缓存里的幽灵 `python.exe`（磁盘上不存在；程序更新清理缓存后，你的任务会全部失效）。
- 环境：`api.is_installed()` / `api.DRY_RUN` / `api.VERSION` / `api.log(msg)`

## 六、开机自启：需要 vs 不需要（本体会「记住」）

- **需要**（如 `auto_lock`）：开机 / 登录时要**跑逻辑**才生效——例如 auto_lock 每次登录检查「现在是否在锁机时间窗口内、该锁剩余多久」。设 `autostart=True`，并在**启用时** `api.set_autostart(id, True)`、**停用时** `False`。本体据此建/删共享登录任务 `LockDevice_PluginBoot`，登录时回调各登记插件的 `on_boot(api)`。
  - ⚠ **别用「固定时间的计划任务直接触发固定时长锁定」**——迟到开机会锁满、过点还会锁，都是错的。要在 `on_boot` 里**按当前时间算**该不该做、做多久（剩余时间）。
- **不需要**：只在程序打开时才用、或做一次性持久系统设置的插件。设 `autostart=False`（默认），不用管。

## 七、完整示例（`plugins/auto_lock.py`，时间窗口 + 开机自启）

```python
import time

PLUGIN = {"id": "auto_lock", "name": "自动锁机", "version": "1.0.1",
          "button": "⏰  自动锁机", "autostart": True}   # 需要开机自启：登录时检查窗口

SETTINGS = [
    {"key": "enabled", "label": "启用每日自动锁机", "type": "bool", "default": False},
    {"key": "time",    "label": "每天开始时间 (HH:MM)", "type": "str", "default": "22:00"},
    {"key": "minutes", "label": "锁机时长（分钟）", "type": "int", "default": 30},
]
ACTIONS = [{"label": "🔒  立即锁一次", "fn": "lock_now"}]

def _remaining(vals):
    """现在若在今天的窗口 [start, start+dur) 内，返回剩余分钟，否则 None。"""
    hh, mm = map(int, str(vals.get("time", "22:00")).split(":"))
    start, dur = hh * 60 + mm, max(1, int(vals.get("minutes", 30)))
    lt = time.localtime(); now = lt.tm_hour * 60 + lt.tm_min
    return (start + dur - now) if (start <= now < start + dur) else None

def on_settings_saved(api, values):
    # 只登记/注销开机自启，不建定时任务；何时锁、锁多久由 on_boot 自己算
    api.set_autostart("auto_lock", bool(values.get("enabled")))

def on_boot(api):                # 每次登录被回调：在窗口内就锁「剩余时间」
    vals = api.get_settings("auto_lock")
    if vals.get("enabled"):
        rem = _remaining(vals)
        if rem:
            api.start_lock(rem)

def on_uninstall(api):
    api.set_autostart("auto_lock", False)

def lock_now(api):
    m = max(1, int(api.get_settings("auto_lock").get("minutes", 30)))
    if api.confirm(f"立即全屏锁定 {m} 分钟？"):
        api.start_lock(m)
```

## 八、铁律 & 打包

- **不** `import lock_device`、**不** `import customtkinter`、**不**建任何窗口——UI 全由本体按你的 `SETTINGS`/`ACTIONS` 渲染。
- 只用**标准库 + `api`**。若确实要用第三方库：加进 `requirements.txt`，并确保 PyInstaller 能收集到（onefile 下 `plugins/` 作为 data 打包，插件的 `import` **不被静态分析**，需要时在 `build.py` 里加 hiddenimports/collect）。
- 放进 `plugins/` 即自动加入；`python build.py` 默认把整个 `plugins/` 打进 exe。
- 坏插件被本体 `try/except` 隔离——只记 `error.log`、不拖垮其它插件和本体。

## 九、插件 UI 2.0（已上线）

时间选择器（`time`）/ 数字框（`int` + `min`/`max`/`step`）/ 动态状态（`status`）/ 条目列表（`items`）、
`api.prompt()` 弹窗收集输入、`api.refresh()` 动态刷新、动作函数可选收表单值——见第三、五节。
**插件图标**（emoji / base64 内嵌图片 / 文件 / FluentIcon）与**文件夹插件**格式已支持——见第二、三节。
