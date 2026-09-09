# 任务 34：macOS 固定安装目录

## 目标与范围

修复安装器将应用迁移到项目 dist 中已有副本的问题，固定安装到 /Applications/百度资质自动提交工具.app。

## 原因

本机 0.30.8 安装日志明确记录 Applications 下应用被 relocated 到项目 dist。现有 pkgbuild --component 未禁用 relocation。

## 设计与步骤

使用仅含目标 app 的暂存根目录，配合 --root 和 --component-plist；显式设置 BundleIsRelocatable=false。保持包标识、版本号及用户数据位置。以最小测试 app 实际执行 pkgbuild，解包检查安装位置、bundle 路径和 relocation 元数据。

## 依赖

任务 17 安装器、macOS 自带 pkgbuild/pkgutil；无新增依赖。

## 验收标准

工作流使用独立暂存根；生成的 pkg 安装位置为 /Applications 且禁用 relocation；安装配置测试通过。旧 dist 中的副本和用户数据保持原样。

## 不在范围内

不修改已发布旧包、不发布新版本、不自动安装到系统目录。

## 验收结果

已完成。安装器及打包资源 12 项测试通过；实际 pkgbuild 生成最小 app 安装包，pkgutil 解包确认 install-location=/Applications、relocatable=false、relocate 无 bundle。git diff --check 通过。未执行系统安装或发布新包，真实系统安装仍需使用重新生成的包验收。
