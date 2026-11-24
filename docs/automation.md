# 科研自动化

到点让 Agent 跑一段指定的指示，并留下每次运行的回执。

## 和闹钟的区别

PurrCat 早就有 `Cron` 闹钟：能存「每天 08:30 提醒我」，也算了下一次触发时刻，
但**没有任何东西会去触发它**。闹钟只躺在 `cron.json` 里——那不是自动化，是备忘录。

自动化补上的是后半截：到点真的会让 Agent 跑起来。

```
Cron 闹钟      存下「明天 08:30 提醒我」        ← 没有人触发
自动化         到点推一段指示给 Agent + 留回执   ← 真的会跑
```

## 最重要的一条不变量

> **排上了 ≠ 跑完了，跑完了 ≠ 结论对。**

这两句话是分开的：

- **排上了 ≠ 跑完了**：回执刚写下时是 `queued`，Agent 真的开始跑才是 `running`，
  跑完才是 `succeeded` / `failed` / `cancelled`。
- **跑完了 ≠ 结论对**：回执里**没有** acceptance / verification 字段。
  「任务跑完了」和「它核对出来的数字可信」是两件事，各有各的词表
  （见 [papers.md](papers.md)）。

这一点在实现上踩过坑：最初只要 Agent 回到 idle 就算 `succeeded`，
结果一次模型鉴权失败（401）的运行被记成了「跑完了」。现在改成看这一轮
最后一条 assistant 消息——出现 `[Error.Fault] 交互断层` 就记 `failed`，
出现 `[Warn.Interrupt]` 就记 `cancelled`。

## 三条规矩

1. **先记后跑**：触发之前先落一条 `queued` 回执，再去推 Agent。
   推失败或进程崩了，这次也已经被记下来了。
2. **Agent 忙就不推**：忙的时候不排队、不堆积，下一次机会再说。
   这跟心跳那套「等空闲再注入」的既有做法一致（`src/agent/heartbeat.py`）。
3. **只报运行状态**：回执说「排上了 / 跑完了 / 挂了」，不说结论可不可信。

## 怎么用

面板（`builtin-automation`）：

- 左边新建：填名字、**到点让 Agent 做什么**、触发时刻、重复规则。
- 右边看详情与运行回执。
- 「手动跑一次」用来验证这条自动化确实能用。

Agent 侧用 `Automation` 工具：

```
Automation(action="create", title="查新论文",
           instruction="看看 arXiv 上有没有和「生存分析」相关的新论文，有的话把摘要记到研究笔记里。",
           trigger_time="08:30", repeat_rule="everyday")
```

指令要写清楚**能执行**的事。「检查一下」这种没法执行。

## 触发时刻

沿用 `Cron` 已有的时间规则，不另造一套日历：

| `repeat_rule` | 含义 |
| --- | --- |
| `none` | 只跑一次 |
| `everyday` | 每天 |
| `weekly_1` … `weekly_7` | 周一到周日 |

时刻是 `HH:MM`（24 小时制），按本地时间理解。

停机期间错过的时刻，醒来后只补跑一次，不堆一堆。

## 运行状态

| 状态 | 意思 |
| --- | --- |
| `queued` | 已排上，但还没跑 |
| `running` | 正在跑 |
| `succeeded` | 跑完了，中途没出错 |
| `failed` | 跑完了，但中途出错 |
| `cancelled` | 被取消了，没跑完 |

已经跑完的回执不会被后来的事件改写——跑完的事就是跑完了。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 定义与回执 | `src/automation/__init__.py` |
| 执行器（触发、等空闲、判成败） | `src/automation/runner.py` |
| Agent 工具 | `src/tool/automation/` |
| HTTP 接口 | `src/server/api/automation_api.py` |
| 面板 | `ui/web-minimal/plugins/builtin/builtin-automation/` |

设计与验收标准见
[../tests/specs/SPEC-032-research-automation.md](../tests/specs/SPEC-032-research-automation.md)。
