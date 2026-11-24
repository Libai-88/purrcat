# 科研环境

只读探测本机有什么工具、什么版本、走什么执行后端，以及有哪些执行能力。

## 边界：观察 ≠ 授权 ≠ 验证

这是从 Pero 的环境模型里借来的一条不变量：

- **观察 ≠ 可导入**：看到装了 Python，不代表能把某篇论文的环境导进来；
- **观察 ≠ 执行授权**：看到装了 git，不代表被允许用它改什么；
- **跑完了 ≠ 结果对**：用它算出来的数字是否可信，是研究记录里 acceptance 的事。

所以探测记录里**没有** acceptance / verification 字段，
就绪度是三态（ready / missing / unknown）而不是布尔值——
拿不到可靠信息就说 unknown，不猜一个 ready 出来。

## 内置、开箱即用

环境探测是**内置工具 + builtin 面板**，随应用分发，不需要用户单独安装。

- Agent 侧：`Environments` 工具（`list` / `observe` / `capabilities`）
- 面板：`builtin-environments`

## 探测什么

Python、Git、uv、Node.js、Docker，加上当前执行后端（local / docker）。

复用 PurrCat 既有的判定逻辑，不另造一套：

- PATH 用 `get_enriched_env()` 合并注册表最新值——
  Windows 上用户刚装完 uv/node 没重启时，老进程的 PATH 还是旧的，
  直接 `which` 会误报「缺失」；
- 执行后端用 `resolve_backend_name()`，跟 `/api/system` 一致。

探测只读：只用 `shutil.which` 与短超时的 `--version`，不改系统、不装东西。

## 能力声明

每种能力都说清「能做什么」和**「不能推出什么」**——后者才是边界：

| 能力 | 能 | 不能推出 |
| --- | --- | --- |
| `process` 受管进程 | 启动固定入口，跟踪身份与退出 | 能跟踪整棵进程树；有 shell 就有受管进程 |
| `batch` 批作业 | 提交作业，读状态与产物 | 提交回执=节点已分配；外部作业 ID=本机任务 ID |
| `http` 服务会话 | 访问明确端点，保持会话 | 能连数据库=可任意读写 |
| `terminal` 终端 | 观察输出并输入 | 有屏幕=有受管进程；关终端=停掉远端作业 |

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 能力 / 工具目录 | `src/environments/catalog.py` |
| 只读探测 | `src/environments/observer.py` |
| Agent 工具 | `src/tool/environments/` |
| HTTP 接口 | `src/server/api/environments_api.py` |
| 面板 | `ui/web-minimal/plugins/builtin/builtin-environments/` |

设计与验收标准见
[../tests/specs/SPEC-034-research-environments.md](../tests/specs/SPEC-034-research-environments.md)。
