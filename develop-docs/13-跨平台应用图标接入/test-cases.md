# 测试用例

## 资源

1. v3 PNG 能读取为 RGBA，四角 alpha 为 0。
2. ICO 能读取并包含 Windows 常用尺寸。
3. ICNS 文件存在且非空。

## 打包

1. Windows 分支选择 `.ico`。
2. macOS 分支选择 `.icns`。
3. macOS APP 的 Info.plist 包含 `CFBundleIconFile`。
4. 冻结应用 `--self-check` 返回 0。

## 回归

1. 完整 pytest 通过。
2. GitHub Actions 的 Windows/macOS 构建命令不变。
3. 图标资源不引入新的软件运行依赖。

## 验证结果

- 图标资源与冻结自检定向测试：6 项通过。
- 完整测试：74 项通过。
- ICO：识别为包含 7 个图层的 Windows icon resource。
- ICNS：识别为 1024px Mac OS X icon。
- macOS APP：`CFBundleIconFile=app-icon.icns`。
- 冻结应用 `--self-check`：通过。
- 新版应用实际启动：通过。
