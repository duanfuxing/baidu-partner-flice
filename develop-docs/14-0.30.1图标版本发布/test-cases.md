# 测试用例

## 版本一致性

1. `src.__version__` 为 `0.30.1`。
2. `pyproject.toml` 项目版本为 `0.30.1`。
3. Windows `filevers`、`prodvers`、`FileVersion` 和 `ProductVersion` 为 `0.30.1`。
4. macOS Bundle 的短版本、构建版本和 PyInstaller BUNDLE 版本为 `0.30.1`。
5. GitHub Actions 三个平台产物名称包含 `0.30.1`。

## 图标资源

1. 正式 PNG 为 RGBA 且尺寸不小于 1024×1024。
2. ICO 包含 Windows 常用尺寸。
3. ICNS 文件头和长度有效。
4. PyInstaller spec 按平台引用正确的图标资源。

## 回归

1. 完整 `pytest` 通过。
2. `git diff --check` 通过。
3. tag 推送后 GitHub Actions 同时创建 Windows x64、macOS arm64 和 macOS x64 构建。
4. tag 工作流构建成功后创建 GitHub Release 并附加三个 ZIP 软件包。

## 验证结果

- 版本与图标资源定向测试：5 项通过。
- 完整自动化测试：75 项通过。
- 桌面入口 `--self-check`：通过。
- 当前运行时与打包配置未发现残留 `0.30.0`。
- `git diff --check`：通过。
