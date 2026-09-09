# 测试场景

- 正常：无表单信息.txt，有图片，解析通过，保存 evidenceUrl=null。
- 边界：无表单信息.txt 且无图片/PDF，仍提示缺少资质文件。
- 回归：空表单、纯链接、旧标签格式及应用流程。

执行结果：`.venv/bin/pytest tests/test_input_loader.py tests/test_application.py -q`，24 项通过。
