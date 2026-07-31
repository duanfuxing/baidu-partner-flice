# 仅标签触发发布打包计划

## 目标

普通 `master` 或 `main` 分支推送不再触发桌面安装包构建，避免同一版本在推送提交和版本标签时重复执行四平台打包。

## 范围

- 删除 GitHub Actions `push.branches` 配置。
- 保留 `push.tags: v*`，版本标签继续触发构建和 Release。
- 保留 Pull Request 校验和 `workflow_dispatch` 手工构建。
- 更新 README 的工作流触发说明。
- 增加触发条件回归测试。

## 验收标准

- [x] 推送 `master` 或 `main` 不触发该工作流。
- [x] 推送 `v*` 标签仍触发四平台构建和 Release。
- [x] Pull Request 和手工触发仍可运行。
- [x] GitHub Actions YAML 解析通过。
- [x] 定向测试和完整测试通过。
- [x] `git diff --check` 通过。

## 不在范围内

- 不修改四平台构建矩阵。
- 不取消正在运行的既有工作流。
- 不改变 Release 创建条件。

## 验证记录

- `pytest tests/test_installers.py`：5 项通过。
- `pytest`：88 项通过。
- GitHub Actions YAML 解析通过。
- `git diff --check`：通过。
