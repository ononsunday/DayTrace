# DayTrace 第三方组件声明

这份声明对应 DayTrace 的 Windows 64 位目录式发布包。组件版本根据本次构建环境的包元数据、运行时版本和实际 DLL 文件核对。许可证原文与上游版权声明保存在同级 `third_party_licenses` 目录中。

DayTrace 自身代码、文档和原创界面素材采用根目录 LICENSE 中的 MIT 许可证。第三方组件分别受其原有许可证约束，项目 MIT 许可不替代这些条款。

## 构建与运行组件

| 组件 | 本次版本 | 用途及许可文本 |
| --- | --- | --- |
| CPython | 3.13.14 | Python 运行时。原安装包许可证为 `Python-3.13.14-LICENSE.txt`，包含 PSF、历史许可证及部分随附库的声明。 |
| PySide6 Essentials | 6.11.2 | Qt 的 Python 绑定。包元数据提供 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`。本交付按 LGPL v3 使用，原文见 `LGPL-3.0-only.txt` 及其引用的 `GPL-3.0-only.txt`。 |
| Shiboken6 | 6.11.2 | Python 与 C++ 绑定运行时。包元数据的许可选项与 PySide6 Essentials 相同，本交付按 LGPL v3 使用。 |
| Qt | 6.11.2 | 发布包使用 Qt Core、Gui、Widgets、Network、Svg，以及 Windows 平台、样式和图像插件。Qt 库按 LGPL v3 使用，内部第三方代码使用各自许可证。 |
| SQLite | 3.50.4 | Python 标准库 `sqlite3` 调用的本地数据库。SQLite 的原始代码属于公有领域；说明见 [SQLite 官方版权页面](https://sqlite.org/copyright.html)及 Qt 源码中的相关声明。 |
| OpenSSL | 3.0.21 | 随 CPython 运行时带入的 SSL 与加密 DLL。本版本采用 Apache 2.0，原文见 `OpenSSL-3.0.21-LICENSE.txt`。DLL 版权信息标明 Copyright 1998-2026 The OpenSSL Authors。 |
| Microsoft C/C++ 运行库 | 随 CPython 与 Qt 包附带 | 包含 `VCRUNTIME140`、`MSVCP140` 等 Windows 运行库；Microsoft Distributable Code 的分发说明保留在 Python 原始许可证中。 |
| PyInstaller | 6.22.3 | 生成目录式可执行包。其完整许可与 bootloader 例外见 `PyInstaller-6.22.3-COPYING.txt`。 |

DayTrace 本身不使用这些库访问网络服务器。Qt Network 用于同一台电脑上的单实例通信。发布构建排除 Qt 的 OpenSSL TLS 插件和未使用的软件 OpenGL 库，保留 Python 运行时自身的 OpenSSL；Windows 自带的 ICU 由操作系统提供，不复制到发布目录中。

`pytest` 和其他测试、安装、打包辅助包属于开发环境，不作为 DayTrace 的应用运行依赖列入此表。

## Qt 与 PySide6 的许可选择

Qt 为不同组件提供不同许可选项。本发布包使用 LGPL 范围内的库与插件，未使用 Qt Charts、Qt Graphs 或 WebEngine 等其他模块；图表由 Qt 原生绘图实现。[Qt 6.11 官方许可说明](https://doc.qt.io/qt-6.11/licensing.html)与 [Qt for Python 官方源码](https://code.qt.io/cgit/pyside/pyside-setup.git/)提供各组件的许可资料。

本地安装包元数据写明了开源许可选项，但其 `licenses` 目录只带有商业许可引用文件。因此本交付从 Qt 官方 6.11.2 源码档补充了 LGPL v3、GPL v2、GPL v3 和 Qt GPL exception 全文。保留的 `Qt-LicenseRef-Commercial.txt` 说明 Qt 的另一种许可选项，不表示 DayTrace 获得了商业 Qt 许可证。

Qt 库通过原始动态 DLL 使用。DayTrace 不限制为修改这些 LGPL 库而进行的逆向工程、替换或调试。需要替换时，先完全退出 DayTrace，备份发布目录，再将兼容的 DLL、Python 绑定和必要插件放回 `_internal\PySide6` 及 `_internal\shiboken6` 的对应位置。替换版本需要兼容 Windows 64 位、Python 3.13 和绑定所需的 Qt 接口；只替换其中一部分可能导致加载失败。

DayTrace 源码包包含应用自身的模块、依赖与 PyInstaller 构建脚本，可用于检查和重新构建应用。这个源码包没有内含完整 Qt、PySide6 或 Python 源码。对应第三方源码可从下列官方位置获取。

## 对应源码获取

| 源码 | 官方获取位置 |
| --- | --- |
| Qt 6.11.2 全量源码 | [Qt 6.11.2 官方源码目录](https://download.qt.io/archive/qt/6.11/6.11.2/single/)，提供 `qt-everywhere-src-6.11.2.zip` 与 `.tar.xz`。 |
| 本包涉及的 Qt 模块 | [Qt 6.11.2 模块源码目录](https://download.qt.io/archive/qt/6.11/6.11.2/submodules/)，选择 `qtbase`、`qtsvg`、`qtimageformats`，如需重新生成翻译文件再取 `qttranslations`。 |
| PySide6 与 Shiboken6 6.11.2 | [Qt for Python 6.11.2 官方源码目录](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/)，下载 `pyside-setup-everywhere-src-6.11.2.zip` 或 `.tar.xz`。源码仓库标签为 `v6.11.2`。 |
| CPython 3.13.14 | [CPython 官方 v3.13.14 标签](https://github.com/python/cpython/tree/v3.13.14)。 |
| OpenSSL 3.0.21 | [OpenSSL 官方 openssl-3.0.21 标签](https://github.com/openssl/openssl/tree/openssl-3.0.21)。 |
| PyInstaller 6.22.3 | [PyInstaller 官方 v6.22.3 标签](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)。 |

解压对应版本的源码档即可获取上游源码。重建 Qt 与 Python 绑定还需要兼容的 C++ 编译环境；具体步骤见 [Qt 6.11 Windows 源码构建说明](https://doc.qt.io/qt-6.11/windows-building.html)与 [Qt for Python 构建说明](https://doc.qt.io/qtforpython-6/building_from_source/index.html)。这里的源码网址用于获取上游代码，不声称这些完整源码已经随 DayTrace 发布包附带。

## Qt 内部第三方代码

许可证目录按原源码模块保留了 `LICENSES`、`qt_attribution.json` 和各组件自己的许可文件。它们来自官方 PySide6、Qt Base、Qt SVG 和 Qt Image Formats 6.11.2 源码档。目录中可能包含上游跨平台或开发工具的声明；保留这些文件不表示 DayTrace 在 Windows 上使用了每一个组件。

涉及的上游声明包括 zlib、PCRE2、double-conversion、HarfBuzz、FreeType、libpng、libjpeg-turbo、libtiff、libwebp、TinyCBOR、Unicode 数据及其他 Qt 内部代码。使用 FreeType 的部分受 FreeType Project License 等许可约束；本产品包含或可能通过 Qt 使用 FreeType Project 开发的软件。组件版权、版本和许可细节以各自原始文件及 [Qt 6.11 第三方代码清单](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html)为准。

`SOURCE_MANIFEST.json` 记录每份原文的来源、字节数和 SHA-256。许可证文本按原文件复制，没有改写条款。

## PyInstaller 例外

PyInstaller 主体采用 GPL v2 或更高版本。其 bootloader 例外允许将编译后的 bootloader 与相关加载文件和其他程序组合、分发，组合程序不会仅因使用这些文件而受到额外的 GPL 分发限制。这个例外没有替代 Python、Qt 或其他组件自己的许可证。[本地完整条款](third_party_licenses/PyInstaller-6.22.3-COPYING.txt)还分别说明了运行时 hooks 和附加运行时模块使用的 Apache 2.0，以及特定 isolated 模块的 MIT 选项。

复制或重新分发 DayTrace 时，请一并保留这份声明和 `third_party_licenses`，并继续遵守实际包含的组件条款。
