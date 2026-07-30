# 测试用例

## UI 品牌

1. 开发环境资源路径指向存在的 `assets/app-icon.png`。
2. 模拟 PyInstaller `_MEIPASS` 时资源路径指向冻结资源目录。
3. `DesktopApplication` 保留 `CTkImage` 引用，避免 Tk 图片被垃圾回收。
4. 侧边栏源码不包含“单 worker · 串行提交”。

## 打包资源与命名

1. PyInstaller spec 将 `assets/app-icon.png` 打入 `assets` 目录。
2. Windows 内部 EXE 保持 `BaiduPartnerFlice.exe`。
3. Windows x64、macOS arm64、macOS x64 的 Artifact 和 ZIP 名称包含中文软件名及 `0.30.2`。
4. Release 下载规则能匹配中文 Artifact。

## 版本一致性

1. Python 包版本为 `0.30.2`。
2. Windows 文件版本为 `0.30.2`。
3. macOS Bundle 版本为 `0.30.2`。
4. Actions 产物版本为 `0.30.2`。

## 回归与发布

1. 完整 `pytest` 通过。
2. 桌面入口 `--self-check` 通过。
3. `git diff --check` 通过。
4. 推送 `v0.30.2` 后 tag 工作流开始运行。

## 验证结果

- UI、资源路径、打包和版本定向测试：9 项通过。
- 完整自动化测试：78 项通过。
- 源码与冻结应用 `--self-check`：通过。
- 源码 GUI 与冻结应用实际启动：通过。
- macOS x64 PyInstaller 构建：通过。
- 冻结包内正式 PNG 路径检查：通过。
- macOS Info.plist 中文显示名、0.30.2 版本和英文内部可执行文件检查：通过。
- `git diff --check`：通过。
