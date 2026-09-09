# 测试场景

- channel 正常时不执行路径回退。
- channel 缺失时可使用系统或用户路径。
- 无 Chrome 时显示中文安装提示并释放 Playwright。
- 非缺失错误保留原始异常。

结果：`.venv/bin/pytest tests/test_browser_helpers.py tests/test_application.py -q`，24 项通过。
