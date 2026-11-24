PAPER_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Paper",
        "description": (
            "论文库与证据核对工具。先用 import 把本机 PDF 导入论文库，之后可以按页读原文、"
            "把一段引文定位到具体页码与上下文、核对某条断言是否真有原文支撑。"
            "核对只依据已导入论文的文本，不做外部检索，也不判断科学结论本身对错。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["import", "list", "page", "locate", "verify"],
                    "description": (
                        "import=导入 PDF；list=列出论文库；page=读某页原文；"
                        "locate=在原文中定位一段引文；verify=核对断言是否有原文支撑"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "action=import 时填写，本机 PDF 的绝对路径。",
                },
                "paper_id": {
                    "type": "string",
                    "description": "论文 id，来自 action=list 的返回。",
                },
                "page": {
                    "type": "integer",
                    "description": "action=page 时填写，从 1 开始。",
                },
                "quote": {
                    "type": "string",
                    "description": (
                        "action=locate 必填，action=verify 可填：原文里那段引文的原话。"
                        "匹配容忍换行与空白差异。"
                    ),
                },
                "claim": {
                    "type": "string",
                    "description": (
                        "action=verify 时填写，要核对的那条断言。"
                        "例如「该方法在样本外验证中误差更低」。"
                    ),
                },
            },
            "required": ["action"],
        },
    },
}
