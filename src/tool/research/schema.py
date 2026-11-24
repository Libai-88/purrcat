RESEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Research",
        "description": (
            "研究记录工具：把一次研究的问题、结论与证据存成可回看的工件。"
            "证据只说明引文出现在原文的哪一页哪一段，不说明结论在科学上成立——"
            "每份记录都带一个可信度状态（默认 unverified），需要人工复核才能变成 accepted。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["save", "list", "read"],
                    "description": "save=保存研究记录；list=列出已有记录；read=读一条记录",
                },
                "record_id": {
                    "type": "string",
                    "description": "action=read 时填写，记录 id（list 的返回里有）。",
                },
                "title": {
                    "type": "string",
                    "description": "action=save 时可选，记录的标题；不填就用问题当标题。",
                },
                "question": {
                    "type": "string",
                    "description": "action=save 时必填：这次研究要回答的问题。",
                },
                "claims": {
                    "type": "array",
                    "description": "action=save 时必填：研究得出的结论。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "结论本身，写成人能读懂的一句话。",
                            },
                            "stance": {
                                "type": "string",
                                "enum": ["support", "counterevidence", "gap"],
                                "description": (
                                    "这条结论相对原文的关系：support=原文支持；"
                                    "counterevidence=原文是反证；gap=原文对此没有说法"
                                ),
                            },
                            "evidence": {
                                "type": "array",
                                "description": (
                                    "支撑这条结论的证据，至少一条。两种："
                                    "kind=paper 是论文原文引文（必须逐字出现在那一页）；"
                                    "kind=data 是一条数据查询收据的引用（用 receipt_id）。"
                                    "两种可以同时给，系统会自动把原文里的数字与收据里的数字字面比对。"
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "paper_id": {
                                            "type": "string",
                                            "description": "论文 id，先用 Paper 的 list 拿到。",
                                        },
                                        "page": {
                                            "type": "integer",
                                            "description": "页码，从 1 开始。",
                                        },
                                        "quote": {
                                            "type": "string",
                                            "description": (
                                                "原文里的原话，必须逐字出现在那一页，"
                                                "不能改写或转述，否则会被拒收。"
                                            ),
                                        },
                                    },
                                    "required": ["paper_id", "page", "quote"],
                                },
                            },
                        },
                        "required": ["text", "evidence"],
                    },
                },
                "papers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "action=save 时可选：本次研究涉及的论文 id 列表。",
                },
                "findings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "action=save 时可选：已经确认的发现。",
                },
                "gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "action=save 时可选：还没解决的问题。",
                },
                "acceptance": {
                    "type": "string",
                    "enum": ["unverified", "needs_review", "accepted", "rejected"],
                    "description": (
                        "记录的可信度状态。默认 unverified：只核对了引文位置，"
                        "没有人工复核结论。"
                    ),
                },
                "project_id": {
                    "type": "string",
                    "description": "action=save 时可选：归属的项目 id。",
                },
            },
            "required": ["action"],
        },
    },
}
