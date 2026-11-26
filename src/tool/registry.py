"""工具注册表：名称、Schema、函数名、能力域与执行位置的唯一事实来源。

此前这三件事分散在 ``src/tool/__init__.py`` 的 Schema 列表、``utils/route.py`` 的
``TOOL_FUNC_MAP`` 与 ``PROCESS_ISOLATED_TOOLS``：新增一个工具要同时改三处，漏一处
就会出现「模型看得到但调不通」或「该隔离的没隔离」。这里登记一次，其余全部派生。

Schema 用惰性属性取用：工具包会反向依赖 ``utils.route``，若在模块加载期就 import
它们会形成 registry → 子包 → route → registry 的环。元数据先就位，Schema 等到
真正取用时再解析。

能力域用于会话级能力快照（``src/agent/capabilities.py``）：core 是基座能力，
research 是科研线扩展。会话创建时固化，不在轮次之间动态切换——工具定义位于请求
前缀，动态增删会击穿 KV Cache。

``timeout_ms`` 目前只登记声明式上限，执行层的实际超时仍由
``utils/execution.py`` 的 ``asyncio.wait_for`` 统一兜底，尚无消费者。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

CORE = "core"
RESEARCH = "research"

ALL_CAPABILITIES = (CORE, RESEARCH)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    module: str
    schema_attr: str
    func: str
    capability: str = CORE
    isolated: bool = False
    timeout_ms: int | None = None

    @property
    def schema(self) -> dict:
        module = importlib.import_module(self.module)
        return getattr(module, self.schema_attr)


def _spec(
    name: str,
    module: str,
    schema_attr: str,
    func: str,
    capability: str = CORE,
    isolated: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        module=f"src.tool.{module}",
        schema_attr=schema_attr,
        func=func,
        capability=capability,
        isolated=isolated,
    )


# 唯一需要手工维护的表：新增工具只改这里（外加建立对应子包）。
SPECS: list[ToolSpec] = [
    _spec("automation", "automation", "AUTOMATION_TOOL_SCHEMA", "Automation", RESEARCH),
    _spec("bash", "bash", "BASH_TOOL_SCHEMA", "Bash", CORE, isolated=True),
    _spec("brainstorm", "brainstorm", "BRAINSTORM_TOOL_SCHEMA", "BrainStorm"),
    _spec("connectors", "connectors", "CONNECTORS_TOOL_SCHEMA", "Connectors", RESEARCH),
    _spec(
        "contributions",
        "contributions",
        "CONTRIBUTIONS_TOOL_SCHEMA",
        "Contributions",
        RESEARCH,
    ),
    _spec("cron", "cron", "CRON_TOOL_SCHEMA", "Cron"),
    _spec("data", "data", "DATA_TOOL_SCHEMA", "Data", RESEARCH),
    _spec(
        "environments",
        "environments",
        "ENVIRONMENTS_TOOL_SCHEMA",
        "Environments",
        RESEARCH,
    ),
    _spec("fetch", "fetch", "FETCH_TOOL_SCHEMA", "Fetch", CORE, isolated=True),
    _spec("filesystem", "filesystem", "FILESYSTEM_TOOL_SCHEMA", "FileSystem"),
    _spec("memo", "memo", "MEMO_TOOL_SCHEMA", "Memo"),
    _spec("notebook", "notebook", "NOTEBOOK_TOOL_SCHEMA", "Notebook", RESEARCH),
    _spec("paper", "paper", "PAPER_TOOL_SCHEMA", "Paper", RESEARCH),
    _spec("request", "request", "REQUEST_TOOL_SCHEMA", "Request", CORE, isolated=True),
    _spec("research", "research", "RESEARCH_TOOL_SCHEMA", "Research", RESEARCH),
    _spec("search", "search", "SEARCH_TOOL_SCHEMA", "Search", CORE, isolated=True),
    _spec("task", "task", "TASK_TOOL_SCHEMA", "Task"),
    _spec("callmcp", "callmcp", "MCP_TOOL_SCHEMA", "CallMCP"),
    _spec(
        "kernelupgrade", "kernelupgrade", "KERNELUPGRADE_TOOL_SCHEMA", "KernelUpgrade"
    ),
]

BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in SPECS}

# 以下派生表不触碰工具包，必须在「解析 Schema」之前定义：
# 子包会经 utils.route 反向 import 到这里。
TOOL_FUNC_MAP: dict[str, str] = {spec.name: spec.func for spec in SPECS}

# 只有「易卡死且无进程内状态」的工具才丢子进程。callmcp 曾被隔离，导致 MCP
# 连接随子进程销毁（Chrome 等被连带关闭），防卡死改由 asyncio.wait_for 兜底。
PROCESS_ISOLATED_TOOLS: set[str] = {spec.name for spec in SPECS if spec.isolated}

# 子任务只需要「读写 + 检索 + 抓取 + MCP」，顺序保持历史契约（刻意不含 Request）。
BASE_TASK_TOOL_NAMES = ("bash", "filesystem", "search", "callmcp", "fetch")

# 解析 Schema 会拉起工具包，放在最后，避免加载期形成环。
AGENT_TOOL_SCHEMA: list[dict] = [spec.schema for spec in SPECS]
BASE_TASK_TOOL_SCHEMA: list[dict] = [
    BY_NAME[name].schema for name in BASE_TASK_TOOL_NAMES
]


def spec_for(name: str) -> ToolSpec | None:
    return BY_NAME.get(name.lower())


def schemas_for(capabilities) -> list[dict]:
    """按能力域返回 Schema，顺序与全量声明一致，保证请求前缀稳定。"""

    allowed = set(capabilities or ())
    if not allowed:
        return list(AGENT_TOOL_SCHEMA)
    return [spec.schema for spec in SPECS if spec.capability in allowed]
