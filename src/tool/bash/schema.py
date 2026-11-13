BASH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Bash",
        "description": "在本机工作目录执行 Shell 命令（默认本地执行，不是容器）。Windows 上优先使用 Git Bash，没有 Git Bash 时使用 PowerShell，此时请写 PowerShell 语法；macOS/Linux 使用 bash。工作目录为 agent_vm，每次调用都从该目录开始，`cd` 不会跨调用保留。你可以使用此工具进行环境配置、代码运行、文件操作等。注意：每次使用 cat >> 写入文件时，严禁超过 50 行代码，写完必须结束当前调用，在下一次回复中继续追加。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 Shell 命令（支持连串命令和多行文本，请注意正确的引号转义）",
                },
                "timeout": {
                    "type": "integer",
                    "description": "命令执行的超时时间（秒），如果不确定请不要传，默认 30 秒；长耗时任务（测试、构建、网络下载）请显式传入更大值或用 nohup 放后台",
                },
            },
            "required": ["command"],
        },
    },
}
