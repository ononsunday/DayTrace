# 素材说明

本目录的背景和功能图标由 `scripts/make_open_art.py` 中的 SVG 几何图形生成，采用项目 MIT 许可证。

| 素材 | 内容 | 可编辑源文件 |
| --- | --- | --- |
| `main-art.png` | 抽象天空、山丘、时钟和花朵 | `main-art.svg` |
| `backdrop.png` | 淡色天空和山丘 | `backdrop.svg` |
| `stickers.png` | 12 个导航和操作图标，4 列 3 行 | `stickers.svg` |

素材不使用第三方角色图片、壁纸、表情包或字体文件。PNG 由 Qt SVG 渲染器生成。修改 SVG 几何描述后，运行生成脚本更新文件。

应用图标 `assets/daytrace.ico` 由 `scripts/make_icon.py` 调用项目内的 `app_icon()` 绘制，采用同一许可证。
