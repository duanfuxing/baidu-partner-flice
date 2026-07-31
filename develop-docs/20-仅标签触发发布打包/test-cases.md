# 测试用例

1. 工作流不存在 `push.branches`。
2. 工作流保留 `push.tags: "v*"`。
3. 工作流保留 `pull_request`。
4. 工作流保留 `workflow_dispatch`。
5. Release job 仍仅在 `refs/tags/v` 下运行。
6. YAML 解析、定向测试和完整测试通过。

## 验证结果

- 触发条件定向测试：5 项通过。
- 完整测试：88 项通过。
- GitHub Actions YAML 解析通过。
