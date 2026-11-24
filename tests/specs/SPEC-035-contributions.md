# SPEC-035：贡献工作区（本地工作区 → diff → 审阅 → 草稿 PR）

## 背景

PurrCat 有 evolve 工厂能在沙盒里改代码、有 Git 能提交，但「把一次改动贡献回上游」
这件事没有一条完整、可回查的路径。Pero 的贡献流程给了三个值得照搬的规则：

1. **Agent 不发布。** 提示里明确禁止它 commit / push / fork / 开 PR；
   发布权留在用户手里。
2. **review token 是 diff 的乐观锁。** 审阅完后文件又变了，就不能拿旧审阅发 PR——
   必须先刷新 diff 重新审阅。
3. **发 PR 前先查有没有已存在的。** 重试不能造成重复 PR。

另有两条从这一系列 spec 一贯下来的不变量：

- **排上了 ≠ 成功**：草稿 PR 建好了不等于贡献被接受。
- **状态不说结论可信**：贡献状态里不带 acceptance / verification。

## 行为

1. **工作区从本机目录或 GitHub 仓库建立**，记下 base commit 与分支名。
2. **Agent 在工作区里改文件**，但**不提交、不推送、不开 PR**（写在提示词里）。
3. **产生 diff 与 review token**：token 是 diff 内容的指纹，用于乐观锁。
4. **审阅必须针对当前 diff**：拿旧 token 发 PR 会被拒收，提示刷新 diff。
5. **发布是独立、显式的动作**：只有用户明确点「发草稿 PR」才执行；
   发之前先查有没有同分支的已存在 PR，避免重试造成重复。
6. **只发草稿 PR**，不直接合并。
7. **发布结果带回执**：成没成、PR 链接在哪；回执不说贡献会不会被接受。
8. **未处理的失败不丢工作**：发布失败时本地改动还在，可重试。

## 验收标准

- [ ] AC-1：工作区能建立、读取、列出、释放。
- [ ] AC-2：Agent 提示里明确禁止 commit / push / fork / PR。
- [ ] AC-3：review token 是 diff 内容的指纹；文件变了 token 就变。
- [ ] AC-4：拿过期 token 发 PR 被拒收。
- [ ] AC-5：发 PR 前先查询同分支已有 PR（重试安全）。
- [ ] AC-6：只发草稿 PR。
- [ ] AC-7：贡献状态里没有 acceptance / verification。
- [ ] AC-8：发布失败时本地改动保留。

## 非目标

- 不做 GitHub OAuth 授权流；用本机已配置好的 `gh` CLI。
- 不做多平台（GitLab / Gitea），本轮只 GitHub。
- 不做自动合并、自动回复评审。
- 不替用户决定发不发 PR——每次发布都要显式动作。
- 不改 Agent 主循环、工具批次与 Hook 阶段顺序。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_contributions.py` | AC-2、AC-3、AC-4、AC-7 |
| L1 | `tests/l1/test_contributions_api.py` | AC-1、AC-5、AC-6、AC-8 |
| L3 | `tests/l3/test_contributions_guardrail.py` | AC-2（提示词红线） |
| 浏览器实测 | `ui/web-minimal/plugins/builtin/builtin-contributions/` | AC-1、AC-3、AC-4 |

## 风险与回滚

- 发布 PR 是对外动作：必须用户显式触发，测试里只验证到「生成草稿命令」为止，
  不打真实 GitHub。
- `gh` 未安装 / 未登录要清晰报出，不静默失败。
- 回滚：删掉 `src/contributions/`、`src/tool/contributions/`、
  `src/server/api/contributions_api.py` 与对应面板；本机工作区目录保留不受影响。
