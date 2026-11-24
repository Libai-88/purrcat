# 科研连接器

检索外部科研数据源，把结果**拉进本机库**，并留下来源凭据。

## 为什么不是「再装几个技能」

技能目录里已经有 66 个能查外部数据源的技能（arxiv、pubmed、openalex、
semantic-scholar、uniprot、zenodo……）。它们**能搜到东西**，但搜到的东西落不到本机库：

- `arxiv` 技能让 Agent 把 PDF 存到项目目录下的 `papers/`；
- `openalex` 技能返回一堆元数据文本；
- 两者都**没有来源凭据**，不进论文库 / 数据集库，**不产生回执**。

于是「我搜到了一篇论文」和「这篇论文是我核过原文的证据」之间断了一截。
研究记录里的 `evidence` 要求引文逐字出现在**论文库那一页**，
但从技能里下载的 PDF 根本不在论文库里，所以它没法当证据用。

连接器补的就是这一截：

```
目录（能拉什么） → 拉取 → 归一 → 入库 → 来源凭据
```

## 目录里有什么

| 连接器 | 能拉什么 | 入库到 | 授权 |
| --- | --- | --- | --- |
| `arxiv` | 题录、论文原文 PDF | 论文库 | 匿名 |
| `openalex` | 题录（引文、机构、资助） | 论文库 | 匿名 |
| `crossref` | 题录（DOI、期刊卷期） | 论文库 | 匿名 |
| `pubmed` | 题录（摘要、MeSH 主题词） | 论文库 | 匿名 |
| `zenodo` | 题录、数据文件 | 数据集库 | 匿名 |
| `uniprot` | 蛋白质/基因条目 | 数据集库 | 匿名 |

**目录是能力声明，不是实现细节。** 未登记的源一律拒收——跟技能的词表同一个道理。

各源的真实接口形态都实地核对过（字段名以实际返回为准），详见
`src/connectors/pull.py` 里每个 `fetch_*` 函数。

## 来源凭据

拉下来的东西必须说得清从哪来的：

```json
{
  "provenance_id": "prov-19d5f02568c4",
  "connector_id": "arxiv",
  "request": {"query": "crispr gene editing", "count": 20},
  "retrieved_at": "2026-11-24T11:00:08+00:00",
  "content_sha256": "a0cd66ca…",
  "landed": "datasets",
  "landed_id": "ds-ab5c337aa036",
  "record_count": 20,
  "source_refs": ["http://arxiv.org/abs/1602.01876v1", "…"]
}
```

**凭据只说明出处，不说明可信。** 「这批数据是从 arXiv 拉的」推不出
「这批数据是对的」——后者是研究记录里 `acceptance` 的事。
凭据字典里**没有** acceptance / verification 字段，有测试盯着这件事。

凭据不可篡改：写了就不改；重新拉一次是**新的一条**，不是覆盖旧的。

## 怎么用

面板（`builtin-connectors`）：左边选连接器，填检索词，
「检索」给候选，「拉取入库」把结果变成数据集并留下来源凭据。

Agent 侧用 `Connectors` 工具：

```
Connectors(action="list")                                  # 看有哪些连接器
Connectors(action="search", connector_id="arxiv", query="crispr")
Connectors(action="pull",   connector_id="arxiv", query="crispr", count=20)
Connectors(action="provenance", provenance_id="prov-…")    # 查某次拉取的来源
```

## 拉进库之后

进库不是终点，是起点。落成数据集之后：

- 能对它跑查询，**留下查询收据**（带 `summary`，能和论文里的数字对字）；
- 能画图；
- 论文原文进论文库之后，能按页读原文、把引文定位到具体页码，
  引文也能逐字核对了——这样它才能当研究记录的证据。

## 失败会说是哪一类

| 类型 | 意思 |
| --- | --- |
| `unreachable` | 连不上源站 |
| `no_auth` | 这个源需要授权 |
| `rate_limited` | 被源站限流 |
| `no_results` | 连上了但没有匹配的结果 |
| `bad_shape` | 拉下来了但不是能入库的形态 |

## 礼貌与限额

所有出口都经本机后端（arXiv 更是**必须**如此——它不带 CORS 头）。
每个源按自己的规矩来：

- **arXiv**：每三秒不超过一次请求，同时只开一条连接（条款要求）。
- **PubMed**：每个请求都带 `tool` 与 `email`；匿名每秒 3 次。
- **OpenAlex**：带 `mailto` 只是礼貌，**不提高限额**；额度要靠 API key。
- **Crossref**：带 `mailto` 或在 UA 里留联系方式进礼貌池（限流从 1 次/秒到 3 次/秒）。
- **Zenodo**：检索接口每分钟 30 次；自定义 UA 是必须的。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 连接器目录（能力声明） | `src/connectors/catalog.py` |
| 拉取与归一 | `src/connectors/pull.py` |
| 入库 | `src/connectors/landing.py` |
| 来源凭据 | `src/connectors/provenance.py` |
| Agent 工具 | `src/tool/connectors/` |
| HTTP 接口 | `src/server/api/connectors_api.py` |
| 面板 | `ui/web-minimal/plugins/builtin/builtin-connectors/` |

设计与验收标准见
[../tests/specs/SPEC-033-research-connectors.md](../tests/specs/SPEC-033-research-connectors.md)。
