# GitHub 上传步骤

本目录是源码仓库的根目录。发布前先阅读 README、LICENSE 和第三方声明。

## 网页上传

1. 在 GitHub 新建仓库，名称可以填写 `DayTrace`，可见性选择 Public。
2. 不勾选自动创建 README、`.gitignore` 和许可证，本提交包已经包含这些文件。
3. 使用“上传文件”，把本目录中的文件和子目录上传到仓库根目录。不要只上传源码 ZIP，也不要把外层 `DayTrace-GitHub` 当作一层子目录。
4. 检查 `README.md`、`LICENSE`、`.gitignore`、`daytrace/`、`tests/`、`scripts/`、`assets/` 和 `third_party_licenses/` 都已上传。隐藏的点文件也需要提交。
5. 打开仓库首页，检查 README 预览图片和文档链接。GitHub Actions 会在推送后运行 Windows 测试；查看它的实际结果。

如果网页提示文件数量或大小限制，使用 GitHub Desktop，选择克隆新建的仓库，把本目录内容复制到克隆目录，再 Commit 和 Push。

## 软件下载安装包

源码仓库不需要 EXE、`_internal`、虚拟环境或本地数据库。需要提供可运行软件时，按 README 打包并生成交付目录，将完整目录压缩后上传到 Releases。

建议 Release 标签使用 `v1.1.1`。描述中写明 Windows 64 位、本地保存数据、统计精度和本次验证范围。二进制包需要保留第三方声明与许可目录。

本地整理完成不代表已经上传到 GitHub；仓库地址、网页呈现和 Actions 结果需在上传后确认。
