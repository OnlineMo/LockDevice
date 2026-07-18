# PySide6 + qfluentwidgets 界面迁移计划

> 界面从 tkinter/customtkinter 迁移到 **PySide6 + qfluentwidgets**（Fluent Design，风格对齐 `example/`）。
> 后端（`lock_device.py`：计划任务 / 配置 / 插件 / 键盘钩子 / 看门狗）**不变**，只重写前端。

## 关键优势：插件零改动
插件是**声明式前端**（`SETTINGS`/`ACTIONS` 纯数据）+ 后端函数。迁移只改「本体的渲染器」——
tkinter 版 `_render_setting_field` → Qt 版 `SettingsInterface._field`。**插件不用动一行**。

## 架构
- 新前端在 `gui_qt/`，通过 `import lock_device as core` 复用后端（源码态直接可用）。
- 锁机先**复用现有 CLI** 解耦：`gui_qt` 收集设置 → 落 config → 拉起 `--startlock <秒>` / `--open`。
  待 Qt 锁屏就绪后再改为 Qt 原生。
- 入口：`python run_qt.py`。

## 已完成（本次起步，dev 分支）
- 工具链：`PySide6` + `PySide6-Fluent-Widgets`（qfluentwidgets 1.11.2），已验证构建。
- `FluentWindow` 主窗 + 导航：**专注锁定（Home）/ 设置 / 关于**。
- Home：锁定方式（①/②）+ 时长 + 两个开关 + 「开始锁定」（mode1 拉 `--startlock`，mode2 走 `--open`）。
- 设置：**按各插件声明的 `SETTINGS` 渲染** Fluent 控件（SwitchButton/ComboBox/LineEdit）+ 保存 → 回调 `on_settings_saved`。
- 无头构造验证通过（`gui_qt.app.MainWindow()` 成功，auto_lock 三项被渲染）。

## 待办（完整迁移）
1. **Home 精修**：改用 `SettingCard`/`SettingCardGroup` 更 Fluent；补模式一（防杀/禁TM）与模式二（登录前/立即）开关联动置灰；自定义快捷。
2. **Qt 锁屏**（核心）：无边框全屏黑幕 + 时钟/大倒计时 + 息屏/关机；复用 `KeyBlocker`（ctypes，工具箱无关）与看门狗；替换 tkinter `_show_lock_screen`。
3. **插件单页**：按 `SETTINGS + ACTIONS` 渲染（对应 tkinter 的 `_show_plugin`），接 ACTIONS 按钮。
4. **对话框**：更新窗 / 安装选项 / 添加快捷 / 高风险确认 → qfluentwidgets `MessageBox`/`Dialog`/`Flyout`。
5. **启动器与分流**：安装/绿色/卸载/清除 + 已安装免 UAC 分流（`schtasks /run TASK_OPEN`）搬到 Qt 入口。
6. **后端解耦**：把 `App.start_mode1_lock` 里的「锁定逻辑」与「tkinter 锁屏」拆开，Qt 直接调后端（或维持 CLI 桥）。
7. **系统托盘**：`example/gui/component/sys_tray.py` 风格，可选。
8. **打包切换**：`build.py` 入口改 `run_qt.py`；`--collect-all PySide6 qfluentwidgets`（含 Qt plugins）；`requirements.txt` 并入 `requirements-qt.txt`、移除 `customtkinter`。全部就绪后合并回 main 发新版。

## 参考
- 样例风格：`example/gui/`（qfluentwidgets：navigation/pivot/flyout/info_bar/setting card 等）。
- 依赖：见 `requirements-qt.txt`。
