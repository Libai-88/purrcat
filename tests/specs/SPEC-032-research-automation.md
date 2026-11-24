# SPEC-032：科研自动化（定时 → Agent 跑，带运行回执）

## 背景

PurrCat 现在有 `Cron` 闹钟：能存「每天 08:30 提醒我」，也算了 `next_run_time`，
但**没有任何东西会去触发它**——闹钟只躺在 `cron.json` 里。这不是自动化，
是备忘录。

Pero 的自动化是一条完整的链路：触发器 → 冻结输入 → 调用 Agent → 留下回执。
它最要紧的一条不变量写在 `apps/automations/README.md` 里：

> A queued receipt is not success; completion is not scientific validation.

也就是说「已排队」不等于「跑成功」，「跑完了」也不等于「结论对」。
这两句话对科研场景尤其要紧：定时任务跑完不代表它核对出来的数字是对的。

PurrCat 已经有跑 Agent 的全部零件——`agent_force_push` 能往会话里推消息，
`AgentManager` 知道 Agent 什么时候空闲。缺的只是把这条链接起来，并把回执记下来。

## 行为

1. **自动化 = 触发时刻 + 一段指示 + 一条运行历史**。定义存 `automations.json`，
   每次触发生成一条回执，回执只追加不改写。
2. **触发时刻**沿用 `Cron` 已有的时间规则（`HH:MM` + 重复规则），
   不另造一套日历。
3. **自动化在 Agent 空闲时才触发**。忙的时候不排队、不堆积，下一次机会再说——
   跟心跳那套「等空闲再注入」的既有做法一致。
4. **回执记录这次实际发生了什么**：什么时候排的、什么时候真的开始、
   什么时候结束、结束成什么样。
5. **回执区分「排上了」和「跑完了」**。`queued` 不是 `succeeded`。
6. **回执不判断结论对错**。回执里没有 acceptance / verification——
   「任务跑完了」和「它核对的结果可信」是两件事，各有各的词表。
7. **能手动触发一次**，用于验证这条自动化确实能用。
8. **关掉自动化只停未来的触发**，已经跑完的回执留着。

## 验收标准

- [ ] AC-1：定义能增删查改，每条有稳定 id。
- [ ] AC-2：到点且 Agent 空闲时会真的触发一次，并留下回执。
- [ ] AC-3：Agent 忙时不触发，回执不产生；Agent 空闲后的下一次机会会触发。
- [ ] AC-4：回执区分 queued / running / succeeded / failed / cancelled。
- [ ] AC-5：`queued` 不等于 `succeeded`——排上但没跑完的，回执说 queued。
- [ ] AC-6：回执里没有 acceptance / verification 字段。
- [ ] AC-7：手动触发会留下回执。
- [ ] AC-8：停用后不再触发，触发时刻重算。

## 非目标

- 不做事件触发（文件变更 / git push）：没有可信的本地事件源，先不做。
- 不做分布式调度与多机协调。
- 不给自动化配权限审批：它只在本机跑，用的是本机已有的 Agent 身份。
- 不改 `Cron` 闹钟的既有行为与工具契约——自动化是另一套，另立文件。
- 不判断自动化跑出来的结论是否可信。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_automation.py` | AC-1、AC-4、AC-5、AC-6、AC-8 |
| L1 | `tests/l1/test_automation_api.py` | AC-2、AC-3、AC-7 |
| 浏览器实测 | `ui/web-minimal/plugins/builtin/builtin-automation/` | AC-1、AC-7 |

## 风险与回滚

- 定时触发会真的调用模型，产生 token 消耗；默认关闭，需要显式启用。
- 与心跳线程都会往 Agent 里推消息：两者都等 Agent 空闲，不会并发注入。
- 回执只追加，文件会慢慢变大；回执上限见实现。
- 回滚：删掉 `src/automation/`、`src/tool/automation/`、`src/server/api/automation_api.py`
  与对应面板，`cron.json` 与既有工具不受影响。
