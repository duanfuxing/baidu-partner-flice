# 跨平台安装程序与 Windows ARM64 计划

## 目标

将便携 ZIP 发布改为系统安装程序，增加 Windows ARM64 原生构建，并明确隔离程序文件与用户登录信息、日志和缓存数据。

## 范围

- Windows x64 使用 Inno Setup 生成独立安装程序。
- Windows ARM64 使用原生 GitHub Actions runner、ARM64 Python 和 PyInstaller 生成独立安装程序。
- macOS Apple Silicon 和 Intel 使用 `pkgbuild` 生成 `.pkg` 安装包。
- Windows 程序目录安装到系统 Program Files，`_internal` 只存在于安装目录内。
- 创建开始菜单快捷方式，并提供可选桌面快捷方式和卸载程序。
- 登录状态、日志、截图和缓存统一放在当前用户应用数据目录。
- Windows UI 使用 `Microsoft YaHei UI`，日志等宽字体使用 `Consolas`。
- 版本统一升级到 `0.30.4`。

## 设计

### 发布产物

- `BaiduPartnerFlice-0.30.4-Windows-x64-Setup.exe`
- `BaiduPartnerFlice-0.30.4-Windows-arm64-Setup.exe`
- `BaiduPartnerFlice-0.30.4-macOS-arm64-Installer.pkg`
- `BaiduPartnerFlice-0.30.4-macOS-x64-Installer.pkg`

### 安装目录

- Windows：`{autopf}\BaiduPartnerFlice`，通常为 `C:\Program Files\BaiduPartnerFlice`。
- macOS：`/Applications/百度资质自动提交工具.app`。
- PyInstaller 的 `_internal` 随主程序复制到 Windows 安装目录，不暴露为下载包根目录中的用户操作项。

### 用户数据目录

- Windows：`%LOCALAPPDATA%\BaiduPartnerFlice`
- macOS：`~/Library/Application Support/BaiduPartnerFlice`
- 子目录：
  - `auth/`：登录状态；
  - `logs/`：运行日志；
  - `screenshots/`：必要的错误截图；
  - `cache/`：应用缓存。
- 安装、升级和普通卸载均不删除用户数据，避免丢失登录状态和审计日志。

### 构建架构

- Windows x64：`windows-2022` + x64 Python。
- Windows ARM64：`windows-11-arm` + ARM64 Python。
- macOS arm64：`macos-15`。
- macOS x64：`macos-15-intel`。
- 每个平台在生成安装包前执行冻结应用 `--self-check`。

## 实现步骤

1. 建立任务文档。
2. 新增 Inno Setup 安装脚本。
3. 将 Actions 扩展为四架构矩阵并输出安装程序。
4. 新增 macOS `.pkg` 构建。
5. 增加用户数据子目录初始化。
6. 配置 Windows 系统字体。
7. 将版本统一升级到 `0.30.4`。
8. 更新 README 和自动化测试。
9. 运行定向测试、完整测试、自检和本机 macOS 最小安装包验证。
10. 提交并推送 `master` 和 `v0.30.4` 标签，触发四平台安装包构建。

## 依赖

- Windows runner 使用预装的 Inno Setup。
- macOS runner 使用系统自带的 `pkgbuild`。
- 不新增 Python 依赖。

## 验收标准

- [ ] Windows x64 和 ARM64 均输出 `.exe` 安装程序。
- [ ] macOS arm64 和 x64 均输出 `.pkg` 安装包。
- [x] Windows 安装脚本将整个 PyInstaller 目录安装到 Program Files。
- [x] Windows 提供开始菜单、可选桌面快捷方式和卸载入口。
- [x] Windows 两个安装程序限制到对应 CPU 架构。
- [x] 用户数据目录包含 `auth`、`logs`、`screenshots` 和 `cache`。
- [x] 卸载脚本不删除用户数据。
- [x] Windows UI 字体为 `Microsoft YaHei UI`，日志字体为 `Consolas`。
- [x] 所有当前版本号均为 `0.30.4`。
- [x] 相关自动化测试和完整测试通过。
- [x] 桌面入口自检通过。
- [x] `git diff --check` 通过。
- [x] 已提交并推送 `master` 和 `v0.30.4` 标签。

## 不在范围内

- Windows Authenticode 签名。
- Apple Developer ID 签名、公证。
- 静默删除用户登录信息和日志。

## 环境限制

- 本机只能实际构建和检查当前 macOS 架构；Windows x64、Windows ARM64 和另一 macOS 架构由 GitHub Actions 原生 runner 验证。

## 验证记录

- 安装配置、版本、用户数据和字体定向测试：16 项通过。
- 完整自动化测试：84 项通过。
- 源码与冻结应用 `--self-check`：通过。
- macOS x64 PyInstaller 构建：通过。
- macOS x64 `.pkg` 实际生成：通过；包载荷根目录为“百度资质自动提交工具.app”，安装位置为 `/Applications`。
- macOS App 显示名和版本 `0.30.4`：通过。
- Actions YAML 语法解析：通过。
- `git diff --check`：通过。
- 修复已提交并通过 `v0.30.4` 标签触发远端构建。
- Windows x64、Windows ARM64 和 macOS arm64 的实际安装包构建需由 GitHub Actions 原生 runner 验证。
