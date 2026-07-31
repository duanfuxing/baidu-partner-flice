# Windows 安装器架构兼容修复计划

## 目标

修复 `v0.30.4` x64 安装程序在标准 Intel x64 Windows 11 24H2 上错误提示“不支持当前 Windows 版本”的问题。

## 问题确认

- 用户系统：Windows 11 企业版 24H2，64 位操作系统，Intel x64 处理器。
- 用户文件：`BaiduPartnerFlice-0.30.4-Windows-x64-Setup.exe`。
- Actions 中 Windows x64 和 ARM64 构建均成功，但 x64 安装器运行时架构校验错误。

## 范围

- x64 安装器使用 Inno Setup 官方推荐的 `x64compatible`。
- x64 和 ARM64 使用两个明确的安装脚本入口。
- 移除通过 Actions 命令行数值宏切换架构的逻辑。
- 原生 ARM64 安装器继续严格限制为 ARM64。
- 版本统一升级到 `0.30.5`。
- 增加安装脚本入口及架构回归测试。

## 设计

- `windows-installer-x64.iss` 明确定义 `x64compatible`。
- `windows-installer-arm64.iss` 明确定义 `arm64`。
- 两个入口共同包含 `windows-installer.iss`，复用安装文件、快捷方式和卸载配置。
- Actions 矩阵直接指定入口脚本，不再传递 `MyAppIsArm64=0/1`。

## 验收标准

- [x] x64 安装入口明确使用 `x64compatible`。
- [x] ARM64 安装入口明确使用 `arm64`。
- [x] Actions 不再通过数值宏选择安装器架构。
- [x] 两个 Windows 安装包名称和原生 PyInstaller 构建保持区分。
- [x] 所有当前版本号均为 `0.30.5`。
- [x] 定向测试和完整测试通过。
- [x] 桌面入口自检通过。
- [x] `git diff --check` 通过。

## 环境限制

- 当前本机无法直接运行 Windows 安装程序；最终安装验收需在 Windows x64 和 ARM64 真机完成。

## 验证记录

- `pytest tests/test_installers.py tests/test_packaging_assets.py`：9 项通过。
- `pytest`：84 项通过。
- `python desktop_main.py --self-check`：退出码 0。
- GitHub Actions YAML 解析通过。
- `git diff --check`：通过。
- Windows x64 安装向导启动：等待 CI 生成 `0.30.5` 后真机验收。
