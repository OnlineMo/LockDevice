# 插件 UI 2.0 · 控件 / 动态能力 / 图标（✅ 已实现 · 2026-10-19）

> 状态：**第一~四节全部实现并通过双端测试**（Qt 8+12 项 / tk 7+3 项，见文末）。
> 权威用法（给插件作者）以 [`PLUGINS.md`](PLUGINS.md) 为准；本文保留设计定档记录。

## 一、新控件（✅ 已实现；`SETTINGS` 与 `api.prompt` 共用同一套字段 schema）

| 类型 | Qt 渲染 | tk 渲染 | 存储 |
|---|---|---|---|
| `time` | qfluentwidgets `TimeEdit` | 时/分两个下拉 | `"HH:MM"` 字符串 |
| `int` + `min`/`max`/`step` | `SpinBox` | `tk.Spinbox` | int |
| `status` | 调 `fn(api)` 显示返回文本（只读，可无 `key`） | 同左 | 不存储 |
| `items` | 卡片列表（对标自定义快捷） | 同左 | `list[dict]` |

`items` 声明（已实现）：

```python
{"key": "items", "type": "items", "label": "我的条目",
 "display": "{name} · {time}",            # 每项显示模板（占位符取 dict 字段）
 "click":  "run_item",                    # 点卡片 → mod.run_item(api, index)（可选）
 "add":    "add_item", "add_label": "＋ 添加",  # 底部按钮 → mod.add_item(api)（可选）
 "remove": "remove_item"}                 # 每项删除钮 → mod.remove_item(api, index)（可选）
```

## 二、api 新能力（✅ 已实现）

- `api.prompt(title, fields) -> dict | None`：本体渲染的通用表单弹窗（字段=上表 schema）。
- `api.refresh()`：重渲染当前显示的插件页（插件改完数据后调用）。
- 动作函数可选收表单值：`def fn(api, values)`（签名探测，老的 `fn(api)` 不受影响）。

**原则不变**：本体只渲染 + 回调；增删改全归插件（prompt 收集 → `save_settings` 写回 → `refresh` 刷新）。

## 三、图标（✅ 已实现 · A/B/C 三方案对比后全量支持）

现状问题：Qt 侧栏所有插件入口都写死 `FIF.APPLICATION`（用户实测「分不清哪个插件」）。

### A/B/C 三方案对比

| 方案 | 内容 | 单文件插件 | 双端一致 | 成本 | 结论 |
|---|---|---|---|---|---|
| **A** emoji + base64 内嵌图片 | `"icon": "⏰"` 或 `{"base64": "…"}` | ✅ | ✅ | 低 | **采用**：零依赖、一个 .py 走天下 |
| **B** A + 文件夹插件 | 另支持 `plugins/<目录>/plugin.py` + `icon.png` 等资源 | 兼容（单文件永久保留） | ✅ | 中（loader/打包小升级） | **采用**：资源能力全面（图标/图片/大附件） |
| **C** B + FluentIcon 名 | `{"fluent": "Camera"}` Qt 原生风格图标 | ✅ | ❌（tk 无 FluentIcon） | 低 | **采用但降级**：Qt 完美；tk 端回退为无图标（可选补 emoji） |

外部路径图标（`{"path": "D:\..."}`）**不做**：移植性差 + 安全隐患。

### 实现（`PLUGIN["icon"]` 单字段自动识别形态）

```python
"icon": "⏰"                            # A：emoji（Qt 画成图标 / tk 文字前缀）
"icon": {"base64": "<PNG/GIF b64>"}     # A：内嵌图片（双端一致；支持 dataURL 前缀）
"icon": {"file": "icon.png"}            # B：相对插件目录（文件夹插件放资源）
"icon": {"fluent": "Camera"}            # C：Qt FluentIcon 名（tk 回退）
```

- 核心解析 `plugin_icon_source()`（本体，双端共用）→ `(kind, value)`；失败只记日志、不影响加载。
- Qt：`_plugin_icon_qt()` → emoji 绘到 64px 透明 pixmap（深色主题浅灰笔；Qt 对 emoji 单色渲染）/
  base64、file → QPixmap→QIcon / fluent → FluentIcon 成员；接入 **侧栏入口 + 插件管理卡片**。
- tk：`_tk_plugin_photo()`（PNG/GIF 原生，自动 subsample）接入**启动器按钮 + 管理页行**；
  emoji 走 `plugin_display_name()` 文字前缀（如「⏰ 自动锁机」，已有则不重复加）。
- 文件夹插件：loader 增扫 `plugins/<目录>/plugin.py`；`build.py` 逐目录 `include-data-dir` 原样打包。

## 四、落地清单（✅ 完成）

1. ✅ 双端 `_field` 渲染器加 `time` / `int+范围` / `status` / `items`；`api.prompt` / `api.refresh` / 动作签名探测。
2. ✅ `items` 控件双端渲染 + 回调路由（`_plugin_items_cb`）。
3. ✅ `auto_lock` 的「时间」换 `time` 类型、「时长」加 `min/max/step`（活例子）；`"icon": "⏰"`。
4. ✅ `PLUGINS.md` 同步（字段表 / api 表 / 图标表 / 文件夹插件格式 / 任务动作规范）。
5. ✅ 图标：`PLUGIN["icon"]` 四形态（emoji / base64 / file / fluent）+ 文件夹插件 loader/打包。

## 五、验收记录（2026-10-19，离屏/隐藏窗口自动化）

- **Qt（8/8 PASS）**：字段渲染（TimeEdit/SpinBox 实际出现）、`_current_values`、动作 `fn(api, values)` 与旧签名、
  items 三种回调、`refresh` 重建、`prompt` 确定（正确返回 dict）/ 取消（None）。
- **tk（7/7 PASS）**：同套用例 + `prompt` 确定（真实点「确定」按钮后返回 dict）/ 取消。
- **图标核心 + 文件夹插件（16/16 PASS）**：四形态解析与容错、显示名前缀去重、
  文件夹插件加载/图标解析/清理、tk PhotoImage（file/base64）。
- **图标 Qt（12/12 PASS）**：emoji→QIcon（实测绘制出内容）、base64/file→QIcon、fluent 名解析（大小写）、
  失败容错、缓存、`add_plugin_nav` 侧栏接入（含真实 auto_lock）、管理页构造。
- **图标 tk UI（3/3 PASS）**：`CTkButton` / `CTkLabel` 带 `tk.PhotoImage`、启动器按钮结构。
- 其余检查：`py_compile` 全过；`api.refresh/prompt` 在无界面上下文（CLI）下为安全空操作。
