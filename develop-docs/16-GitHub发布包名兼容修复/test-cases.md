# 测试用例

## 发布文件命名

1. Windows x64 Artifact 名称为 `BaiduPartnerFlice-0.30.3-Windows-x64`。
2. macOS arm64 Artifact 名称为 `BaiduPartnerFlice-0.30.3-macOS-arm64`。
3. macOS x64 Artifact 名称为 `BaiduPartnerFlice-0.30.3-macOS-x64`。
4. 工作流中的三个 Artifact 名称均不包含中文字符。
5. Release 下载规则为 `BaiduPartnerFlice-*`。

## 中文品牌回归

1. GitHub Release 标题仍为“百度资质自动提交工具 + tag”。
2. macOS App 名称和显示名仍为“百度资质自动提交工具”。
3. Windows 产品显示名仍为“百度资质自动提交工具”。

## 回归

1. Python、Windows、macOS 和 Actions 版本均为 `0.30.3`。
2. 打包资源与版本定向测试通过。
3. 完整 `pytest` 通过。
4. `git diff --check` 通过。

## 验证结果

- 打包资源与命名定向测试：5 项通过。
- 桌面入口 `--self-check`：通过。
- 完整自动化测试：78 项通过。
- `git diff --check`：通过。
