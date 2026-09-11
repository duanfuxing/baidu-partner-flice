# 测试场景

- 正常、初始加载延迟、重置其他筛选、相同结果、残留红色错误提示。
- 慢响应、非本轮请求响应、其他URL/页码/路径/域名/请求方法不匹配。
- HTTP错误、业务错误、非JSON、响应结构异常、网络失败、未发请求或请求无响应。
- 空结果、相似URL、重复URL、分页、接口成功但表格不刷新或一直加载。
- 监听器和DOM观察器在成功/失败后清理；日志不含动态URL、Token或响应原文。
- 旧版原页与新版新标签详情入口回归。

结果：通过。所有接口拦截在本地Chrome中完成，不使用真实认证信息。

- `.venv/bin/pytest tests/test_url_overview.py tests/test_browser_error_close.py tests/test_browser_helpers.py tests/test_application.py`：70 passed。
- `.venv/bin/pytest tests/test_url_overview.py::test_query_unauthorized_requires_login tests/test_playwright_flow6.py -k 'unauthorized or pending_review_url or new_url_row_view'`：4 passed，58 deselected。
- compileall、git diff --check通过。
- 慢响应只有一次页面请求；旧响应虽成功也不接受；请求方法、域名、路径、URL、页码不符以及重复参数均不接受；成功/失败均清理监听。
- HTTP401/403要求重新登录；业务错误只记录状态码，不回显响应中的认证内容。
- 真实页面和Windows验收未执行，未打包发布。
