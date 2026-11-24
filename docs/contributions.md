# 贡献工作区

把本机改动变成一篇**草稿 PR**：工作区 → diff → 审阅 → 发布。

## 两条硬规则

1. **Agent 不发布。** 它拿到的指示里明确写着：

   > 不要 commit、不要 push、不要 fork、不要开 pull request；
   > 贡献者会审阅改动，并由 PurrCat 发布。

   **发布权留给用户**——`publish` 是用户显式触发的动作。

2. **review token 是 diff 的乐观锁。** token 是 diff 内容（head + diff + 文件名）的指纹。
   审阅之后文件又变了，token 就对不上，发 PR 会被拒收（HTTP 409）：
   「审阅之后文件变了。先刷新 diff 重新审阅，再发 PR。」

另有两条一贯的不变量：

- **草稿 PR 建好了 ≠ 贡献会被接受**（排上了 ≠ 成功）；
- 贡献状态里**没有** `acceptance` / `verification`——流程走到哪，
  和这个贡献好不好，是两件事。

## 内置、开箱即用

贡献是**内置工具 + builtin 面板**，随应用分发，不需要单独安装。

- Agent 侧：`Contributions` 工具（`list` / `prepare` / `start` / `review` / `ready` / `publish` / `release`）
- 面板：`builtin-contributions`

Agent 只能走到 `review`——看 diff、交回审阅凭据；
`ready` 与 `publish` 是用户的动作。

## 流程

| 状态 | 含义 |
| --- | --- |
| `prepared` | 工作区已建立 |
| `working` | Agent 正在里面改 |
| `review` | 有 diff，等审阅；生成 review token |
| `ready` | 用户确认审阅完成 |
| `published` | 草稿 PR 已准备（或发现已有同分支 PR） |
| `released` | 用户放弃；本地改动不动 |

发 PR 前的两道关：

1. **review token 必须对**——过期就拒收；
2. **先查同分支有没有已存在的 PR**——重试不会造成重复 PR。

PR 只能是草稿：生成的命令硬带 `--draft`，且**只生成、不自动执行**——
命令显示在面板里，由你决定是否在自己的终端里跑。

## 边界

- 用本机已配置好的 `gh` CLI，不做 OAuth 授权流。
- 只支持 GitHub。
- 不自动合并、不自动回复评审。
- `gh` 没装 / 没登录会明确报错；本地改动保留，可重试。

## 代码位置

| 关注点 | 位置 |
| --- | --- |
| 领域核心（值 / 状态 / diff 指纹） | `src/contributions/domain.py` |
| Git / gh seam | `src/contributions/gitops.py` |
| 工作区流程 | `src/contributions/store.py` |
| Agent 工具 | `src/tool/contributions/` |
| HTTP 接口 | `src/server/api/contributions_api.py` |
| 面板 | `ui/web-minimal/plugins/builtin/builtin-contributions/` |

设计与验收标准见
[../tests/specs/SPEC-035-contributions.md](../tests/specs/SPEC-035-contributions.md)。
