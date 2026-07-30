# 跨平台应用图标接入计划

## 目标

将确认使用的品牌图标接入 Windows 和 macOS 桌面软件包，使 EXE、APP、任务栏、Dock 和文件管理器使用统一品牌图标。

## 范围

- 以 `assets/app-icon.png` 作为唯一正式设计源，不在正式文件名中携带设计迭代版本。
- 生成包含多尺寸图层的 Windows `app-icon.ico`。
- 生成标准 macOS `app-icon.icns`。
- PyInstaller 在 Windows EXE 和 macOS APP 中按平台选择图标。
- GitHub Actions 继续使用同一份 spec，无需增加 Secret 或运行依赖。
- 设计草稿和纯色背景源图不进入提交。

## 验收标准

- [x] 将确认采用的 v9 图片重命名为 `assets/app-icon.png`。
- [x] PNG 为 RGBA，四角透明且尺寸足够生成 1024px 图层。
- [x] ICO 包含至少 16、32、48、64、128、256px 尺寸。
- [x] ICNS 包含 macOS 标准 iconset 尺寸。
- [x] spec 在 Windows 使用 ICO，在 macOS 使用 ICNS。
- [x] macOS 冻结包构建成功，Info.plist 包含应用图标配置。
- [x] 冻结包 `--self-check` 通过。
- [x] 自动化测试全部通过。

## 完成记录

- 正式设计源：`assets/app-icon.png`。
- Windows 图标：7 个尺寸的 `assets/app-icon.ico`。
- macOS 图标：1024px ICNS 容器 `assets/app-icon.icns`。
- 设计过程源图和未采用的 v1/v2 草稿已加入忽略规则，不进入提交。
- 2026-07-30 确认采用无圆章、浅蓝渐变“资”字且位置向左下微调的 v9 设计，并将正式源图统一命名为 `assets/app-icon.png`。
- 新版图标资源定向测试 4 项通过；PNG、ICO 和 ICNS 文件格式检查通过。
- 74 项自动化测试通过。
- macOS Intel APP 构建、Info.plist 图标检查、冻结自检和实际启动通过。
- Windows x64 与 macOS Apple Silicon 由 GitHub Actions 在对应平台继续验证。

## 不在范围内

- 再次调整已确认的图形设计。
- Windows 代码签名和 Apple Developer ID 公证。
- 修改软件版本号。
