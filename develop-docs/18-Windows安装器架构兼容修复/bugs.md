# 问题记录

## BUG-001：x64 安装器错误拒绝 Intel x64 Windows 11

- 状态：已修复，待 Windows x64 真机验收
- 版本：`0.30.4`
- 复现环境：Windows 11 企业版 24H2（OS Build 26100.7462），Intel x64 处理器。
- 现象：运行 `BaiduPartnerFlice-0.30.4-Windows-x64-Setup.exe` 时提示当前 Windows 版本不受支持。

### 构建日志证据

- Actions runner 为 `windows-2022`，Python 架构为 `x64`。
- Python 安装包为 `python-3.11.8-win32-x64.zip`。
- PyInstaller 使用 `Windows-64bit-intel\runw.exe`，构建后 `--self-check` 成功。
- Inno Setup 收到 `/DMyAppIsArm64=0`，随后成功生成安装程序。

上述证据确认应用载荷为 x64，问题范围收敛到 Inno Setup 安装器架构门禁。

### 解决方案

- x64 安装入口改用 Inno Setup 推荐的 `x64compatible`。
- x64 与 ARM64 分别使用显式入口脚本，移除命令行数值宏分支。
- 增加静态回归测试，并在 Windows x64 真机验证安装向导。
