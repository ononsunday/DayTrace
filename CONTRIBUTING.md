# 贡献说明

修复问题或增加功能前，请先查看现有 Issues，说明出现问题的操作步骤、期望结果和实际结果。

请勿上传个人数据库、日记、应用使用记录或未经处理的日志。复现问题时可以设置 `DAYTRACE_DATA_DIR`，使用独立测试目录。

## 本地验证

按照 README 创建开发环境，然后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

修改界面后，在 Windows 上运行以下脚本，检查页面、托盘和主题。脚本使用临时数据，仅保存测试程序的窗口图像。

```powershell
.\.venv\Scripts\python.exe scripts\verify_desktop.py
```

打包步骤见 README。`scripts/check_bundle.py` 是可选的 DLL 诊断工具，另需安装 `pefile`。

## 提交修改

Pull Request 请写清问题、修改后的行为和实际执行的验证。涉及统计规则时，说明是否改变前台归属、空闲阈值、午夜拆分或失败重试。

新增素材应使用你有权公开分发的内容，并记录来源、许可证和生成方法。第三方许可原文不要改写；依赖版本变化后，应同步核对第三方声明。

向项目提交贡献时，你同意将有权授权的贡献按本项目 MIT 许可证提供。第三方内容继续遵守其原有条款。
