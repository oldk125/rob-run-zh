# ROB RUN 中文汉化适配工具

0.3.x 使用 C# 和 Windows Forms：定位、差分重建、安装、备份、还原及诊断均由原生程序实现。运行包不含 Python、PyInstaller、第三方补丁 DLL 或另附的运行库，使用 Windows 自带的 .NET Framework。

0.3.1 适配 Steam App `4262460`、游戏 Build `26807668`。本次资源共 4947 条文本，包含 118 条新增、25 条变化的英文；基于当前游戏原始字体重新制作中文扩展，保留已调整的原生分辨率采样方式。游戏上游的占位标识不据键名猜译。离线校验通过，当前更新的游戏内显示和兼容性仍需实际验证。

## 使用

1. 在 Windows 10/11 上完整解压原生版 ZIP，保留 `data` 目录和随附文本。
2. 退出游戏，双击 `ROB_RUN_CN.exe` 或 `启动汉化工具.bat`，无需安装本工具或 Python。
3. 自动定位或选择游戏目录，点击安装；从 Steam 正常启动游戏，在语言设置中选择“简体中文”。
4. 恢复原版时，退出游戏后点击“移除语言包”。

旧版用户（含 0.3.0）请先用本版移除已识别的旧语言包，再安装当前资源。本版精确识别旧记录及其备份，移除旧记录时只处理旧记录拥有的文件，不会删除新版官方缓存。未知文件、未知记录、版本不匹配和路径链接均会阻止覆盖。

安装在临时目录从本机原版资源重建并校验全部文件，再完整备份已有官方缓存并切换；不修改游戏安装目录原文件。支持操作锁、故障回滚及中断恢复。游戏更新前请移除语言包并保留备份。移除不要求旧版原始资源仍然存在。

本工具未签名。改用 C# 不代表杀毒产品或 SmartScreen 必然放行，程序不修改安全设置、不添加排除项、不关闭扫描。

## 编译原生版

Windows 自带的 .NET Framework C# 编译器即可，无需 Python、NuGet、Visual Studio 或 .NET SDK：

```bat
native\build_native.bat
```

产物在 `native\build\`。也可传入输出目录：

```bat
native\build_native.bat C:\build\ROB_RUN_CN
```

`native/Program.cs` 为原生界面，`native/Manager.cs` 为事务后端，`native/DeltaPatch.cs` 使用系统 GZipStream 解读差分。根目录旧 Python 源码仅保留为开发历史参考，不是 0.3.x 的运行入口；旧版构建脚本不适用于当前原生资源格式。

差分创建及游戏资源开发使用的 Python 工具属于开发流程，不会进入运行包。完整游戏资源、英文语料库与重建后的完整文件均不随发布包分发。

## 检查

原生事务回归只操作指定工作目录中生成的假游戏和假缓存：

```bat
%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /out:TestNative.exe /r:System.Web.Extensions.dll /r:System.Core.dll native\Manager.cs native\DeltaPatch.cs native\TestNative.cs
TestNative.exe C:\build\checks
```

界面自检不安装汉化、不启动游戏、不访问真实用户缓存：

```bat
native\build\ROB_RUN_CN.exe --self-test-ui native\build C:\build\checks\ui.json
```

## 权利与第三方组件

这是非官方中文适配项目。差分、免费及免责声明均不能替代权利人授权；使用和对外分发前请确认法律、授权及游戏协议允许的范围。见 [DISCLAIMER.md](DISCLAIMER.md) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，也可从界面底部离线查看。

更新发布包不能撤回他人已下载的文件或平台缓存中的历史副本。
