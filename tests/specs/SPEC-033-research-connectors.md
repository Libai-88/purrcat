# SPEC-033：科研连接器（把外部文献/数据拉进本机库，带来源凭据）

## 背景

科研技能目录里已经有 66 个能查外部数据源的技能（arxiv、pubmed、openalex、
semantic-scholar、uniprot、zenodo……）。它们**能搜到东西**，但搜到的东西落不到
本机库里：

- `arxiv` 技能让 Agent 把 PDF 存到项目目录下的 `papers/`；
- `openalex` 技能返回一堆元数据文本；
- 两者都**没有来源凭据**，不进论文库 / 数据集库，**不产生回执**。

于是「我搜到了一篇论文」和「这篇论文是我核过原文的证据」之间断了一截。
研究记录里的 `evidence` 要求引文逐字出现在**论文库那一页**，
但从技能里下载的 PDF 根本不在论文库里，所以它没法当证据用。

Pero 的连接器解决的正是这一层：`packages/connectors/src/connectors/model.mjs`
里写得很清楚——

> A connector is a directory entry, an authorization, a runtime and a tool policy:
> four facts written by four different authorities.

而它最要紧的一条不变量在 `apps/automations/README.md`：

> A queued receipt is not success; completion is not scientific validation.

## 行为

1. **连接器目录**：一份封闭词表里的数据源，每个说明它能拉什么、
   要不要授权、返回什么形态的结果。目录是**能力声明**，不是实现细节。
2. **拉取 = 落地 + 留凭据**。从连接器取回的东西要真的进本机库
   （论文进论文库、数据进数据集库），并留下**来源凭据**：从哪来、
   什么时候取的、原始请求是什么、内容的哈希是多少。
3. **来源凭据不可篡改、不可省略**。取回来的东西说不清从哪来的，就不进库。
4. **凭据只说明出处，不说明可信**。跟研究记录一样：来源可信度与
   学术可信度是两件事，凭据里**没有** acceptance / verification。
5. **授权信息不进投影**。连接器的凭据（API key 之类）由本机保管，
   不出现在面板、不出现在回执、不进 Agent 的上下文。
6. **失败要说清是哪一类**：连不上、没授权、源站限流、返回了但没有结果、
   拉下来了但不是能入库的形态。
7. **连接器不替用户做判断**：拉回来的是候选，不是结论。

## 验收标准

- [ ] AC-1：目录是封闭词表；未登记的数据源不能被拉取。
- [ ] AC-2：拉取成功后，东西真的进了论文库 / 数据集库。
- [ ] AC-3：入库的东西带来源凭据（来源、时刻、请求、哈希）。
- [ ] AC-4：来源凭据里没有 acceptance / verification 字段。
- [ ] AC-5：授权信息不出现在回执与面板投影里。
- [ ] AC-6：失败分得清：连不上 / 没授权 / 限流 / 没结果 / 形态不对。
- [ ] AC-7：限流与网络抖动按 `http_fetch` 的既有策略重试与等待。
- [ ] AC-8：Agent 侧能列目录、拉取、看某次拉取的凭据。

## 非目标

- 不做 OAuth 授权流（本轮只支持匿名可用的源 + 已配置好的 API key）。
- 不做增量同步与定时拉取（定时跑交给 SPEC-032 的自动化）。
- 不做网页抓取式的通用爬取；每个源都是一个明确声明的接口。
- 不改技能目录里既有技能的行为；连接器是**另一条路**，不是替换它们。
- 不替用户判断论文质量、结论对错。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_connectors.py` | AC-1、AC-4、AC-5、AC-6 |
| L1 | `tests/l1/test_connectors_api.py` | AC-2、AC-3、AC-6、AC-8 |
| L3 | `tests/l3/test_connectors_catalog.py` | AC-1（目录与词表冻结） |
| 浏览器实测 | `ui/web-minimal/plugins/builtin/builtin-connectors/` | AC-2、AC-3、AC-6 |

## 风险与回滚

- 拉取会真的联网；测试用假 HTTP 响应，不打真实站点。
- 入库会占磁盘；沿用数据集库既有的导入上限。
- 回滚：删掉 `src/connectors/`、`src/tool/connectors/`、
  `src/server/api/connectors_api.py` 与对应面板；
  已入库的东西留在库里，与既有功能不冲突。
