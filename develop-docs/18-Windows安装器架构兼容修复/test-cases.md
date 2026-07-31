# 测试用例

## x64 安装器

1. x64 入口定义 `MyArchitecturesAllowed` 为 `x64compatible`。
2. x64 Actions job 只编译 x64 入口。
3. x64 安装包名称以 `Windows-x64-Setup.exe` 结尾。
4. Intel x64 Windows 11 24H2 能启动安装向导。

## ARM64 安装器

1. ARM64 入口定义 `MyArchitecturesAllowed` 为 `arm64`。
2. ARM64 Actions job 只编译 ARM64 入口。
3. ARM64 安装包名称以 `Windows-arm64-Setup.exe` 结尾。

## 回归

1. 公共安装配置仍递归安装完整 PyInstaller onedir。
2. 登录状态、日志、截图和缓存不进入安装目录。
3. Python、Windows、macOS、安装脚本和 Actions 版本均为 `0.30.5`。
4. 定向测试和完整测试通过。
5. 桌面入口自检通过。
6. `git diff --check` 通过。

## 验证结果

- 安装器入口、Actions 路由、版本一致性和用户数据隔离测试：通过。
- 完整自动化测试：84 项通过。
- 桌面入口自检：通过。
- Windows x64 24H2 真机安装：等待 CI 产物。
