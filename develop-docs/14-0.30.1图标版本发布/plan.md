# 0.30.1 图标版本发布计划

## 目标

将确认采用的新版应用图标作为正式资源发布，并将桌面软件版本从 `0.30.0` 升级到 `0.30.1`，通过 `v0.30.1` 标签触发 GitHub Actions 构建 Windows 与 macOS 软件包和 GitHub Release。

## 范围

- 正式图标源统一命名为 `assets/app-icon.png`。
- 更新 Windows ICO 与 macOS ICNS。
- 将项目元数据、应用版本、Windows 文件版本、macOS Bundle 版本及构建产物名称统一为 `0.30.1`。
- 提交并推送 `master` 分支。
- 创建并推送 `v0.30.1` 标签。
- 确认 GitHub Actions 发布工作流已触发。

## 实现步骤

1. 更新开发任务文档和任务索引。
2. 更新所有运行时、打包和构建产物版本号。
3. 运行完整自动化测试和差异检查。
4. 提交并推送分支。
5. 创建并推送发布标签。
6. 检查 GitHub Actions 运行状态。

## 验收标准

- [x] 所有当前版本号均为 `0.30.1`。
- [x] 正式 PNG、ICO、ICNS 资源检查通过。
- [x] 完整自动化测试通过。
- [x] `git diff --check` 通过。
- [ ] `master` 已推送到 `origin`。
- [ ] `v0.30.1` 标签已推送。
- [ ] GitHub Actions 已创建对应的 tag 构建。

## 依赖

- GitHub Actions 使用仓库自带的 `GITHUB_TOKEN` 创建 Release，无需额外配置仓库密钥。
- Windows 与 macOS 构建由 GitHub 托管 runner 完成。

## 不在范围内

- 修改自动化业务流程。
- Windows 代码签名。
- Apple Developer ID 签名、公证和自动更新。

## 本地验证记录

- 版本与图标资源定向测试：5 项通过。
- 完整自动化测试：75 项通过。
- 桌面入口 `--self-check`：通过。
- 当前运行时与打包配置中无残留 `0.30.0`。
- `git diff --check`：通过。
