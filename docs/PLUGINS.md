# LockDevice 插件开发指南

> 后续所有插件都按本文档编写。

## 一、概览

- 插件 = `plugins/` 目录下的一个 `.py` 模块，程序启动时**自动识别加入**；打包时整个 `plugins/` 打进 exe（默认包含所有插件）。
- 插件**只做两件事**：① 实现**后端逻辑**（建计划任务、锁机、读写配置…）；② **声明前端**（`SETTINGS` / `ACTIONS` 都是纯数据 schema）。
- **界面完全由本体渲染**，插件不碰任何 GUI 组件。好处：本体日后从 tkinter 换成 Qt，插件**零改动**。
- **铁律**：不 `import lock_device`、不 `import customtkinter`/不建任何窗口、只用**标准库 + 注入的 `api`**。
  （PyInstaller onefile 下入口以 `__main__` 运行，`import` 本体会失败/重复执行——所以本体把能力打包成 `api` 注入。）

## 二、放哪

`plugins/<你的插件 id>.py`。以下划线 `_` 开头的文件会被忽略。

调试是否被识别：`python lock_device.py --list-plugins`（打包后 `LockDevice.exe --list-plugins` 同样可用，用来验证冻结态加载）。

## 三、契约（模块要暴露的东西）

### 1. `PLUGIN`（必需，dict）
```python
PLUGIN = {
    "id": "auto_lock",        # 唯一标识：配置命名空间 / CLI 路由 / 任务名都用它
    "name": "自动锁机",        # 显示名
    "version": "1.0.0",
    "button": "⏰  自动锁机",   # 主页按钮文字（缺省用 name）
    "autostart": False,       # 是否需要「本体开机自启」，见第六节
}
```

### 2. `SETTINGS`（可选，list）——前端声明，本体渲染成统一表单
```python
SETTINGS = [
    {"key": "enabled", "label": "启用",         "type": "bool",   "default": False},
    {"key": "time",    "label": "时间 (HH:MM)", "type": "str",    "default": "22:00"},
    {"key": "minutes", "label": "时长（分钟）",  "type": "int",    "default": 30},
    {"key": "mode",    "label": "方式",         "type": "choice", "default": "锁屏",
     "options": ["锁屏", "关机"]},
]
```
- `type` ∈ `bool` / `int` / `str` / `choice`（`choice` 需 `options`）。
- 值存在**与本体共用**的 `config.json` 里的 `cfg["plugins"][<id>][<key>]`，按插件分区。
- 主页会给有 `SETTINGS`/`ACTIONS` 的插件放一个按钮（进入该插件单页）；另有统一「⚙ 设置」页聚合所有插件的 `SETTINGS`。

### 3. `ACTIONS`（可选，list）——声明按钮，本体渲染，点击调同名后端函数
```python
ACTIONS = [{"label": "🔒  立即锁一次", "fn": "lock_now"}]

def lock_now(api):
    ...
```

## 四、后端函数（都可选，签名固定）

| 函数 | 何时调用 | 典型用途 |
|---|---|---|
| `on_settings_saved(api, values)` | 用户在设置页/插件页点「保存」后 | `values` = 该插件最新设置；据此建/删计划任务 |
| `on_uninstall(api)` | 卸载 / 清除数据时 | 删掉自己建的任务等残留 |
| `on_boot(api)` | 开机登录（仅当 `autostart=True` 且已登记） | 重新拉起需要常驻的东西 |
| `handle_cli(argv, api)` | 你建的任务用 `--plugin <id> …` 回调时 | 自定义计划任务的落点 |
| `<action fn>(api)` | 点击 `ACTIONS` 里声明的按钮 | 任意即时动作 |

## 五、`api`（本体注入的能力，你**唯一**的依赖）

**配置（共用 config）**
- `api.get_settings(id) -> dict`
- `api.save_settings(id, dict)`

**锁机（复用本体，别自己写锁）**
- `api.lock_command(minutes, mode=1) -> str`：返回计划任务动作参数（`--startlock <秒>` / `mode=2` 为 `--startshutdown <分>`）
- `api.start_lock(minutes, mode=1)`：**立即**锁（仅 GUI 上下文有效）

**计划任务**
- `api.register_task(name, trigger_xml, extra_args, **kw) -> (ok, msg)`
  默认：当前用户 · `LeastPrivilege` · 免 UAC · 仅计划触发。`kw` 可覆盖 `run_level`/`system`/`on_demand`/`desc`。
- `api.delete_task(name)` / `api.task_exists(name)`
- `api.daily_trigger(hh, mm) -> xml`：每天 `hh:mm` 触发（`CalendarTrigger`）
- `api.action_for(extra_args) -> (cmd, args)`：低层，自己拼 XML 时用

**开机自启记账**
- `api.set_autostart(id, on)`：登记/注销「需要本体开机自启」，见第六节

**环境**
- `api.is_admin()` / `api.is_installed()` / `api.relaunch_as_admin(args)` / `api.DRY_RUN` / `api.VERSION` / `api.log(msg)`

**对话框（工具箱无关，别用 tkinter）**
- `api.info(msg[, title])` / `api.confirm(msg[, title]) -> bool` / `api.error(msg[, title])`

## 六、开机自启：需要 vs 不需要（本体会「记住」）

- **不需要**（推荐，如 `auto_lock`）：靠你**自己建的计划任务**持久——Windows 计划任务重启后照常触发，本体根本不用开机跑。设 `autostart=False`，什么都不用管。
- **需要**：你的功能必须让本体/后台在开机时跑起来才生效。设 `autostart=True`，并在**启用时** `api.set_autostart(id, True)`、**停用时** `api.set_autostart(id, False)`。本体会据此建/删一个共享的登录任务 `LockDevice_PluginBoot`，开机登录时回调各登记插件的 `on_boot(api)`。

## 七、完整示例（`plugins/auto_lock.py`，最小可用）

```python
PLUGIN = {"id": "auto_lock", "name": "自动锁机", "version": "1.0.0",
          "button": "⏰  自动锁机", "autostart": False}

SETTINGS = [
    {"key": "enabled", "label": "启用每日自动锁机", "type": "bool", "default": False},
    {"key": "time",    "label": "每天锁机时间 (HH:MM)", "type": "str", "default": "22:00"},
    {"key": "minutes", "label": "锁机时长（分钟）", "type": "int", "default": 30},
]
ACTIONS = [{"label": "🔒  立即锁一次", "fn": "lock_now"}]
_TASK = "LockDevice_Plugin_autolock"

def on_settings_saved(api, values):
    if not values.get("enabled"):
        api.delete_task(_TASK); return
    hh, mm = map(int, str(values.get("time", "22:00")).split(":"))
    minutes = max(1, int(values.get("minutes", 30)))
    ok, msg = api.register_task(_TASK, api.daily_trigger(hh, mm),
                                api.lock_command(minutes), desc="每日自动锁机")
    api.info("已设定。") if ok else api.error("失败：\n" + (msg or ""))

def on_uninstall(api):
    api.delete_task(_TASK)

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
