# 测试用例

## Windows 安装程序

1. x64 runner 使用 x64 Python，产物名以 `Windows-x64-Setup.exe` 结尾。
2. ARM64 runner 使用 ARM64 Python，产物名以 `Windows-arm64-Setup.exe` 结尾。
3. 安装脚本递归复制 `dist/BaiduPartnerFlice`，包含 EXE 和 `_internal`。
4. x64 安装程序只允许 x64 Windows，ARM64 安装程序只允许 ARM64 Windows。
5. 默认安装到 Program Files 下的 `BaiduPartnerFlice`。
6. 创建开始菜单快捷方式，桌面快捷方式为可选项。
7. 卸载配置不删除 `%LOCALAPPDATA%\BaiduPartnerFlice`。

## macOS 安装包

1. Apple Silicon runner 输出 arm64 `.pkg`。
2. Intel runner 输出 x64 `.pkg`。
3. 两个安装包均将中文名称的 `.app` 安装到 `/Applications`。
4. `.pkg` 版本与应用版本一致。

## 用户数据

1. Windows 根目录为 `%LOCALAPPDATA%\BaiduPartnerFlice`。
2. macOS 根目录为 `~/Library/Application Support/BaiduPartnerFlice`。
3. 首次启动创建 `auth`、`logs`、`screenshots` 和 `cache`。
4. 登录状态路径为 `auth/storage_state.json`。
5. 运行日志写入 `logs`。

## 字体

1. Windows 默认 UI 字体为 `Microsoft YaHei UI`。
2. Windows 日志等宽字体为 `Consolas`。
3. 非 Windows 平台不强制使用 Microsoft 字体。

## 回归

1. Python、Windows、macOS 和 Actions 版本均为 `0.30.4`。
2. 打包配置定向测试通过。
3. 用户数据和字体定向测试通过。
4. 完整 `pytest` 通过。
5. 桌面入口 `--self-check` 通过。
6. `git diff --check` 通过。

## 验证结果

- 安装配置、版本、用户数据和字体定向测试：16 项通过。
- 完整自动化测试：84 项通过。
- 源码与冻结应用 `--self-check`：通过。
- macOS x64 PyInstaller 和 `.pkg` 实际构建：通过。
- `.pkg` 载荷及 `/Applications` 安装位置检查：通过。
- Actions YAML 语法解析：通过。
- `git diff --check`：通过。
- Windows x64、Windows ARM64 和 macOS arm64 待 GitHub Actions 原生 runner 验证。
