# 便携版

解压即用，数据跟着目录走，拷走整个目录就带走了全部状态。

## 产物

```
release/PurrCat-portable-0.1.0.zip   (~329 MB，含本地嵌入模型)
```

解压后：

```
PurrCat-portable/
  PurrCat.exe                  主程序
  resources/
    app.asar                   应用代码
    backend/                   Python 后端 sidecar
  portable.flag               便携模式标记
  data/                       所有数据都在这里
    embedding/                 本地语义检索模型
    core/ data/ electron/ ...  配置、研究库、Electron 状态
```

## 怎么用

解压到任意目录（U 盘、共享盘、临时目录都行），双击 `PurrCat.exe`。
不需要安装、不写注册表、不写全局 PATH。

**换机器 / 备份**：直接拷贝 `data/` 目录，或整个程序目录。

## 它和安装版的区别

只有一处：**程序目录旁有没有 `portable.flag`**。

| | 安装版 | 便携版 |
|---|---|---|
| 数据根 | `~/.purrcat` | 程序目录旁的 `data/` |
| Electron userData | 系统默认位置 | `data/electron/` |
| 自动更新 | 从 GitHub Releases 检查 | 关闭（换目录即升级） |
| 安装 / 注册表 | NSIS / dmg 安装 | 无 |

Python 侧通过 `PURRCAT_DIR` 环境变量统一覆盖数据根——
Electron 在启动后端时注入它，所有路径常量（技能、论文库、数据集、笔记、
自动化、连接器、来源凭据、贡献工作区）都从它派生，所以一处覆盖全链路生效。

没有环境变量时仍是 `~/.purrcat`，**安装版行为完全不变**。

## 与 Docker 的关系

便携版本身不依赖 Docker。默认本机 shell 执行；有 Docker 时仍可显式设
`PURRCAT_EXEC_BACKEND=docker` 用容器沙盒——纯可选增强。

## 自己构建

```powershell
uv run pyinstaller main.spec --noconfirm    # 先打 Python 后端
python scripts/build_portable.py            # 组装便携目录 + zip
```

脚本**不依赖 electron-builder**：那东西在 Windows 上会为了给 exe 写版本资源
去下载 winCodeSign，解压时要建符号链接，普通用户没权限而失败。
便携版本来不签名，所以直接组装 Electron 运行时 + app.asar + 后端即可。

如果本机 `~/.purrcat/embedding` 有语义检索模型，会一起打进包里；
没有则跳过，关键词检索仍可用。

设计与验收标准见
[../tests/specs/SPEC-036-portable-build.md](../tests/specs/SPEC-036-portable-build.md)。
