# 桌面应用与跨平台打包计划

## 目标

将现有命令行自动化工具改造成业务人员可直接使用的桌面应用，并通过 GitHub Actions 构建 Windows 与 macOS 软件包。当前版本为 `0.30.0`。

## 范围

- 使用 Tkinter 提供桌面窗口。
- 每次启动不预设输入目录，必须由用户主动选择。
- 选择目录后先完成全部输入校验并展示公司、资质类型、资质数量和文件数量。
- 输入错误、登录提示、流程错误和最终结果均在窗口中展示。
- 登录完成确认由窗口按钮完成，不依赖控制台输入。
- 公司提交固定为单 worker 串行执行。
- 每次正式运行创建独立日志文件；窗口支持查看本次日志和历史日志。
- 调度文件锁兼容 Windows 与 macOS。
- 使用 PyInstaller 构建 Windows 和 macOS 桌面包。
- GitHub Actions 在推送、手工触发和 `v*` 标签时构建；标签构建同时创建 GitHub Release。
- 清理 `.gitignore`，排除输入、认证、日志、截图、IDE 和构建产物。

## 设计

### 桌面交互

桌面入口与命令行入口分离，共用输入解析、浏览器和业务流程。耗时操作在后台线程执行，通过线程安全事件队列将日志、校验结果、登录确认和运行结果送回 Tk 主线程。

### 数据目录

- 输入目录：每次运行由用户选择，不持久化为默认值。
- 登录状态、运行日志：保存到当前用户的应用数据目录。
- 调度状态、公司执行状态和结果：继续保存在用户选择的输入目录中。

### 日志

每次任务生成带时间和随机标识的 UTF-8 日志文件。主进程和唯一 worker 写入同一个任务日志。日志不得记录 Cookie、Token、完整请求头或密码。

### 打包

- Windows：PyInstaller windowed onedir，压缩为 zip。
- macOS：PyInstaller windowed `.app`，分别构建 Apple Silicon 与 Intel zip。
- 使用本机已安装的 Google Chrome，不捆绑浏览器二进制。
- 首版产物不签名；macOS Gatekeeper 和 Windows SmartScreen 提示作为发布限制记录。

## 实现步骤

1. 更新版本、依赖、忽略规则和任务文档。
2. 将 `fcntl` 替换为跨平台文件锁，并把 worker 上限固定为 1。
3. 抽取可复用的校验和运行服务，支持登录回调及任务日志。
4. 实现桌面窗口、校验摘要、登录确认、错误展示和日志历史。
5. 增加冻结应用入口与 PyInstaller spec。
6. 增加 Windows/macOS GitHub Actions 构建和标签发布。
7. 更新并执行单元测试、静态编译检查和本地打包冒烟检查。

## 依赖

- Python 3.11
- Playwright
- portalocker
- PyInstaller（仅构建）
- pytest（仅开发和 CI）

## 验收标准

- [x] 桌面程序启动时输入目录为空，必须选择后才能校验和运行。
- [x] 合法输入以结构化列表展示，错误输入完整展示错误列表。
- [x] 未校验或校验失败时不能开始运行。
- [x] 登录确认和运行错误不依赖控制台。
- [x] 任意公司数量都只启动一个 worker。
- [x] Windows 与 macOS 均可导入调度模块并使用文件锁。
- [x] 每次运行有独立日志，桌面窗口可查看历史日志。
- [x] 版本在应用、包元数据和构建产物中统一为 `0.30.0`。
- [x] GitHub Actions 已配置生成 Windows、macOS arm64 和 macOS Intel 软件包。
- [x] 自动化测试通过（56 项）。

## 不在范围内

- Windows 代码签名。
- Apple Developer ID 签名与公证。
- 自动更新。
- 将 Google Chrome 或 Playwright Chromium 捆绑进安装包。
- 修改真实资质提交业务规则。

## 环境限制

- 当前开发环境为 macOS x64；源码测试、macOS x64 打包和 `.app` 启动冒烟检查已通过。Windows 与 macOS arm64 产物需由 GitHub Actions 首次运行验证。
- 未签名产物在 Windows SmartScreen 或 macOS Gatekeeper 下可能需要用户人工允许首次启动。
