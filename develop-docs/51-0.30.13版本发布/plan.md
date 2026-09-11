# 0.30.13版本发布

目标：发布任务50的业务标签动态定位修复。
范围：统一版本、提交代码、四平台打包及 GitHub Release。
设计与步骤：确认新标签未占用；同步版本；执行版本和定位回归；提交并推送 master 与 v0.30.13；等待四平台测试、自检、安装器及发布；核对附件。
依赖：现有 GitHub Actions 和 PyInstaller，无新增依赖。
验收：版本一致，Windows/macOS 的 x64/arm64 构建均通过，Release 四个非空安装包可用。
不在范围内：修改输入、真实业务操作或最终审核。
初始状态：进行中；任务50相关页面回归已通过，Windows真实业务验收尚未执行。

调整：首轮未发布成功；Windows夹具400毫秒等待不足，调整到5秒；macOS x64附件上传403。保留v0.30.13标签，发布版本顺延0.30.14，重新执行四平台CI。

完成结果：最终版本0.30.14，提交0504db2，四平台完整测试、自检、安装包构建及Release全部成功。发布页非草稿，四个附件均非空且uploaded。当前Windows真实业务验收仍待用户安装后验证。

构建：https://github.com/duanfuxing/baidu-partner-flice/actions/runs/34565955190

下载：https://github.com/duanfuxing/baidu-partner-flice/releases/tag/v0.30.14
