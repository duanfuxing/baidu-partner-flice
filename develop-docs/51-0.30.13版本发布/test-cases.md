# 测试场景

- 正常：版本一致性、定位回归、四平台完整测试、自检和安装器构建。
- 异常及边界：不覆盖已有标签；任一构建失败不得视为发布完成；检查四个附件非空。
- 本地结果：版本/安装资源检查与业务标签定位回归共16项通过；git diff --check通过。
- 发布提交：89213e5；标签 v0.30.13。
- CI：https://github.com/duanfuxing/baidu-partner-flice/actions/runs/34560354010 （首轮失败，未发布）。

- 最终0.30.14：本地16项复测通过；CI 34565955190四平台测试、自检、打包与Release全部成功。
- Release附件：macOS arm64 60332702字节、macOS x64 63004797字节、Windows arm64 36356779字节、Windows x64 41510856字节；全部uploaded。
