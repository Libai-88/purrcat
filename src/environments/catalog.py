"""科研环境：只读探测、能力声明、证据边界。

Pero 的环境模型给了三条值得照搬的边界：

1. **元数据观察既不代表可导入，也不代表执行授权。**
2. **准备授权与科学计算批准是两件事。**
3. 就绪度是三态：ready / missing / unknown。

所以这里只说「观察到什么」，不说「能跑什么实验」，更不说「结果对不对」。
探测记录里**没有** acceptance / verification——那是研究记录的事。
"""

from __future__ import annotations

# —— 就绪度三态 ——

READY = "ready"
MISSING = "missing"
UNKNOWN = "unknown"

READINESS_VALUES = (READY, MISSING, UNKNOWN)

# —— 能力封闭词表 ——
# 每项写清「能做什么」与「不能推出什么」——后者才是边界所在。

CAPABILITIES = (
    {
        "id": "process",
        "name": "受管进程",
        "can": "启动一个固定入口的进程，跟踪它的身份与退出状态。",
        "cannot": "不能推出能跟踪整棵进程树；有 shell 不等于有受管进程。",
    },
    {
        "id": "batch",
        "name": "批作业",
        "can": "向站点提交作业，读回状态与产物。",
        "cannot": "提交回执不等于节点已分配；外部作业 ID 不是本机任务 ID。",
    },
    {
        "id": "http",
        "name": "服务会话",
        "can": "访问一个明确的服务端点，并保持会话。",
        "cannot": "能连上数据库不等于可以任意读写所有数据。",
    },
    {
        "id": "terminal",
        "name": "终端",
        "can": "观察终端输出并向它输入。",
        "cannot": "有屏幕不等于有受管进程；关掉终端不等于停掉远端作业。",
    },
)

CAPABILITY_IDS = tuple(item["id"] for item in CAPABILITIES)

# —— 被探测的工具目录 ——
# 复用既有判定逻辑：依赖检查那里怎么判，这里就怎么判。

TOOLS = (
    {
        "id": "python",
        "name": "Python",
        "kind": "interpreter",
        "command": "python",
        "version_args": ("--version",),
        "note": "本机 Python 解释器；版本探测只取 stdout 第一行。",
    },
    {
        "id": "git",
        "name": "Git",
        "kind": "vcs",
        "command": "git",
        "version_args": ("--version",),
        "note": "贡献工作区与技能安装需要。",
    },
    {
        "id": "uv",
        "name": "uv",
        "kind": "package_manager",
        "command": "uv",
        "version_args": ("--version",),
        "note": "Python 依赖解析与虚拟环境。",
    },
    {
        "id": "node",
        "name": "Node.js",
        "kind": "runtime",
        "command": "node",
        "version_args": ("--version",),
        "note": "桌面壳与部分 MCP 工具需要。",
    },
    {
        "id": "docker",
        "name": "Docker",
        "kind": "container",
        "command": "docker",
        "version_args": ("--version",),
        "note": "容器执行后端；默认用本机 shell，不依赖它。",
    },
)


class EnvironmentError(Exception):
    """环境用法不对，或目录里没有这个工具。"""


def list_capabilities() -> list[dict]:
    return [dict(item) for item in CAPABILITIES]


def get_capability(capability_id: str) -> dict:
    for item in CAPABILITIES:
        if item["id"] == capability_id:
            return dict(item)
    raise EnvironmentError(
        f"没有这种能力：{capability_id!r}；可用：{', '.join(CAPABILITY_IDS)}"
    )


def list_tools() -> list[dict]:
    return [dict(item) for item in TOOLS]


def get_tool(tool_id: str) -> dict:
    for item in TOOLS:
        if item["id"] == tool_id:
            return dict(item)
    raise EnvironmentError(
        f"目录里没有这个工具：{tool_id!r}；"
        f"可用：{', '.join(item['id'] for item in TOOLS)}"
    )
