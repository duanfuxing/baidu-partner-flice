# 任务 30：Chrome 缺失提示与路径兼容

## 目标与范围

处理 Windows 启动时报 Chrome distribution not found 的情况，明确提示安装 Google Chrome；兼容常见系统和用户安装路径。

## 设计与步骤

保留 Playwright channel 启动；仅在明确找不到 Chrome 时探测 Windows ProgramW6432、ProgramFiles、ProgramFiles(x86)、LOCALAPPDATA 下的 Google/Chrome/Application/chrome.exe 并重试。仍找不到时给出中文提示。其他启动错误保留原始异常。

## 依赖

任务 2 的会话管理；不增加依赖。

## 验收标准

模拟测试覆盖路径兼容、缺失提示、其他错误不被误报以及失败资源释放；原浏览器辅助测试通过。

## 不在范围内

不自动安装浏览器，不使用日常 Chrome 个人资料，不变更版本号或发布；Windows 真机验证待用户执行。

## 验收结果

本地浏览器辅助及应用回归测试共 24 项通过。Windows 路径及启动分支使用模拟测试；未在用户 Windows 机器上验证，尚未打包发布。
