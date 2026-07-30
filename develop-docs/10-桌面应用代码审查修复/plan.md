# 桌面应用代码审查修复计划

## 目标

修复版本 `0.30.0` 桌面化代码审查发现的跨平台安全性、登录验证、运行结果、日志性能和任务取消问题。

## 范围

- Windows 使用无损 API 检查 PID 存活状态，禁止通过 `os.kill(pid, 0)` 探测。
- 人工确认登录后必须重新通过 URL 和页面特征验证，验证失败不得保存 storage state。
- `busy` 公司属于未处理结果，GUI 不得提示全部成功，CLI 不得返回成功退出码。
- 桌面日志按文件偏移量增量读取，不得每 100ms 读取完整日志。
- 增加安全取消：登录等待可立即取消；公司处理中只请求取消，等待当前公司稳定结束后停止后续公司。
- 为未开始的已预留公司写入明确的取消状态。
- 增加无需真实接口的桌面包 `--self-check`，并在 GitHub Actions 构建后运行。
- 补充单元测试和任务文档。

## 设计

### Windows PID 检测

Windows 使用 `OpenProcess(SYNCHRONIZE)` 和 `WaitForSingleObject(handle, 0)` 查询进程状态，并始终关闭句柄。无法打开但权限被拒绝时按“存活”处理，进程不存在时按“不存活”处理。

### 登录验证

人工点击确认后，在有限时间内重复扫描浏览器上下文页面。只有 `_looks_logged_in` 成功才保存状态；否则抛出 `AuthenticationRequired`，由桌面窗口展示。

### 取消语义

- 登录等待：取消事件立即解除等待并关闭登录 Chrome。
- 公司执行中：不强杀 worker/Chrome；当前公司完成后停止。
- 尚未开始的公司：调度状态写为 `failed`，`errorCode` 为 `task-cancelled`。
- 取消作为独立桌面结果展示，不混同普通业务失败。

### 自检

冻结程序支持 `--self-check`，检查版本、Tkinter、Playwright、portalocker 和 spawn 子进程，不打开真实 Chrome、不访问网络。

## 验收标准

- [x] Windows PID 检测不会发送终止信号。
- [x] 人工确认但仍处于登录页时返回明确错误且不保存认证状态。
- [x] `busy` 非空时 GUI 和 CLI 均不报告成功。
- [x] 日志轮询只读取新增字节。
- [x] 登录等待可以取消。
- [x] 当前公司处理中请求取消不会强制中断当前提交。
- [x] 未开始公司保存取消状态。
- [x] GitHub Actions 构建后执行冻结程序自检。
- [x] 完整自动化测试通过（66 项）。

## 验证记录

- 源码 `desktop_main.py --self-check` 通过。
- macOS x64 PyInstaller `.app` 构建通过。
- 冻结 `.app --self-check` 通过，包含 spawn 子进程。
- 修复后的 GUI 实际启动冒烟检查通过。
- Windows 与 macOS arm64 的平台构建和自检由 GitHub Actions 首次运行验证。

## 不在范围内

- 强制中断正在提交的单个公司。
- Windows 或 Apple 代码签名。
- 修改真实资质提交业务规则。
