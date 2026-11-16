# ROB RUN 中文适配工具

Windows 桌面汉化管理器：自动定位游戏、安装简体中文、备份与还原、查看操作记录和导出本地诊断。

当前适配 Steam App `4262460`、游戏 Build `26615022`。工具在用户数据目录管理中文资源，不修改游戏安装目录原文件。

## 使用

1. 退出游戏，运行 `ROB_RUN_CN_0.2.6.exe`。
2. 点击“自动定位”或“选择目录”，确认 ROB RUN 安装位置。
3. 安装语言包，从 Steam 正常启动游戏，在语言设置中选择“简体中文”。
4. 恢复原版时，退出游戏后点击“移除语言包”。

从 0.2.5 升级无需重装语言包：本版仅调整分发方式和声明，重建后的语言资源逐字节相同。更早版本先移除旧语言包，再安装新版。游戏更新前应先移除语言包；遇到版本或文件校验不匹配时，工具会停止操作并保留现有文件。

0.2.6 改为发布差分补丁，安装时只读本机对应版本游戏资源，在临时目录重建并校验，再进入原有备份和安装流程。状态检查和移除不执行重建。完整游戏 bundle、目录数据和原文语料库不包含在本版源码包或 EXE 中。0.2.5 的字体生成方式保持不变，其最终视觉效果仍需在游戏中复核。

这是非官方工具，未因发布而取得游戏汉化授权。差分、免费和免责声明均不能替代权利人授权；译文及补丁的传播仍可能涉及相关权利。使用和对外分发前请确认法律、授权及游戏协议允许的范围。完整说明见 [DISCLAIMER.md](DISCLAIMER.md)，软件底部“免责声明”可查看正文与第三方许可。

## 从源码运行与编译

使用 Windows 版 Python 3.12，安装小型差分依赖；界面使用随 Python 提供的 Tkinter。

```powershell
python -m pip install -r requirements.txt
python ui_v2.py
```

编译单文件 EXE：

```powershell
python -m pip install -r requirements-build.txt
python build_exe.py
```

构建脚本生成 `ROB_RUN_CN.exe`，仅打包清单中的差分、UI 图标和许可声明。可用 `--name`、`--output`、`--work` 指定文件名、输出和中间目录。

`ui_v2.py` 是界面入口，`addon.py` 负责用户缓存中的安装与移除。`manager.py` 提供共用函数；新版入口不使用其中保留的旧界面。字体资源开发另需 `requirements-dev.txt` 中的 UnityPy 和 Pillow，运行管理器不需要安装它们。原文及完整开发资源不随源码分发。

## 检查

安装与还原测试使用临时目录；指定的游戏目录仅作为只读原版资源来源：

```powershell
python test_addon.py --game "D:\steam\steamapps\common\Rob Run"
```

## 第三方组件

详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 及随附许可。第三方组件的许可证不授予游戏内容的权利。

本版发布范围已排除完整资源，但旧 Git 提交、旧 Release 或用户下载的历史包可能仍含旧内容；新版本不能自动清除历史副本。
