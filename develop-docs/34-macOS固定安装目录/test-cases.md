# 测试场景

配置禁用 relocation；独立根目录只包含目标 app；macOS 实际构建并展开最小安装包，检查安装位置和 relocation 元数据；Windows 安装配置回归。

结果：`.venv/bin/pytest tests/test_installers.py tests/test_packaging_assets.py -q`，12 项通过，包含 macOS 实际 pkg 构建和展开校验；未安装到系统目录。
