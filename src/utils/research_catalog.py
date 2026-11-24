"""科研技能目录：公开第三方科研 Skill 的索引来源。

目录条目只描述「哪个仓库的哪个 commit 里的哪个技能」，技能本体始终从上游取，
PurrCat 不复制、不改写上游内容。每个上游仓库自带许可，目录只记录其许可状态。
"""

import json
import os
import threading

from src.utils.config import (
    RESEARCH_CATALOG_PATH,
    RESEARCH_CATALOG_SHIPPED_PATH,
)

SCHEMA_VERSION = 1

CATEGORIES = {
    "research-design": "选题与研究设计",
    "literature": "文献检索与管理",
    "data": "数据获取与处理",
    "statistics": "统计检验与分析",
    "ai": "机器学习与 AI 实验",
    "scientific-computing": "科学计算与仿真",
    "laboratory": "实验与实验室",
    "visualization": "科研绘图与可视化",
    "writing": "论文写作与排版",
    "review": "审稿投稿与返修",
    "presentation": "学术汇报与幻灯",
    "workflow": "科研流程与自动化",
    "documents": "科研文档处理",
    "unclassified": "待分类",
}

# 顺序即优先级：先命中先归类，越具体的领域越靠前。
_CATEGORY_RULES = (
    (
        "literature",
        (
            "literature review",
            "literature search",
            "literature gap",
            "literature mapping",
            "citation",
            "arxiv",
            "pubmed",
            "biorxiv",
            "europe pmc",
            "crossref",
            "dblp",
            "openalex",
            "semantic scholar",
            "scholarly",
            "bibliograph",
            "bibliometric",
            "h-index",
            "impact factor",
            "peer-reviewed",
            "research paper",
            "open access",
            "full text",
            "prior art",
            "reference manager",
            "zotero",
            "paper search",
            "find papers",
            "文献",
            "引文",
            "参考文献",
            "综述",
            "检索",
            "open access paper",
            "research database",
            "metadata api",
        ),
    ),
    (
        "review",
        (
            "peer review",
            "reviewer",
            "rebuttal",
            "revision",
            "response to reviewers",
            "prior art",
            "patent databases",
            "审稿",
            "返修",
            "投稿",
            "referee",
            "response letter",
            "point-by-point",
        ),
    ),
    (
        "writing",
        (
            "paper writing",
            "academic writing",
            "academic tone",
            "manuscript",
            "thesis",
            "dissertation",
            "conference paper",
            "latex",
            "bibtex",
            "journal",
            "abstract",
            "introduction writing",
            "discussion writing",
            "paper screening",
            "proofread",
            "proofread",
            "论文",
            "写作",
            "排版",
            "润色",
            "referee response",
        ),
    ),
    (
        "presentation",
        (
            "presentation",
            "slide",
            "pptx",
            "poster",
            "keynote",
            "group meeting",
            "lab meeting",
            "academic talk",
            "汇报",
            "幻灯",
            "演示文稿",
            "海报",
            "组会",
        ),
    ),
    (
        "statistics",
        (
            "statistical",
            "hypothesis test",
            "regression",
            "anova",
            "survival analysis",
            "kaplan",
            "bayesian",
            "confidence interval",
            "p-value",
            "effect size",
            "bootstrap",
            "causal inference",
            "econometric",
            "identif",
            "panel data",
            "instrumental variable",
            "difference-in-difference",
            "检验",
            "统计",
            "假设检验",
            "回归",
            "生存分析",
            "贝叶斯",
            "显著性",
            "因果推断",
            "structural equation",
            "latent variable",
            "topic model",
            "sem model",
        ),
    ),
    (
        "ai",
        (
            "machine learning",
            "deep learning",
            "neural network",
            "model training",
            "fine-tun",
            "shap",
            "transformer",
            "language model",
            "llm",
            "gpt",
            "rag",
            "agent framework",
            "prompt engineering",
            "model benchmark",
            "ai scientist",
            "机器学习",
            "深度学习",
            "神经网络",
            "模型训练",
            "大模型",
            "reinforcement learning",
            "ablation",
            "rl environment",
            "model evaluation",
        ),
    ),
    (
        "scientific-computing",
        (
            "simulation",
            "solver",
            "numerical",
            "monte carlo",
            "finite element",
            "molecular dynamics",
            "density functional",
            "quantum",
            "lattice dynamics",
            "spectroscop",
            "signal processing",
            "radar",
            "antenna",
            "electromagnetic",
            "crystal",
            "semiconductor",
            "bioinformatics",
            "genom",
            "proteom",
            "rna",
            "dna",
            "sequencing",
            "phylogen",
            "alignment",
            "cheminformatics",
            "molecule",
            "protein",
            "peptide",
            "metabolic",
            "reaction network",
            "enzyme",
            "catalysis",
            "drug",
            "compound",
            "single-cell",
            "omics",
            "variant",
            "seismic",
            "climate",
            "ecosystem",
            "ecolog",
            "evolutionary",
            "biodiversity",
            "geoscience",
            "科学计算",
            "模拟",
            "求解",
            "分子动力学",
            "数值",
            "基因组",
            "蛋白",
            "代谢",
            "gene ontology",
            "blast",
            "species distribution",
            "maxent",
            "bioactivity",
            "chemogenomic",
        ),
    ),
    (
        "visualization",
        (
            "plot",
            "chart",
            "figure",
            "visualiz",
            "matplotlib",
            "seaborn",
            "diagram",
            "excalidraw",
            "绘图",
            "可视化",
            "图表",
            "配图",
            "示意图",
        ),
    ),
    (
        "data",
        (
            "dataset",
            "data cleaning",
            "data wrangling",
            "data audit",
            "data deposit",
            "data sharing",
            "data repository",
            "data source",
            "data explorer",
            "data processing",
            "data fetcher",
            "open data",
            "survey data",
            "microdata",
            "pandas",
            "spreadsheet",
            "数据库",
            "数据清洗",
            "数据集",
            "数据处理",
            "数据获取",
            "ocr",
            "text cleanup",
            "open library",
            "data catalog",
            "dataset api",
            "dataset repository",
        ),
    ),
    (
        "laboratory",
        (
            "laboratory",
            "protocol",
            "assay",
            "wet lab",
            "sample preparation",
            "experiment log",
            "specimen",
            "reagent",
            "clinical trial",
            "clinical",
            "patient",
            "medical",
            "pharmacolog",
            "toxicolog",
            "epidemiolog",
            "健康",
            "临床",
            "实验",
            "实验记录",
            "实验方案",
            "试剂",
        ),
    ),
    (
        "workflow",
        (
            "workflow",
            "automation",
            "pipeline",
            "orchestrat",
            "reproduc",
            "research plan",
            "end-to-end",
            "流程",
            "自动化",
            "工作流",
            "复现",
        ),
    ),
    (
        "research-design",
        (
            "research question",
            "study design",
            "experimental design",
            "research proposal",
            "research design",
            "hypothesis",
            "qualitative",
            "ethnography",
            "action research",
            "grounded theory",
            "concept map",
            "ideation",
            "research idea",
            "topic selection",
            "preregistration",
            "replication",
            "sampling",
            "conjoint",
            "factorial design",
            "design of experiment",
            "选题",
            "研究设计",
            "研究方案",
            "假设",
            "质性研究",
            "survey design",
            "survey instrument",
            "scale design",
            "questionnaire",
        ),
    ),
    (
        "documents",
        (
            "docx",
            "word document",
            "latex compile",
            "document conversion",
            "pdf parsing",
            "document parsing",
            "文档",
            "转换",
            "解析",
        ),
    ),
)

_catalog_cache = {}
_catalog_lock = threading.Lock()


def classify(name: str, description: str) -> str:
    """按关键词把一个技能归到科研分类；无法判定时归入 unclassified。"""
    text = f"{name} {description}".lower()
    for category, keywords in _CATEGORY_RULES:
        for keyword in keywords:
            if keyword in text:
                return category
    return "unclassified"


def category_label(category: str) -> str:
    """分类的中文名；未知分类回落到待分类。"""
    return CATEGORIES.get(category, CATEGORIES["unclassified"])


def _read_catalog_file(path: str):
    """读取单个目录文件；文件缺失或损坏时返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    if not isinstance(data.get("skills"), list):
        return None
    return data


def load_catalog() -> dict:
    """读取科研技能目录；用户覆盖优先于发行版副本，任何异常都降级为空目录。

    结果按文件 mtime 缓存，目录文件不变时不重复解析。
    """
    with _catalog_lock:
        candidates = [
            p for p in (RESEARCH_CATALOG_PATH, RESEARCH_CATALOG_SHIPPED_PATH) if p
        ]
        for path in candidates:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            cached = _catalog_cache.get(path)
            if cached and cached[0] == mtime:
                return cached[1]
            data = _read_catalog_file(path)
            if data is None:
                continue
            _catalog_cache[path] = (mtime, data)
            return data
        return {}


def reset_catalog_cache() -> None:
    """清空目录缓存；目录文件被就地替换后需要它才能读到新内容。"""
    with _catalog_lock:
        _catalog_cache.clear()


def catalog_signature() -> str:
    """目录内容签名，用于判断检索索引是否过期。"""
    catalog = load_catalog()
    generated_at = str(catalog.get("generated_at") or "")
    return f"{generated_at}:{len(catalog.get('skills', []))}"


def catalog_entries() -> list:
    """目录中的全部技能条目；每条至少包含 name、description、source。"""
    entries = []
    for raw in load_catalog().get("skills", []):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        source = raw.get("source")
        if not name or not isinstance(source, dict):
            continue
        repository = str(source.get("repository") or "").strip()
        commit = str(source.get("commit") or "").strip()
        path = str(source.get("path") or "").strip()
        if not repository or not commit or not path:
            continue
        category = str(raw.get("category") or "unclassified")
        files = raw.get("files")
        entries.append(
            {
                "name": name,
                "description": str(raw.get("description") or ""),
                "category": category,
                "category_zh": category_label(category),
                "license": str(raw.get("license") or ""),
                "files": (
                    [str(item) for item in files if isinstance(item, str)]
                    if isinstance(files, list)
                    else []
                ),
                "source": {
                    "repository": repository,
                    "commit": commit,
                    "path": path,
                    "url": str(source.get("url") or ""),
                },
            }
        )
    return entries


def find_entry(name: str):
    """按技能名或目录 id 查找条目，忽略大小写；找不到返回 None。"""
    target = str(name or "").strip().lower()
    if not target:
        return None
    for entry in catalog_entries():
        if entry["name"].lower() == target:
            return entry
    for entry in catalog_entries():
        source_path = entry["source"]["path"]
        if source_path.rsplit("/", 1)[-1].lower() == target:
            return entry
    return None


def entry_install_url(entry: dict) -> str:
    """目录条目对应的安装链接；ref 位置放 commit，使安装可复现。"""
    source = entry.get("source") or {}
    repository = source.get("repository", "")
    commit = source.get("commit", "")
    path = source.get("path", "")
    if not repository or not commit or not path:
        return ""
    return f"https://github.com/{repository}/tree/{commit}/{path}"
