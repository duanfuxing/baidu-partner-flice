# 发布检查

- 程序、pyproject、Windows版本资源、Windows/macOS安装器、工作流产物名、README和版本测试均为0.30.16。
- 任务55的81个不同场景、任务56/57的74项相关回归已通过，详见对应任务记录。
- 包装资源、安装器、自检及资源测试；git diff --check。
- master和v0.30.16标签成功推送，标签工作流触发；不将“已触发”记作“安装包已完成”。

结果：`.venv/bin/pytest tests/test_packaging_assets.py tests/test_installers.py tests/test_self_check.py tests/test_resources.py`：17 passed。git diff --check通过；发布配置中未残留0.30.15。代码83d5270及v0.30.16已原子推送；已确认标签push触发运行34586821089，headSha一致。未等待构建结束或下载验收安装包。
