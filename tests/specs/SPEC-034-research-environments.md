# SPEC-034：科研环境（只读探测 + 能力声明 + 证据边界）

## 背景

PurrCat 已经有几处零散的环境信息：启动时的依赖检查（git / uv / node / 嵌入模型）、
`/api/system/env/*` 的本机 shell / Docker 探测、以及执行后端选择。
它们分散在不同地方、说法不一，也没有一套统一的「这个环境现在能干什么」的说法。

Pero 的环境模型有一条关键不变量（ADR 0029/0030）：

- **元数据观察既不代表可导入，也不代表执行授权。**
- **准备的授权与科学计算的批准是两件事。**
- 就绪度是三态（Ready / NotReady / Unknown），不是一个布尔值。

PurrCat 不需要照搬它的软件准备 / 计算绑定整套机制，
但**探测结果的表达边界**值得照搬：观察到什么就说什么，不把「装了 git」
说成「能复现这篇论文」。

## 行为

1. **环境探测是只读的**：看得到有哪些工具、版本、执行后端，不改系统、不装东西。
2. **就绪度三态**：`ready` / `missing` / `unknown`。拿不到信息就说 unknown，
   不猜一个 ready 出来。
3. **观察 ≠ 授权 ≠ 验证**：一条探测记录只说明「观察到这个软件在这个版本」，
   不说明「它能跑这个实验」，更不说明「用它算出来的结果是对的」。
4. **能力声明是封闭词表**：`process` / `batch` / `http` / `terminal` 之类，
   每种能力说清它能做什么、不能推出什么。
5. **探测结果带来源与时间**：什么时候、用什么方式观察到的。
6. **复用既有能力**：依赖检查走 `src/utils/dependency_check.py` 的判定，
   shell / Docker 走 `/api/system` 的探测，不另写一套。

## 验收标准

- [ ] AC-1：探测是只读的，不改系统状态。
- [ ] AC-2：就绪度是三态，信息不足时是 unknown。
- [ ] AC-3：探测记录里没有 acceptance / verification。
- [ ] AC-4：能力声明是封闭词表，且每项说明「不能推出什么」。
- [ ] AC-5：观察记录带时刻与观察方式。
- [ ] AC-6：Agent 侧能列环境、看某一项、查能力。

## 非目标

- 不做软件安装 / 环境准备（那会改系统，且需要用户明确授权）。
- 不做计算绑定与执行授权（本次只读）。
- 不做多机调度、容器编排、HPC。
- 不改既有的依赖检查与 `/api/system` 行为。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_environments.py` | AC-2、AC-3、AC-4、AC-5 |
| L1 | `tests/l1/test_environments_api.py` | AC-1、AC-6 |
| L3 | `tests/l3/test_environments_catalog.py` | AC-4（能力词表冻结） |
| 浏览器实测 | `ui/web-minimal/plugins/builtin/builtin-environments/` | AC-2、AC-4 |

## 风险与回滚

- 探测会调用本机 `shutil.which` 和 `subprocess` 的版本查询；超时要短，不能卡住界面。
- 回滚：删掉 `src/environments/`、`src/tool/environments/`、
  `src/server/api/environments_api.py` 与对应面板，既有依赖检查与 `/api/system` 不动。
