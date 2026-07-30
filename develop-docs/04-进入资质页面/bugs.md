# 任务 4：Bugs

| ID | 发现日期 | 问题 | 复现条件 | 状态 | 解决方案 |
| --- | --- | --- | --- | --- | --- |
| BUG-004 | 2026-07-29 | 实际页面使用 HTTP 且 URL 在 Hash 前包含 `?castk=...`，代码强制要求 HTTPS 且完整匹配，误判未进入资质页面 | 点击“资质环节”后 URL 为 `http://fkzhunru.baidu.com/flice?castk=...#/truth/submit/...`，页面已出现“URL状态概览” | 已修复 | URL 允许 HTTP/HTTPS，解析 pathname 和 hash；“URL状态概览”作为进入页面的 DOM 成功标志 |
