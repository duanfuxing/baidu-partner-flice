# 任务 3：公司搜索开发计划

## 目标

调用百度公司搜索接口，根据一级目录公司名取得唯一的 `custId`。

## 接口

```text
POST https://partner.baidu.com/polaris-web/onecrm-oneFrontArchive/archive/cust/list/query
```

请求体中的 `custName` 使用任务 1 输出的 `companyName`。其他查询参数按接口文档的默认值发送，包括 `queryType=2`、`isAgentPlatform=true`、`pageNum=1`、`pageSize=20` 等。

## 实现步骤

1. 从已登录的 Playwright 浏览器上下文获取请求客户端，确保请求携带当前 Cookie。
2. 为每个公司构造 POST 请求体，仅动态替换 `custName`。
3. 校验 HTTP 状态和响应 JSON。
4. 校验业务 `code == 0`。
5. 读取 `data.totalCount` 和 `data.result`。
6. `totalCount == 1` 时提取 `data.result[0].custId`。
7. `totalCount == 0` 或大于 1 时生成明确业务错误，不继续进入资质页面。
8. 保存脱敏后的搜索结果摘要，不能记录 Cookie 或 Token。

## 数据输出

为后续任务输出：

```text
companyName
url
custId
```

可以保留接口返回的 `siteUrlList` 作为诊断信息，但流程 5 仍以页面“URL状态概览”表格为最终匹配来源。

## 重试和错误

- 网络错误、连接超时和 5xx 错误可有限重试。
- 业务错误、未授权和结果数量不唯一不应盲目重试。
- 发现会话失效时交由任务 2 处理人工重新登录。
- 当前公司失败后默认记录并继续下一家公司。

## 验收标准

- 请求 URL、方法和动态参数正确。
- 使用当前浏览器会话的认证信息。
- 能正确提取示例公司的 `custId`。
- 能区分 0、1、多个搜索结果。
- 响应格式错误时有明确错误路径。
- 不在日志中暴露认证信息。
