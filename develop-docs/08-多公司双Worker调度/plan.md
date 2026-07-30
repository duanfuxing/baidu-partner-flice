# 任务 8：多公司双 Worker 调度

## 目标

不增加 `--workers` 参数，根据公司数量自动选择并发数：

- 1 个待处理公司：1 个 worker。
- 2 个及以上待处理公司：最多 2 个 worker。
- 3 个公司：先并行两个，任一完成后由空闲 worker 处理第三个。

## 执行顺序

1. 主进程解析全部公司并生成 `input.json`。
2. 主进程启动一次 Chrome，完成登录检测或人工登录。
3. 保存 `.auth/storage_state.json` 并关闭登录 Chrome。
4. 通过统一调度器原子预留待处理公司。
5. 使用 spawn 多进程启动最多两个 worker。
6. 每个 worker 启动独立 Playwright 和 Chrome，直接加载登录状态并处理一个公司。
7. worker 完成后关闭 Chrome，进程池自动领取下一个排队公司。
8. 主进程汇总结果并输出调度文件路径。

## 状态文件

### `input/scheduler.json`

记录：

- `maxWorkers`：固定为 2。
- `queuedCompanies`：已预留、等待 worker 的公司。
- `runningCompanies`：当前实际执行的公司。
- `companies`：每家公司状态、runId、协调进程 PID、worker PID、时间、结果和错误。

### `input/<公司>/execution-status.json`

保存该公司的最新状态副本，状态包括：

- `queued`
- `running`
- `success`
- `failed`
- `dry-run-success`

## 防争抢

- 使用 `.scheduler.lock` 和 `fcntl.flock` 跨进程互斥。
- 所有 JSON 使用临时文件写入后原子替换。
- 存活协调进程持有的 queued 公司和存活 worker 持有的 running 公司不可被另一主程序领取。
- PID 已不存在时允许回收陈旧任务。
- 相同输入文件哈希已有最终提交成功结果时直接跳过，防止重复送审。

## 登录约束

- 只有主进程调用 `ensure_logged_in` 并保存登录状态。
- worker 不调用登录检测，不提示人工登录，不写 storage state。
- 登录状态失效时由 worker 按业务错误失败，下一次主程序重新执行统一登录检查。

## 关闭行为

- 登录 Chrome 保存状态后自动关闭。
- 每个 worker Chrome 在公司成功或失败后自动关闭。
- 所有 worker 结束后主程序退出。
