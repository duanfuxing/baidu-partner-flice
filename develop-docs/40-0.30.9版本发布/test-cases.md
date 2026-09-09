# 测试场景

版本号、Windows 数字版本、macOS Bundle/PKG 版本与安装包名称一致；macOS 禁用 relocation；标签触发发布。

执行结果：`.venv/bin/pytest tests/test_installers.py tests/test_packaging_assets.py -q`，12 项通过。
