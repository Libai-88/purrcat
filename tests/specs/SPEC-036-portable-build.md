# SPEC-036：便携版（数据随目录走，不写注册表 / 不依赖 Docker）

## 背景

PurrCat 现在的分发方式是安装包（Windows NSIS / macOS dmg / Linux tar.gz），
数据固定在 `~/.purrcat`。这意味着：

- 换机器要手动搬数据；
- U 盘 / 共享盘上用不了；
- 用户无法把「整个应用 + 全部数据」作为一个目录拷走。

便携版要解决的是：**解压即用、数据跟着目录走、拷走整个目录就带走了全部状态**。
它不改现有安装版行为。

## 行为

1. **便携模式由程序目录旁的标记文件 `portable.flag` 决定**，不靠命令行参数——
   用户解压后不用记参数。
2. 便携模式下：
   - 数据根目录 = 程序目录旁的 `data/`（不是 `~/.purrcat`）；
   - Electron 的 `userData`（GPU flag 等）也在 `data/electron/` 内；
   - 后端通过 `PURRCAT_DIR` 环境变量拿到数据根，Python 侧所有路径从它派生。
3. **不写注册表、不装全局 CLI、不写 PATH**；API 端口照旧自动选空闲端口。
4. **安装版行为完全不变**：没有 `portable.flag` 时，数据仍在 `~/.purrcat`。
5. **与 Docker 解耦**：便携版本身不依赖 Docker；有 Docker 时仍可显式切容器后端。
6. 打包产物是一个可直接解压的目录（再压成 zip），内含 Electron、后端 sidecar、
   一个空的 `data/` 与 `portable.flag`。

## 验收标准

- [ ] AC-1：`PURRCAT_DIR` 环境变量能覆盖 Python 数据根，所有派生路径跟着变。
- [ ] AC-2：没有环境变量时仍用 `~/.purrcat`（安装版不受影响）。
- [ ] AC-3：Electron 检测到 `portable.flag` 时，把 `userData` 设到程序目录内。
- [ ] AC-4：Electron 便携模式给后端注入 `PURRCAT_DIR`。
- [ ] AC-5：打包脚本产出便携版目录/zip，含 `portable.flag` 与空 `data/`。
- [ ] AC-6：便携版数据不落在 `~/.purrcat`。
- [ ] AC-7：便携版启动不需要 Docker。

## 非目标

- 不做单文件 exe（PyInstaller onefile 启动慢且解包到临时目录，不适合数据就地存放）。
- 不自动迁移已安装版的数据到便携版（用户可自行拷贝 `~/.purrcat` 到 `data/`）。
- 不改现有 NSIS / dmg / tar.gz 安装包。
- 不做 macOS app 签名与公证。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_portable_config.py` | AC-1、AC-2 |
| L1 | `tests/l1/test_portable_layout.py` | AC-5、AC-6 |
| L3 | `tests/l3/test_portable_redline.py` | AC-3、AC-4、AC-7 |
| 实测 | 打包目录启动 | AC-5、AC-6、AC-7 |

## 风险与回滚

- 环境变量覆盖要在 config 模块导入时生效，必须在 Electron spawn 后端前注入。
- 相对路径一律转绝对，避免后端 `cwd` 变化导致数据目录漂移。
- 回滚：删掉打包脚本与环境变量分支；安装版行为不受影响。
