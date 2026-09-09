# 测试场景

- 应用版本、Windows 数字版本、macOS Bundle/PKG 版本一致。
- 四架构产物名称包含 0.30.7。
- 举证链接纯值及可选文件回归通过。
- 标签指向发布提交，Actions 由标签触发。

执行结果：`.venv/bin/pytest tests/test_packaging_assets.py tests/test_installers.py tests/test_input_loader.py tests/test_application.py -q`，34 项通过。
