# 问题记录

| 编号 | 问题 | 状态 | 解决方案 |
| --- | --- | --- | --- |
| 13-001 | 当前 macOS `iconutil` 将尺寸正确的 iconset 判为 Invalid Iconset | 已解决 | 使用 Pillow 从 1024px RGBA 源图原生编码 ICNS，并以 `file`、`sips` 和自动化测试校验 |
