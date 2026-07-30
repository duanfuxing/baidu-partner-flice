# 任务 7：本模块最终提交与自动关闭

## 目标

所有经营业务和单个资质处理成功，且页面资质集合与 `input.json` 一致后：

1. 点击页面唯一可见的“本模块提交”或“全部提交”按钮。
2. 如出现确认弹窗，点击确认。
3. 等待 `POST /permit/web/permit/submitall`。
4. 仅在 HTTP 成功且响应 `status == 0` 时标记最终提交成功。
5. 公司成功或失败后关闭对应 worker Chrome，并将结果写入状态 JSON。

## 安全边界

- 任一单项资质失败时不得调用 `submitall`。
- 通过页面按钮触发请求，不从文档复制或自行拼接动态 token、URL ID 等参数。
- `--dry-run` 不点击最终提交。
- 最终接口失败时记录原始业务错误并保留页面。

## 实现

- `workflow.submit_all_qualifications`：定位按钮、处理确认弹窗并校验接口。
- `SubmissionResult.final_submission_success`：记录最终提交结果。
- `CompanyRunResult.final_submission_completed`：输出公司最终提交状态。
- CLI 成功时离开浏览器上下文并自动关闭；失败且为交互终端时等待人工检查。

## 验收

- 单项全成功时调用一次 `submitall`。
- 接口 `status != 0` 时整体失败。
- 任一单项失败时调用次数为 0。
- 成功后无人工回车提示，Chrome 自动关闭。
- 失败时 worker Chrome 自动关闭，错误写入统一和公司状态 JSON。
