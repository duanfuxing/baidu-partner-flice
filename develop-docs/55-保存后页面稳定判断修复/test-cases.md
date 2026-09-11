# 测试场景

- 正常：匹配保存凭据的文件和举证稳定后通过；延迟状态/文件回填后通过。
- 异常：文件丢失、错误身份、图片未加载、举证错误、当前卡片或父级遮罩一直存在时失败并说明原因。
- 边界：状态文字未更新但已校验保存响应、文件/举证一致时通过；相邻卡片独立遮罩不阻塞；卡片暂时移除后重建继续等待；永久消失不能提前返回。
- 回归：无预览凭据页面继续检查已有保存状态；保存业务失败不进入后续上传；逐文件保存和生产组件重新定位仍通过。
- 自动测试仅使用本地 HTML 和拦截请求，无真实上传和最终送审。

结果：本地 Chrome 全部通过。具体执行记录：

- 修复前：`.venv/bin/pytest tests/test_card_save_settle.py::test_other_card_loading_does_not_block_saved_card`，1 failed，复现相同的保存后刷新稳定超时。
- 第一轮：`.venv/bin/pytest tests/test_card_save_settle.py tests/test_card_autosave.py tests/test_new_audit_qualification.py`，45 passed。
- 补充用例后：`.venv/bin/pytest tests/test_card_save_settle.py tests/test_playwright_flow6.py -k 'card_save_settle or new_audit'`，50 passed，28 deselected。包含18项保存稳定性场景、32项新版流程，覆盖文件丢失停止、逐文件保存、最终审核模拟接口及上传内容核验。
- 额外覆盖空举证链接、隐藏遮罩、无凭据时状态不可绕过，以及恢复后再次异步清空必须重新累计稳定时间。
- `.venv/bin/python -m compileall -q src/new_audit_qualification.py tests/test_card_save_settle.py`、`git diff --check`通过。

两轮有14项重叠，共81个不同场景通过。Windows 真机回归需要安装修复版本后验收；未打包发布。
