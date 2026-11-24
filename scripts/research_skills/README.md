# 科研技能目录（Research Skill Catalog）

把公开第三方仓库里的科研 `SKILL.md` 整理成一份索引，让 Agent 能检索到尚未安装的科研技能，
取用时按需安装。

**目录只是一份索引**：技能本体始终从上游仓库取，PurrCat 不复制、不改写上游内容。
每个上游仓库自带许可，目录只记录其许可状态。

## 为什么需要它

PurrCat 的 Skill 体系只认本地已安装的 `~/.purrcat/skills/<dir>/SKILL.md`。
学生做科研的真正卡点不是「没有工具」，而是「不知道该用哪个方法、参数怎么给、结果怎么验」——
而这些成体系的科研方法散落在几十个公开仓库里，用户得自己知道地址、找到 `SKILL.md`、手动放进目录。

目录把这件事变成：Agent 检索 → 命中目录条目 → `Fetch` 时自动按需安装。

## 用法

```bash
# 1) 采集：扫描上游仓库，提取 SKILL.md 的 name / description / 许可 / 文件清单
uv run python scripts/research_skills/collect.py --output build/collected.json

# 2) 生成目录：分类、去重、写出运行时 catalog
uv run python scripts/research_skills/publish.py \
  --input build/collected.json \
  --output src/utils/research_catalog.json
```

只采集个别仓库：

```bash
uv run python scripts/research_skills/collect.py --output build/collected.json \
  --repo Yuan1z0825/nature-skills
```

只重读原文、复用既有的来源路径（修了解析逻辑或要补描述时用，不消耗 API 配额）：

```bash
uv run python scripts/research_skills/collect.py \
  --refresh build/collected.json --output build/refreshed.json
```

## 采集方式

| 步骤 | 通道 | 说明 |
| --- | --- | --- |
| 文件树 + commit | `api.github.com/repos/{repo}/git/trees/HEAD?recursive=1` | 一次请求拿到整棵树与 commit |
| 文件内容 | `raw.githubusercontent.com/{repo}/{commit}/{path}` | 并发读取，无严格限流 |

git 协议（`git clone`）在本机网络下过慢且不稳，实测比上述方式慢一个数量级，故不采用。

未认证的 api.github.com 限额是 60 次/小时。采集器命中限额时会读取 `X-RateLimit-Reset`
等到重置再继续，不会在限额中途丢掉一半仓库；仓库文件树另按仓库缓存到
`.tree-cache/`，重跑不必再消耗配额。

采集**只读不执行**：仓库内容仅作为文本解析，绝不运行其中任何脚本。

## 目录文件

| 路径 | 作用 |
| --- | --- |
| `src/utils/research_catalog.json` | 发行版副本，由 `collect_all('src')` 自动打进安装包 |
| `~/.purrcat/research-catalog.json` | 用户覆盖副本，优先于发行版；可自行更新目录而不必重装 |

用户文件损坏或版本不匹配时自动回落到发行版副本；两者都不可用时功能整体降级为
「只认本地已装技能」，不报错。

## 分类

13 个科研分类，规则见 `src/utils/research_catalog.py` 的 `CATEGORIES` 与 `_CATEGORY_RULES`，
按关键词先命中先归类。发布脚本与运行时共用这一份定义，不会漂移。

目录条目保留上游的原始描述（多为英文），不做机器翻译——运行时使用的嵌入模型是多语言的，
中文提问能直接命中英文描述。实测「生存分析」与 `survival analysis` 的余弦相似度为 0.96。

分类只是检索结果的提示，不是排序依据——排序由语义嵌入决定，个别条目归类不准不影响可用性。
无法归入的条目记为「待分类」，不会硬塞进某一类。

## 排除

明显偏通用开发、与科研流程无关的技能放在 `sources.py` 的 `EXCLUDED_SKILL_NAMES`，
逐条人工确认后列入，不进目录。往里加条目时同样要先确认描述确实偏通用开发向。

## 检索与安装

- 检索走既有的 `Search(route="skill")`：本地已装技能与目录条目合并返回，未安装的带「未安装」标记。
- 取用走既有的 `Fetch(source="skill")`：本地没有就查目录，命中则按目录记录的 commit 下载安装后再加载。
- 安装按 commit 定位而非分支，保证同一技能重复安装得到相同内容。
- 目录条目自带该技能的文件清单，安装时只取这些文件，不下载整个上游仓库；清单缺失时才退回
  按文件树安装，再不行才下整个仓库归档。

## 许可

上游仓库各有各的许可，目录只记录状态。安装走的是 GitHub 原始文件下载，
技能作者与仓库的许可条款照旧适用。
