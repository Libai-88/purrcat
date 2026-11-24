# 论文库与证据核对

PurrCat 面向科研场景的内核能力：把 PDF 导入本机论文库，之后 Agent 可以**按页读原文**、
**把一段引文定位到具体页码**，并**核对自己的断言是否真有原文支撑**。

它解决的是科研写作里最不能含糊的一环——回答里的每句话都要能回指原文。

## 为什么是 native tool

论文能力做成一个原生工具（`Paper`），而不是走 MCP / Skill 的检索式路径：

- 面向学生的 Agent，论文工具应当**首屏就在**，而不是等 Agent 先 `Search` 再 `Fetch` 才浮现。
- 论文操作不需要常驻进程，打包后的桌面端同样可用。

工具本身只有一份 schema，用 `action` 区分五种操作，token 成本很低。

## 工具用法

| action | 作用 | 必填参数 |
| --- | --- | --- |
| `import` | 导入本机 PDF，解析分页原文 | `path`（绝对路径） |
| `list` | 列出论文库 | — |
| `page` | 读取某一页原文 | `paper_id`、`page`（从 1 开始） |
| `locate` | 在原文中定位一段引文 | `paper_id`、`quote` |
| `verify` | 核对断言是否有原文支撑 | `paper_id`、`claim`（`quote` 可选） |

典型流程：

```
Paper(action="import", path="/abs/path/paper.pdf")
Paper(action="list")                                  # 拿到 paper_id
Paper(action="page", paper_id="<id>", page=3)        # 读原文
Paper(action="locate", paper_id="<id>", quote="...") # 定位到页码
Paper(action="verify", paper_id="<id>", claim="...", quote="...")
```

## 导入

论文可以从两个入口进论文库：

- **面板**：点左上的「导入 PDF」，选文件或直接填路径。原生文件选择只在桌面端可用；
  独立浏览器里没有这个能力，插件会直接提示改填路径（不悬着不给反馈）。
- **Agent**：`Paper(action="import", path=...)`，路径需通过既有的文件权限检查。

两条入口走同一套导入逻辑：按页提取 PDF 文本层并落盘。

## 阅读面板

内置插件 `builtin-paper` 入驻中栏面板区（`slot.area: "panel"`）：

- 左侧列出论文库里的论文，右侧按页显示原文，可翻页。
- 在正文里选中一段，底部会出现引文预览，「发送给 Agent」按钮随之可用。
- 点击后经宿主动作总线的 `chat.sendBatch` 推送两个事件：
  - `paper-evidence`——结构化载荷 `{paper_id, title, page, page_count, quote}`，供 Agent 精确定位；
  - `user`——一句自然语言请求，让 Agent 去核对这段引文。

面板与 Agent 之间只有「面板推给 Agent」这一条通路——宿主不提供 Agent 反向读取面板状态的通道，
所以面板负责呈现与选段，核对由 Agent 通过 `Paper` 工具完成。

面板的数据来自后端接口（`/api/papers*`），与 Agent 侧读的是同一份论文库。

## 数据存放

论文库在本机数据目录下（`<data_root>/papers/`），每篇论文一个目录：

```
papers/
  index.json                 # 索引（加速用的缓存，坏了不影响逐篇读取）
  <paper_id>/
    meta.json                # id、标题、来源路径、页数、导入时间
    pages/0001.txt           # 逐页原文
```

`paper_id` 形如 `<标题短名>-<来源路径哈希前 8 位>`：同一文件重复导入落到同一处，论文 id 不变。

导入时按页提取 PDF 的**文本层**并落盘。之后读取某页原文只是文件读，不会重复解析 PDF。

## 匹配与核对

**引文定位**容忍排版差异：PDF 抽出的文本带换行与多余空白，用户引用的却常是连续一段。
匹配时把两边空白折叠后再比对，命中位置能映射回原文的字符区间。

**核对结论**有三档：

| 结论 | 含义 |
| --- | --- |
| `原文支持` | 引文在原文中原样出现，或断言的关键词高度重合 |
| `原文部分支持` | 只命中部分关键词 |
| `原文未提及` | 原文里找不到对应内容 |

引文找不到时，会给出最接近的候选页码，便于人工判断。

> 核对只依据已导入论文的文本，不做外部检索，也不引入模型推断。
> 它回答的是「原文里有没有这句话」，**不是**「这个结论在科学上对不对」。

## 边界

- **不做 OCR**：扫描件（没有文本层）导入时明确报错，不产出空论文——空页只会让后续核对给出误导结论。
- **不做外部查证**：不联网检索，不判断引文是否被误引、是否断章取义。
- **不做语义判定**：结论基于字面证据与规则，措辞完全不同的表述可能只判为部分支持。
- **不越界**：论文库只写自己的数据目录；导入路径先过既有文件权限检查，没有读取权限时拒绝导入。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 论文库存储与导入 | `src/papers/library.py` |
| 引文定位与断言匹配 | `src/papers/locate.py` |
| 核对结论 | `src/papers/verify.py` |
| Agent 工具 | `src/tool/paper/` |
| 面板接口 | `src/server/api/papers_api.py` |
| 阅读面板插件 | `ui/web-minimal/plugins/builtin/builtin-paper/` |
| 测试 PDF 生成 | `tests/support/pdf_factory.py` |

设计与验收标准见 [../tests/specs/SPEC-026-paper-evidence-chain.md](../tests/specs/SPEC-026-paper-evidence-chain.md)。
