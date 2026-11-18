# 第三方组件与权利说明

- 中文字形来自 Noto Sans SC，转换为静态 SDF 字形并加入字体资源，字体部分继续依 SIL Open Font License 1.1 使用，见 FONT_LICENSE.txt。保留用户本地原字体的既有字形；Libertinus 的许可见 LIBERTINUS_LICENSE.txt。字体修改不表示原作者认可本工具。
- 原生差分读取器由 C# 实现，使用 .NET 的 GZipStream，沿用 BSDIFF 差分语义。开发期创建差分使用 bsdiff4，原始组件及 BSDIFF 声明见 BSDIFF4_LICENSE.txt；运行包不包含 bsdiff4 二进制库。
- 原生界面使用 Windows Forms 和系统字体，不使用第三方界面框架；运行时由 Windows 已安装的 .NET Framework 提供，不随包重新分发。
- Python、UnityPy、Pillow 等仅用于资源开发或旧版本实现；0.3.0 运行包不包含 Python、Tcl/Tk 或 PyInstaller。开发及旧版组件许可保留在源码仓库的相应 LICENSE 文件与 third_party_licenses/ 中。

Noto Sans SC 源码：https://github.com/google/fonts/tree/main/ofl/notosanssc
Libertinus 源码：https://github.com/alerque/libertinus
Feather 源码：https://github.com/feathericons/feather
bsdiff4 源码：https://github.com/ilanschnell/bsdiff4

游戏相关资源与译文的权利边界另见 DISCLAIMER.md。以上许可只适用于对应第三方组件，不构成游戏汉化或游戏资源分发授权。
