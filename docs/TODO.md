# LockDevice TODO（滚动维护）

> 最后更新：2026-10-19 深夜。规则：进行中的条目写清「状态 / 验收标准」；做完的挪进「已完成」。

## 进行中

### 1) 1.6.5：打开到前台 + 启动提速（**已推送 `6ba5a29`，CI 构建中**）
- [x] **窗口开在后台（要点任务栏才出来）**：免 UAC 链路是「计划任务 → 提权实例」，
      Task Scheduler 启动的进程没有前台激活权限。修法：中转实例触发任务前
      `_allow_child_foreground()`（AllowSetForegroundWindow ASFW_ANY 授权）；
      Qt 主窗 `_force_foreground_win()`（附加输入队列技巧 + 600/1400ms 延迟补枪，
      已在前台自动跳过）；tk `run()` 补 `_bring_to_front()`。实机验证通过
      （后台进程弹窗 `foreground == test window: True`）。
- [x] **每次打开约 3 秒**：安装时把 onefile 解压产物释放到 app\\ 后没把主程序改回规范名
      （app\\LockDevice-1.6.4-qt-plugins.exe），`installed_main()` 对不上号就一路回退
      onefile（每次启动过一次解压缓存检查，单次约 1 秒；链路要走两段进程 → 约 2 秒白耗）。
      修法：安装/更新时 `_rename_app_main()` 改名规范名 + `installed_main()` 兼容探测。
      实测：固化版 `--list-plugins` 0.13-0.16 秒 vs onefile 1.0 秒。
- [x] 测试：单测 `test_launch_165.py` 8/8；真机前台验证；回归 bridge 4/4、icons 16/16、
      ui2 qt 8/8、ui2 tk 7/7。
- [ ] CI 构建 1.6.5 → 用户经「发现更新」窗更新 → 复测：error.log 启动链路时间戳间隔、
      前台体验、快捷方式/任务指向 `app\\LockDevice.exe`。

### 2) 本机状态（2026-10-19 深夜）
- [x] 应用已更新到 **1.6.4**；`auto_lock_multi v1.0.2` 已装入本机
      （`C:\\Program Files\\LockDevice\\plugins\\`，哈希 `1E24324C…`）——
      含旧宿主回退修复（幽灵路径）+ UI 2.0（items/status/图标/迁移兜底）。
- [x] `LockDevice_MultiLock_*` 任务已重指到规范入口（不再指向幽灵路径）。
- [ ] 更新 1.6.5 后：MultiLock 任务随「保存」/登录自愈到 `app\\LockDevice.exe`
      （tick 也走零解压固化版，到点触发更快），并复验 13:26-14:00 时段行为。

## 已完成（近期）

- 1.6.4 发布（`bd9f74e` 推送，CI run 39204313267 成功，四变体齐全）；用户已更新。
- 插件 UI 2.0（time / int+范围 / status / items）+ 图标四形态（emoji/base64/file/fluent）+
  文件夹插件格式（`plugins/<目录>/plugin.py`）；`auto_lock_multi v1.0.2`：
  旧文本时段自动迁移（on_boot / 保存 / 编辑 / 首渲染兜底 / CLI），双端安全。
- 1.6.0~1.6.3：PyInstaller → Nuitka 迁移；Qt 数值框显示修复（锁 PySide6<6.12）；CI 自动构建 4 变体。
- 插件操作线程化与退出收尾机制、插件任务幽灵路径修复（随 1.6.4，commit `2285824`）。
