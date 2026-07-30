# 问题记录

| 编号 | 问题 | 复现条件 | 状态 | 解决方案 |
| --- | --- | --- | --- | --- |
| 09-001 | `fcntl` 无法在 Windows 导入 | Windows 启动调度模块 | 已解决 | 使用 portalocker 跨平台文件锁替换 |
| 09-002 | 无控制台桌面程序无法使用 `input()` 确认登录 | PyInstaller windowed 启动 | 已解决 | 使用线程事件和窗口按钮确认 |
| 09-003 | 冻结应用多进程可能递归启动窗口 | PyInstaller + spawn worker | 已解决 | 桌面入口尽早调用 `multiprocessing.freeze_support()` |
| 09-004 | 沙箱环境无法启动本机 Chrome 测试 | 沙箱内执行 Playwright 页面测试 | 环境限制 | 获得本机 Chrome 启动权限后完整测试通过 |
