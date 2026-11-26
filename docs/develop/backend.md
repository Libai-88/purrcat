# 后端开发

FastAPI 应用，入口 `main.py`，代码在 `src/`。

## 启动顺序

`main.py` 的初始化顺序不可调整：

```text
multiprocessing.freeze_support()
  → 端口预检（必须带 __name__ != "__main__" 守卫）
  → ensure_initialized()（必须在业务 import 之前）
  → init_agent()
  → 注册路由
  → /api/health
  → 挂载 /minimal 静态目录
  → uvicorn
```

- 健康检查路由必须先于静态挂载注册。
- `_bg_heavy_init()` 异步预热重依赖，不阻塞首屏。
- 端口由 `scripts/dev.mjs` 或启动参数决定，`--api-port` 缺省时按 `electron/api-port.cjs` 的规则挑选。
- **监听地址默认 `127.0.0.1`**（`DEFAULT_BIND_HOST`），唯一放开入口是环境变量 `PURRCAT_BIND`（`resolve_bind_host()`）。不要绕过硬编码 `0.0.0.0`。所有 `/api/*` 走统一凭证守卫（`src/server/auth.py`），豁免集只有 `/api/health` 与 `/minimal` 前缀；凭证复用 `~/.purrcat/acp_token`，可走 `X-PurrCat-Token` 头或 `/minimal` 下发的 `purrcat_token` cookie。

## Agent 主循环

```text
on_loop_start → while: on_loop_epoch → 调模型
  ├─ 有 tool_calls → 执行 → on_tool_calling
  └─ 无 → on_loop_end → 通过则结束；否则注入 workflow_hint 重试
```

Hook 阶段固定为 `on_build_system_prompt / on_loop_start / on_loop_epoch / on_tool_calling / on_loop_end / on_input_received`，由范式（AgentLoop）声明。范式存于 `~/.purrcat/paradigms/*.yaml`，会话可在 `meta.json` 绑定并热切换（不重建系统提示，保 KV Cache）。细节见 [AgentLoop 开发](../plugins/agentloop.md)。

## 会话存储

```text
~/.purrcat/data/checkpoints/agent/<session_id>/
├─ meta.json          # token 权威 + mode + capabilities
├─ main.json          # 主干历史快照（完整数组）
├─ main.journal.jsonl # 主干增量（每行 {"i": n, "m": message}）
├─ sub_<branch>.json  # 子代理分支快照
├─ sub_<branch>.journal.jsonl
├─ plan.md
└─ attachment/
```

写路径是"快照 + 增量"（`src/agent/session_journal.py`）：`<branch>.json` 始终是能被任何读方直接解析的完整数组，新增消息先 append 到 `.journal.jsonl`，满 200 行或距上次压实 30 s 才重建快照。回放只接受紧接快照末尾的**连续**序号，半行与跳号一律丢弃而不是拼错历史——崩溃只会丢最后一条未落盘的消息。整段回退用环境变量 `PURRCAT_STORE=legacy`。

路径布局统一由 `src/agent/session_layout.py` 生成（`branch_path()` 等），读写两侧不得各写一套。

列表索引 `index.json` **不含 token**，任何统计或展示 token 都必须读 `meta.json`。

## 工具路由

- **唯一事实源是 `src/tool/registry.py`** 的 `SPECS`：每条 `ToolSpec(name, module, schema_attr, func, capability, isolated, timeout_ms)`；`TOOL_FUNC_MAP`、`PROCESS_ISOLATED_TOOLS`、`AGENT_TOOL_SCHEMA`、`BASE_TASK_TOOL_SCHEMA`、`schemas_for()` 全部由它派生，不要再手工维护第二张表。
- 统一入口 `dispatch_tool`（`src/tool/utils/route.py`），输出按 token 截断（FileSystem 读上限 9900）。
- 进程隔离白名单由 `SPECS` 的 `isolated` 派生，当前恰为 `bash / request / fetch / search`，不可扩大。
- 有状态工具（callmcp、brainstorm、task、memo 等）必须留在主进程；callmcp 用 `asyncio.wait_for` 防挂起。

新增工具：`src/tool/<name>/` 实现 `func` 与 schema → **在 `registry.py` 的 `SPECS` 加一条**（其余派生表自动跟上）→ 视需要补 `capability`（`core` 进 work 模式，`research` 只进 science 模式）。

注意注册表有一处结构约束：schema 必须保持惰性（`@property` + `importlib.import_module`），且**派生表要在 schema 解析之前算好**，否则 `bash → utils.format → utils/__init__ → route → registry` 会形成循环导入。

## 会话能力域

每个会话在创建时把可用工具集固化成 `meta.json` 的 `capabilities`（`src/agent/capabilities.py`）：`work → ["core"]`、`science → ["core","research"]`。当前模式读 `~/.purrcat/settings.json` 的 `webminConfig.mode.value`。

**切模式不改变已有会话**——工具定义位于请求前缀，动态改 schema 会击穿 KV Cache。老会话缺 `capabilities` 字段一律给全量，切模式只影响之后新建的会话。`Agent._get_tool_schema()` 用 `schemas_for(self.capabilities)`，因此能力域是会话级、不可在轮内变更。

## 其它子系统

- DAG：[Graph 开发](../plugins/graph.md)，人工干预节点必须真暂停。
- Sensor：[Sensor 开发](../plugins/sensor.md)，stdout 只输出 JSON-RPC，日志走 stderr。
- ACP：[ACP 接口](../api/acp.md)，需 `X-PurrCat-Token`。

## 运行数据

```text
~/.purrcat/
├─ settings.json · model.json · mcp_config.json · activate_sensor.json
├─ file.json · mcp_schema.json · acp_token
├─ core/          # SOUL.md / GOAL.md / MEMORY.md / info.json / heartbeat.json / cron.json
├─ paradigms/ · skills/ · mcps/ · sensor/ · graph/ · webmin-plugins/
├─ data/          # memory · projects · checkpoints/agent · checkpoints/task
└─ bin/acp_relay.py · logs/backend.log · run/control.json
```

`data_root` 可迁移。用户数据不得写入源码目录。

## 调试

- 改后端必须彻底重启进程并清理残留的 `uv.exe`，否则内存代码与磁盘不一致。
- 崩溃先看 `~/.purrcat/logs/backend.log`。
- 改了 `src/server` 必须同步 `docs/api/`，否则 `scripts/check_api_docs.py` 与 CI 会失败。
