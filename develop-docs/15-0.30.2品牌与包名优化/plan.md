# 0.30.2 品牌与包名优化计划

## 目标

优化桌面软件的品牌呈现和发布包命名，将版本升级到 `0.30.2`，并通过 `v0.30.2` 标签触发 Windows 与 macOS 打包发布。

## 范围

- 左上角品牌区域使用正式的 `assets/app-icon.png`，替换临时蓝底“资”字方块。
- PyInstaller 将正式 PNG 作为运行时资源打入软件包。
- 删除侧边栏左下角“单 worker · 串行提交”说明，只保留版本号。
- GitHub Actions 的三个下载 ZIP 和 Artifact 使用中文软件名称。
- 保留 Windows 内部目录和 EXE 的英文名称，避免中文路径兼容问题。
- 将运行时、Windows、macOS 和构建产物版本统一升级到 `0.30.2`。
- 提交并推送 `master` 和 `v0.30.2` 标签，确认 tag 构建已触发。

## 设计

- 新增冻结环境兼容的资源路径解析函数：开发环境从项目 `assets/` 读取，PyInstaller 环境从 `sys._MEIPASS/assets/` 读取。
- 使用 `CTkImage` 加载 RGBA 正式图标，保持固定显示尺寸和高分辨率缩放。
- 下载包命名为：
  - `百度资质自动提交工具-0.30.2-Windows-x64.zip`
  - `百度资质自动提交工具-0.30.2-macOS-arm64.zip`
  - `百度资质自动提交工具-0.30.2-macOS-x64.zip`

## 实现步骤

1. 更新任务文档。
2. 增加运行时图标资源解析和显示。
3. 更新 PyInstaller datas。
4. 删除侧边栏串行提交说明。
5. 更新 Actions 中文产物名称及 Release 下载规则。
6. 将版本统一升级到 `0.30.2`。
7. 补充并运行测试、自检和本地最小打包验证。
8. 提交、推送分支和标签，确认 Actions 触发。

## 验收标准

- [x] 开发环境能定位正式图标。
- [x] PyInstaller spec 包含正式 PNG 运行时资源。
- [x] 左上角显示正式图标。
- [x] 侧边栏不再出现“单 worker · 串行提交”。
- [x] 三个平台下载包使用中文名称。
- [x] 所有当前版本号均为 `0.30.2`。
- [x] 完整自动化测试通过。
- [x] 桌面入口自检通过。
- [ ] `master` 和 `v0.30.2` 已推送。
- [ ] GitHub Actions tag 构建已触发。

## 依赖

- Pillow 用于读取和缩放 PNG 图标，需同步维护 `requirements.txt` 和 `pyproject.toml`。

## 不在范围内

- 修改浏览器自动化业务流程。
- 将 Windows 内部 EXE 文件名改为中文。
- Windows/macOS 代码签名和公证。

## 本地验证记录

- UI、资源路径、打包和版本定向测试：9 项通过。
- 完整自动化测试：78 项通过。
- 源码桌面入口 `--self-check`：通过。
- macOS x64 PyInstaller 构建：通过。
- 冻结应用 `--self-check`：通过。
- 源码 GUI 与冻结应用实际启动：通过，冻结应用持续运行检查正常。
- 冻结包名称：`百度资质自动提交工具.app`。
- 冻结包内包含 `Contents/Resources/assets/app-icon.png`。
- Info.plist 显示名称为“百度资质自动提交工具”，版本为 `0.30.2`，内部可执行文件保持 `BaiduPartnerFlice`。
- `git diff --check`：通过。
