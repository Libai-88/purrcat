# 研究笔记

把一次研究写成**由块组成的文档**：正文、论文原文引文、数据查询收据、可计算的表格，
以及引用前两者的结论。

这是科研全流程里把「查到的」和「算出的」收拢到一处的地方——前面几个能力各自成立，
到这里合成一份能交付、能回查、能被质疑的文档。

## 设计取舍

参考 Pero 的 Notebook，但按 PurrCat 的形态落地，三处不一样：

| | Pero | PurrCat |
| --- | --- | --- |
| 文档模型 | TS + Python **各实现一份** | **只有 Python 一份**，面板是投影 |
| 公式引擎 | TS（`fast-formula-parser`） | **Python**，面板与 Agent 调同一个接口 |
| 表格算值时机 | 编辑器内每次事务重算 | 后端算，面板按需取 |

理由是：一份规范树这条不变量，只有在模型只有一份实现时���真正成立。

## 块

| 块 | 承载什么 | 校验 |
| --- | --- | --- |
| `text` / `heading` | 正文、标题 | — |
| `evidence` | 论文原文引文 | **引文必须逐字出现在那一页**，否则拒收 |
| `data` | 一条查询收据 | 收据必须存在且 `status="completed"` |
| `table` | 可计算的表格 | 存公式源码，尺寸有上限 |
| `finding` | 结论 | **只能引用同一文档里的 `evidence` / `data` 块** |

三层身份分开记：块 id（文档内）、属主对象 id（论文 / 收据）、版本（commit / 收据本身）。

## 公式引擎

三条硬规则，都是为了不让「算错的数」看起来像「算对的数」：

1. **错误是值，而且会传播。** 引用到的格子里有 `#DIV/0!`，`SUM` 的结果也是 `#DIV/0!`——
   把错误跳过去会让「少了一个坏格子」的求和看起来像一个正常结果。
2. **循环引用产生独立的错误值。** 必须是 `#CIRC!` 这种能认出来的错误，不能是 0——
   0 会被当成一个有效测量值混进均值和回归。
3. **易变与外部调用一律拒绝。** `NOW`、`RAND`、`PY`、`WEBSERVICE`、DDE 链接和
   `'[其它工作簿]Sheet'!A1` 都返回 `#NAME?`，因为它们的结果不可复现。

单元格存的是**源码**（`=SUM(A1:A3)` 或 `3`），不是算出来的值。值是渲染时的投影。

## 修订

修订**不可变**，只追加。每次提交带 `expected_revision`，对不上就报冲突而不是覆盖。
每个修订记着自己的文档摘要（内容寻址），可以回答「这份记录后来被改过吗」。

## 导出

Markdown 是**有损的**，所以必须把损失说出来：

| 损失码 | 含义 |
| --- | --- |
| `formula-not-exported` | 表格里的公式不保留，只导出计算结果 |
| `table-values-only` | 表格的格式（合并、颜色、列宽）不在 Markdown 里 |
| `evidence-snapshot-not-exported` | 证据的原文快照不随文档导出 |
| `cell-unit-not-exported` | 单元格的单位标注不在 Markdown 里 |

原则：**不用有损格式悄悄替换一份完整的证据记录。**

## 工具

| action | 作用 | 必填参数 |
| --- | --- | --- |
| `list` | 列出笔记 | — |
| `read` | 读一篇 | `doc_id` |
| `save` | 提交一版 | `blocks` |
| `export` | 导出 Markdown | `doc_id` |

`save` 可带 `expected_revision`；对不上会报冲突而不是覆盖。

## 面板

内置插件 `builtin-notebook` 入驻中栏面板区：左边是笔记列表，右边是块列表。
正文与表格单元格可直接编辑，公式算值由后端算好后回填，证据块与收据块显示各自的来源与口径。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 文档模型与块校验 | `src/notebook/document.py` |
| 公式引擎 | `src/notebook/table.py` |
| 修订存储 | `src/notebook/store.py` |
| 导出与损失清单 | `src/notebook/export.py` |
| Agent 工具 | `src/tool/notebook/` |
| 面板接口 | `src/server/api/notebook_api.py` |
| 面板插件 | `ui/web-minimal/plugins/builtin/builtin-notebook/` |

设计与验收标准见 [../tests/specs/SPEC-030-research-notebook.md](../tests/specs/SPEC-030-research-notebook.md)。
