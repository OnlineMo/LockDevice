# LockDevice TODO（滚动维护）

> 最后更新：2026-10-19 下午。规则：进行中的条目写清「状态 / 验收标准」；做完的挪进「已完成」。

## 进行中

### 1) 1.6.4（第一个提交已完成；**推送 & CI 构建待确认**）
- [x] **更新后插件后台停摆**：宿主 `api.self_path()`/`api.action_for()`、`do_install` 刷新
      `TASK_PLUGIN_BOOT`、`_plugins_dirs()` 纳入安装根目录扫描（commit `2285824`）。
- [x] **插件开关卡 5-6 秒**：回调后台线程 + `plugin_op_lock` 串行 + 开关防连点 + 关窗收尾。
- [x] 插件补丁 `auto_lock_multi v1.0.1` **已装入本机**（2026-10-19，`C:\Program Files\LockDevice\plugins\`，
      哈希一致 `58E3953D…`）。
      ⚠ 旧的 `LockDevice_MultiLock_*` 任务仍指向幽灵路径——**在插件里点一次「保存」**
      （或下次登录 `on_boot` 自愈）即重建到规范入口。
- [ ] 推送 + CI 构建 1.6.4（**等用户确认**；README 路线图改动不进这次提交）。

### 2) 插件 UI 2.0 + 插件图标（✅ 已实现并验证，随第二个提交落地）
- [x] `SETTINGS`/`prompt`：`time` / `int+min/max/step` / `status` / `items` 双端渲染
- [x] `api.prompt()` / `api.refresh()` / 动作签名 `fn(api, values)`
- [x] **插件图标**（A/B/C 对比后全量支持）：emoji / base64 / file / fluent 四形态
      （Qt 侧栏+管理页；tk 按钮+管理页文字前缀）+ **文件夹插件**格式（`plugins/<目录>/plugin.py`，build.py 打包）
- [x] `auto_lock` 换 `time` 字段 + `"icon": "⏰"`（活例子）；`docs/PLUGINS.md` 同步；`docs/PLUGIN_UI_2.md` 验收记录
- [ ] 构建一个变体做真机实测（可选，随 1.6.4 CI 一起）

## 已完成（近期）

- 1.6.0~1.6.3：PyInstaller → Nuitka 迁移；Qt 数值框显示修复（锁 PySide6<6.12）；CI 自动构建 4 变体。
- 插件操作线程化与退出收尾机制、插件任务幽灵路径修复（随 1.6.4，commit `2285824`）。
- 插件图标系统与文件夹插件支持（emoji/base64/file/fluent + `plugins/<目录>/plugin.py`）。
