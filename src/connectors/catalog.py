"""科研连接器目录：能拉什么、从哪拉、要什么授权。

**目录是能力声明，不是实现细节。** 每个连接器说明三件事：

- 能拉什么形态的东西（论文元数据 / 论文原文 / 数据文件）
- 要不要授权（哪些源匿名可用，哪些要 API key）
- 拉回来的东西该怎么进本机库

登记在目录里的源才能被拉取——未登记的源一律拒收。
这条跟技能的词表是同一个道理：封闭词表之外不接受。

接口形态都实地核对过（字段名以各源的实际返回为准）：

- arXiv   ``https://export.arxiv.org/api/query`` → Atom XML
- OpenAlex ``https://api.openalex.org/works`` → JSON
- Crossref ``https://api.crossref.org/works`` → JSON
- PubMed  ``https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`` → JSON + XML
- Zenodo  ``https://zenodo.org/api/records`` → JSON
"""

from __future__ import annotations

# —— 能拉什么形态 ——

KIND_METADATA = "metadata"  # 元数据条目（题录、摘要、标识符）
KIND_PAPER = "paper"  # 论文原文（PDF）
KIND_DATASET = "dataset"  # 数据文件

KIND_VALUES = (KIND_METADATA, KIND_PAPER, KIND_DATASET)

# —— 要不要授权 ——

AUTH_NONE = "none"  # 匿名可用
AUTH_KEY = "api_key"  # 需要 API key（由本机保管，不进投影）

AUTH_VALUES = (AUTH_NONE, AUTH_KEY)

# —— 拉回来落到哪 ——

LAND_PAPERS = "papers"  # 进论文库
LAND_DATASETS = "datasets"  # 进数据集库

LAND_VALUES = (LAND_PAPERS, LAND_DATASETS)

# —— 失败分类 ——

FAIL_UNREACHABLE = "unreachable"  # 连不上
FAIL_NO_AUTH = "no_auth"  # 没授权
FAIL_RATE_LIMITED = "rate_limited"  # 源站限流
FAIL_NO_RESULTS = "no_results"  # 连上了但没结果
FAIL_BAD_SHAPE = "bad_shape"  # 拉下来了但不是能入库的形态

FAIL_VALUES = (
    FAIL_UNREACHABLE,
    FAIL_NO_AUTH,
    FAIL_RATE_LIMITED,
    FAIL_NO_RESULTS,
    FAIL_BAD_SHAPE,
)

# —— 目录 ——

CONNECTORS = (
    {
        "id": "arxiv",
        "name": "arXiv",
        "description": "物理、数学、计算机等学科的预印本。检索题录，也可以取原文 PDF。",
        "kinds": (KIND_METADATA, KIND_PAPER),
        "auth": AUTH_NONE,
        "lands": LAND_PAPERS,
        "rate_limit": "官方要求请求间隔不少于 3 秒，且同时只开一条连接。",
        "citation": "arXiv:1234.5678",
        "home": "https://arxiv.org",
    },
    {
        "id": "openalex",
        "name": "OpenAlex",
        "description": "开放的学术图谱：题录、引文、机构、开放获取状态与资助信息。",
        "kinds": (KIND_METADATA,),
        "auth": AUTH_NONE,
        "lands": LAND_PAPERS,
        "rate_limit": "匿名每 IP 每秒 10 次；免费 key 提到每秒 30 次并加额度。",
        "citation": "https://doi.org/10.xxxx/xxxxx",
        "home": "https://openalex.org",
    },
    {
        "id": "crossref",
        "name": "Crossref",
        "description": "出版商登记的 DOI 题录：标题、作者、期刊、卷期页。",
        "kinds": (KIND_METADATA,),
        "auth": AUTH_NONE,
        "lands": LAND_PAPERS,
        "rate_limit": "每秒 1 次；带 mailto 或 UA 里留联系方式进礼貌池。",
        "citation": "https://doi.org/10.xxxx/xxxxx",
        "home": "https://www.crossref.org",
    },
    {
        "id": "pubmed",
        "name": "PubMed",
        "description": "生物医学文献库。检索题录，含摘要与 MeSH 主题词。",
        "kinds": (KIND_METADATA,),
        "auth": AUTH_NONE,
        "lands": LAND_PAPERS,
        "rate_limit": "匿名每秒 3 次；带 API key 提到每秒 10 次。",
        "citation": "PMID:12345678",
        "home": "https://pubmed.ncbi.nlm.nih.gov",
    },
    {
        "id": "zenodo",
        "name": "Zenodo",
        "description": "开放数据仓库：数据集、软件与附件，可直接取文件。",
        "kinds": (KIND_METADATA, KIND_DATASET),
        "auth": AUTH_NONE,
        "lands": LAND_DATASETS,
        "rate_limit": "检索接口每分钟 30 次。",
        "citation": "https://doi.org/10.5281/zenodo.1234567",
        "home": "https://zenodo.org",
    },
    {
        "id": "uniprot",
        "name": "UniProt",
        "description": "蛋白质与基因的权威条目：推荐名、物种、基因名、序列与文献引用。",
        "kinds": (KIND_METADATA,),
        "auth": AUTH_NONE,
        "lands": LAND_DATASETS,
        "rate_limit": "未公布限额，实测无 429。",
        "citation": "https://www.uniprot.org/uniprotkb/P01308",
        "home": "https://www.uniprot.org",
    },
)

_BY_ID = {item["id"]: item for item in CONNECTORS}


class ConnectorError(Exception):
    """连接器用法不对，或目录里没有这个源。"""


class PullError(Exception):
    """拉取失败。``kind`` 说明是哪一类失败。"""

    def __init__(self, kind: str, message: str):
        if kind not in FAIL_VALUES:
            kind = FAIL_UNREACHABLE
        super().__init__(message)
        self.kind = kind
        self.message = message


def list_connectors() -> list[dict]:
    """目录里的全部连接器。"""
    return [dict(item) for item in CONNECTORS]


def get_connector(connector_id: str) -> dict:
    """取一个连接器；不在目录里就拒收。"""
    item = _BY_ID.get(str(connector_id or "").strip().lower())
    if item is None:
        raise ConnectorError(
            f"目录里没有这个连接器：{connector_id!r}；可用：{', '.join(sorted(_BY_ID))}"
        )
    return dict(item)


def connector_ids() -> tuple[str, ...]:
    """目录里的全部连接器 id。"""
    return tuple(sorted(_BY_ID))


def supports(connector_id: str, kind: str) -> bool:
    """这个连接器能不能拉这种形态的东西。"""
    item = get_connector(connector_id)
    return kind in item["kinds"]
