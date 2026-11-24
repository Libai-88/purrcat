NOTEBOOK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Notebook",
        "description": (
            "研究笔记工具：把一次研究写成由块组成的文档。"
            "块可以承载论文原文引文、数据查询收据、可计算的表格，以及引用前两者的结论。"
            "引文必须逐字出现在论文那一页，收据必须已经跑完——不然文档会拒收。"
            "每次保存产生一个不可变修订，带 expected_revision 提交，修订号对不上会报冲突。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "read", "save", "export"],
                    "description": "list=列出笔记；read=读一篇；save=提交一版；export=导出 Markdown",
                },
                "doc_id": {
                    "type": "string",
                    "description": "笔记 id；save 时用新 id 建新笔记，read/export 时指定。",
                },
                "revision": {
                    "type": "integer",
                    "description": "action=read 时可选，读某一版；不填读最新版。",
                },
                "title": {
                    "type": "string",
                    "description": "action=save 时可选，笔记标题。",
                },
                "blocks": {
                    "type": "array",
                    "description": (
                        "action=save 时必填，块列表。每个块形如 "
                        '{"kind": "...", "block_id": "...", "attrs": {...}}。'
                        "kind=text 的 attrs 是 {text}；"
                        "kind=heading 的 attrs 是 {text, level}；"
                        "kind=evidence 的 attrs 是 {paper_id, page, quote}；"
                        "kind=data 的 attrs 是 {receipt_id}；"
                        "kind=table 的 attrs 是 {label, sheet: {rows, columns, cells}}，"
                        "cells 里存公式源码（如 =SUM(A1:A3)）或字面值；"
                        "kind=finding 的 attrs 是 {claim, stance, limitations, evidence_ids}，"
                        "evidence_ids 指向同一文档里的 evidence 或 data 块。"
                    ),
                    "items": {"type": "object"},
                },
                "expected_revision": {
                    "type": "integer",
                    "description": (
                        "action=save 时可选：你读到的那一版修订号。"
                        "对不上会报冲突而不是覆盖——别把别人的改动冲掉。"
                    ),
                },
                "acceptance": {
                    "type": "string",
                    "enum": ["unverified", "needs_review", "accepted", "rejected"],
                    "description": "action=save 时可选，文档的可信度状态，默认 unverified。",
                },
            },
            "required": ["action"],
        },
    },
}
