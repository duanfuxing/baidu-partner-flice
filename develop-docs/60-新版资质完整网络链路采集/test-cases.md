# 测试与验收

| 场景 | 预期 | 状态 |
| --- | --- | --- |
| 敏感 JSON、URL、multipart 参数 | 无认证值、原始动态标识、文件内容落盘；相同标识匿名代号一致 | 通过 |
| 本地多文件上传和保存 | request/response/finished 与页面 change/save 事件关联 | 通过，2 次选择文件及保存 |
| 失败响应和网络终止 | 区分 HTTP 失败与 requestfailed，保留阶段 | 通过，503 响应与 connectionreset |
| 真实已存在草稿 | 先检查，不擅自清理或覆盖其他资质 | 已检查：业务数量为 0，无需清理 |
| 真实三文件资质 | 逐文件观察，完成后重新打开并核对文件与举证 | 已完成；程序第三张误报超时，独立重新打开核验通过 |
| 最终送审保护 | submitall 被阻止且没有成功送审请求 | 5 个分支测试通过；真实采集 submitall 请求数为 0 |
| 浏览器已关闭时结束采集 | 收尾仍落盘，不覆盖原错误 | 通过；重复 close 也无异常 |

执行：`.venv/bin/pytest tests/test_qualification_trace.py -q`，9 项通过。`git diff --check` 通过。真实记录及已确认误报证据见 `findings.md`。

真实登录人工完成；日志仅保留脱敏事件，不保存原始网络档案。
