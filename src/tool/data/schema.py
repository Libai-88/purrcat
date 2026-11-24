DATA_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Data",
        "description": (
            "数据集工具：导入本机数据文件、检查数据结构、查询与聚合。"
            "CSV/TSV 的值一律按文本处理，要做数值比较或求和必须先把该字段显式解释为数字；"
            "每次查询会留下一条收据，记录读的是哪个版本、用的什么口径。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "import",
                        "list",
                        "inspect",
                        "query",
                        "chart",
                        "charts",
                        "receipts",
                    ],
                    "description": (
                        "import=导入数据文件；list=列出数据集；inspect=检查一个版本的结构与质量；"
                        "query=查询与聚合并留下收据；chart=画一张图并保存图表规格；"
                        "charts=列出已保存的图表；receipts=列出已有查询收据"
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "action=import 时填写，本机数据文件的绝对路径。",
                },
                "name": {
                    "type": "string",
                    "description": "action=import 时可选，数据集显示名；不填就用文件名。",
                },
                "kind": {
                    "type": "string",
                    "enum": ["dataset", "model"],
                    "description": "action=import 时可选，默认 dataset。",
                },
                "dataset_id": {
                    "type": "string",
                    "description": "数据集 id，先用 action=list 拿到。",
                },
                "asset_id": {
                    "type": "string",
                    "description": "要读的版本；不填就用最新版。",
                },
                "interpretations": {
                    "type": "object",
                    "description": (
                        '显式把某些字段解释为数字，形如 {"年龄": "number"}。'
                        "只有被点名的字段会转换，其余保持文本。"
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "filter": {
                    "type": "object",
                    "description": "过滤条件：{field, operator, value}。operator 取 contains/eq/gte/lte/missing/null/empty。",
                    "properties": {
                        "field": {"type": "string"},
                        "operator": {
                            "type": "string",
                            "enum": [
                                "contains",
                                "eq",
                                "gte",
                                "lte",
                                "missing",
                                "null",
                                "empty",
                            ],
                        },
                        "value": {"type": "string"},
                    },
                },
                "sort": {
                    "type": "object",
                    "description": "排序：{field, descending}。",
                    "properties": {
                        "field": {"type": "string"},
                        "descending": {"type": "boolean"},
                    },
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要展示的列，最多 32 列；不填就展示全部。",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回多少行，默认 50，最多 200。",
                },
                "category": {
                    "type": "string",
                    "description": "action=query 且做聚合时填写：按哪一列分组。",
                },
                "measure": {
                    "type": "string",
                    "description": "action=query 且求和时填写：对哪一列求和（该列须已解释为数字）。",
                },
                "aggregation": {
                    "type": "string",
                    "enum": ["count", "sum"],
                    "description": "action=query 的聚合方式，默认 count。",
                },
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "area", "scatter"],
                    "description": (
                        "action=chart 时填写图表类型。bar/line/area 按类目聚合，"
                        "scatter 逐行画点。数值列须已显式解释为数字。"
                    ),
                },
                "x": {
                    "type": "string",
                    "description": (
                        "action=chart 时填写横轴列。bar/line/area 是类目列，"
                        "scatter 是数值列。"
                    ),
                },
                "y": {
                    "type": "string",
                    "description": "action=chart 时填写纵轴列（必须是已解释为数字的数值列）。",
                },
                "question": {
                    "type": "string",
                    "description": "action=query 时填写：这次查询要回答什么。会记进收据。",
                },
                "unit": {
                    "type": "string",
                    "description": "action=query 时可选：这个数字是什么单位。收据里只是声明。",
                },
                "grain": {
                    "type": "string",
                    "description": "action=query 时可选：一行代表什么。",
                },
                "denominator": {
                    "type": "string",
                    "description": "action=query 时可选：分母是什么。",
                },
            },
            "required": ["action"],
        },
    },
}
