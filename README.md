# 百度资质自动提交工具

当前版本：`0.30.0`

本工具读取用户选择的公司资质输入目录，通过 Playwright 控制本机 Google Chrome，完成百度客户资质流程的校验、登录、公司查询、经营业务维护、资质上传和最终提交。

## 桌面版使用

1. 从 GitHub Actions 的构建产物或 GitHub Release 下载对应系统的软件包。
2. 解压整个软件包，不要只复制其中的 EXE。
3. 确保电脑已安装 Google Chrome。
4. Windows 双击 `BaiduPartnerFlice.exe`；macOS 打开 `BaiduPartnerFlice.app`。
5. 每次任务点击“选择输入目录”，选择包含公司目录的根目录。
6. 在“任务中心”查看统计卡和输入验证结果；只有全部校验通过后才可点击“开始运行”。
7. 如需在所有资质填写完成后直接最终送审，勾选“完成后执行全部提交”；默认不勾选，只完成资质填写并跳过最后的“全部提交”。
8. Chrome 提示登录时人工完成登录，然后回到软件点击“我已完成登录”。
9. 在“本次运行”查看进度和实时日志，在“历史日志”查看以往任务。

软件始终使用一个 worker，所有公司按顺序逐个处理，不并发提交。
如需取消，点击“取消任务”：登录阶段会立即取消；公司已经开始处理时，会等待当前公司稳定结束后停止后续公司，避免破坏提交状态。

登录状态和日志保存在当前用户的应用数据目录：

- Windows：`%LOCALAPPDATA%\BaiduPartnerFlice`
- macOS：`~/Library/Application Support/BaiduPartnerFlice`

调度状态、公司状态、标准化输入和提交结果仍保存在用户选择的输入目录中。

## 命令行开发运行

```bash
source .venv/bin/activate
python main.py --input input
```

测试：

```bash
pytest
```

## GitHub Actions 打包

`.github/workflows/build-desktop.yml` 在以下场景构建：

- 推送到 `master` 或 `main`
- Pull Request
- 手工触发
- 推送 `v*` 标签

构建产物包括：

- Windows x64 zip
- macOS Apple Silicon zip
- macOS Intel zip

每个平台完成构建后都会先执行离线 `--self-check`，验证 Tk、Playwright、文件锁和冻结程序 spawn 子进程，再上传软件包。

推送版本标签（例如 `v0.30.0`）后，工作流会在所有平台构建成功后自动创建 GitHub Release 并附加三个压缩包。

首版产物未做 Windows 代码签名、Apple Developer ID 签名或公证，首次打开时操作系统可能显示安全提示。
