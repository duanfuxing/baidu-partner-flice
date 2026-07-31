# GitHub 发布包名兼容修复计划

## 目标

修复 GitHub Release 上传中文 ZIP 文件名后，中文品牌部分被移除、下载文件只剩版本和平台后缀的问题。

## 范围

- 将 GitHub Actions 的 Artifact 名称和 ZIP 实际文件名恢复为 ASCII 品牌名。
- 将 Release 下载 Artifact 的匹配规则同步改为 ASCII。
- 保留桌面应用、macOS App 和 GitHub Release 标题中的中文显示名。
- 增加工作流命名回归测试。
- 将修复版本统一升级为 `0.30.3`，提交并创建 `v0.30.3` 标签。

## 设计

- 三个平台发布文件分别使用：
  - `BaiduPartnerFlice-0.30.3-Windows-x64.zip`
  - `BaiduPartnerFlice-0.30.3-macOS-arm64.zip`
  - `BaiduPartnerFlice-0.30.3-macOS-x64.zip`
- GitHub 会重命名包含特殊字符或非字母数字字符的 Release Asset 文件名；因此实际文件名只使用 ASCII。
- 中文品牌继续用于应用可见名称和 Release 标题，不影响用户识别。

## 实现步骤

1. 建立任务文档并记录已发布版本中的问题。
2. 修改三平台 Artifact 和 ZIP 名称。
3. 修改 Release Artifact 下载匹配规则。
4. 更新命名测试并运行相关测试。
5. 将运行时、Windows、macOS 和构建产物版本统一升级到 `0.30.3`。
6. 运行完整测试和差异检查。
7. 提交变更并创建 `v0.30.3` 标签。

## 依赖

- 不新增依赖。

## 验收标准

- [x] 三个平台 Artifact 和 ZIP 均以 `BaiduPartnerFlice-0.30.3-` 开头。
- [x] Release 下载规则只匹配 ASCII Artifact 名称。
- [x] Release 标题仍显示“百度资质自动提交工具”。
- [x] macOS App 中文显示名不变。
- [x] 所有当前版本号均为 `0.30.3`。
- [x] 相关自动化测试通过。
- [x] 完整自动化测试通过。
- [x] `git diff --check` 通过。
- [x] 已创建提交和 `v0.30.3` 标签。

## 不在范围内

- 修改桌面应用业务流程。
- 删除或覆盖已发布的 `v0.30.2` Release Asset。

## 验证记录

- 打包资源与命名定向测试：5 项通过。
- 桌面入口 `--self-check`：通过。
- 完整自动化测试：78 项通过。
- `git diff --check`：通过。
- 修复变更已提交并创建本地 `v0.30.3` 标签；尚未推送远端。
