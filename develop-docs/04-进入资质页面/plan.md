# 任务 4：进入资质页面开发计划

## 目标

根据 `custId` 获取 `qulificationAuditUrl`，打开资质流程页面，点击“资质环节”，进入真实资质提交页面。

## 接口

```text
GET https://partner.baidu.com/polaris-web/onecrm-oneFrontArchive/archive/cust/summary/query?custId={custId}
```

响应字段：

```text
data.qulificationAuditUrl
```

接口字段拼写以实际返回为准，保留 `qulificationAuditUrl`，不在代码中改成其他拼写。

## 实现步骤

1. 使用任务 3 产生的 `custId` 发起 GET 请求。
2. 校验 HTTP 状态、JSON 格式和业务 `code == 0`。
3. 提取非空的 `data.qulificationAuditUrl`。
4. 在同一个浏览器上下文中新建页面打开该 URL。
5. 等待页面加载完成，并定位流程节点“资质环节”。
6. 点击“资质环节”节点；已有 XPath 可作为初始定位方案，同时保留基于可见文本/节点结构的备用定位方案。
7. 等待页面跳转完成。
8. 校验最终 URL 的协议、域名、路径和 Hash：

   ```text
   http(s)://fkzhunru.baidu.com/flice?动态参数#/truth/submit...
   ```

   协议可以是 HTTP 或 HTTPS，Hash 前可能有 `castk` 等动态查询参数；只判断域名、路径和 Hash 是否以 `#/truth/submit` 开头。

9. 确认页面已出现“主体资质”和“URL状态概览”等提交页面内容。

## 页面跳转说明

初始资质链接通常类似：

```text
.../flice#/lice/process/...
```

点击“资质环节”后进入：

```text
http(s)://fkzhunru.baidu.com/flice?castk=...#/truth/submit/...
```

不能用初始 URL 判断进入成功，也不能将带动态参数的最终 URL 做完整等值比较。

## 错误处理

- 资质链接为空或接口返回异常：当前公司失败。
- 找不到“资质环节”：等待后重试；仍失败则截图并记录。
- 点击后未进入 `#/truth/submit`：按页面跳转失败处理。
- 发现登录页：交由任务 2 重新人工登录。
- 当前公司失败后默认继续下一家公司。

## 验收标准

- 能根据动态 `custId` 请求并提取资质链接。
- 能打开资质流程页面并点击“资质环节”。
- 能识别带动态参数的 `#/truth/submit` 页面。
- 能在页面未完成加载或跳转失败时给出清晰错误。
- 成功后将页面对象和公司上下文交给任务 5。
