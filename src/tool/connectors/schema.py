"""Connectors 工具的 schema：把外部文献与数据拉进本机库。"""

from __future__ import annotations

CONNECTORS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Connectors",
        "description": (
            "连接器工具：检索外部科研数据源（arXiv、OpenAlex、Crossref、PubMed、"
            "Zenodo、UniProt），并把结果拉进本机库、留下来源凭据。"
            "检索只给候选；拉取（pull）才进库，进了库才能被研究记录当证据引。"
            "来源凭据只说明出处，不说明结论可信。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "search", "pull", "paper", "provenance"],
                    "description": (
                        "list=看有哪些连接器；search=只检索（给候选）；"
                        "pull=拉取并入库（留来源凭据）；"
                        "paper=把论文原文 PDF 拉进论文库；provenance=查某次拉取的来源凭据"
                    ),
                },
                "connector_id": {
                    "type": "string",
                    "enum": [
                        "arxiv",
                        "openalex",
                        "crossref",
                        "pubmed",
                        "zenodo",
                        "uniprot",
                    ],
                    "description": "连接器 id；action=search/pull 时指定。",
                },
                "query": {
                    "type": "string",
                    "description": "检索词；action=search/pull 时必填。",
                },
                "count": {
                    "type": "integer",
                    "description": "拉多少条，默认 10，最多 100。",
                },
                "pdf_url": {
                    "type": "string",
                    "description": (
                        "论文原文 PDF 链接；action=paper 时必填。"
                        "一般先 search 拿到 pdf_url，再用这个动作入库。"
                    ),
                },
                "provenance_id": {
                    "type": "string",
                    "description": "来源凭据 id；action=provenance 时指定。",
                },
            },
            "required": ["action"],
        },
    },
}

__all__ = ["CONNECTORS_TOOL_SCHEMA"]
