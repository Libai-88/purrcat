# SPEC-024：本地执行后端（去除 Docker 必需依赖）

## 背景

Bash 工具当前只有 Docker 一种执行后端（`src/tool/bash/docker_env.py`），启动时还会后台拉取沙盒镜像（`src/utils/sandbox_setup.py`），依赖检查把 Docker 列为缺失项，安装脚本默认安装 Docker Desktop。

结果是：没有 Docker 或不愿安装 Docker 的新用户，Bash 工具完全不可用，Agent 失去执行能力；而 Docker Desktop 需要 WSL2、管理员权限与重启，安装门槛远高于 Python 与 Node。

目标：默认使用本机 shell 执行，Docker 降级为可选后端，使新用户在不安装 Docker 的前提下获得完整执行能力。

## 行为

1. **默认本地执行**：没有任何额外配置时，Bash 工具在本机执行命令。
   - Windows：优先使用 Git Bash（`bash.exe`），没有则使用 PowerShell。
   - macOS / Linux：使用 `bash -lc`。
2. **工作目录固定**：命令在 `AGENT_VM_DIR`（`<data_root>/agent_vm`）下执行，目录不存在时自动创建。每次调用从该目录开始，`cd` 不跨调用保留。
3. **执行约束**：超时后终止整棵进程树并返回已捕获的部分输出；输出做 ANSI 清理并截断到 100 KB；执行前清洗 `PYTHONHOME` / `PYTHONPATH` / `VIRTUAL_ENV` 等父进程环境变量。
4. **Docker 变为可选**：设置 `PURRCAT_EXEC_BACKEND=docker` 时仍走原有 Docker 沙盒；默认值与 `auto` 都是本地执行。
5. **启动不再碰 Docker**：不再后台拉取沙盒镜像，不再因 Docker 缺失写入依赖缺失请求。
6. **安装脚本不装 Docker**：`install.ps1` / `install.sh` 不再安装 Docker Desktop 或 dockerd。
7. **依赖检查**保留 git / uv / node / 嵌入模型四项；Docker 与沙盒镜像不再计入缺失。
8. **工具描述**如实说明当前后端与 shell 类型，不再声称“在 Docker 沙盒中执行”。

## 验收标准

- [ ] AC-1：未安装 Docker 时，Bash 工具能执行 `echo`、`pwd` 并返回正确退出码与工作目录。
- [ ] AC-2：命令超过 timeout 时被终止，返回超时错误并携带部分输出，且不残留子进程。
- [ ] AC-3：命令的工作目录是 `AGENT_VM_DIR`；构造的本地命令拒绝把 cwd 解析到该目录之外。
- [ ] AC-4：`dependency_check` 在无 Docker 的机器上不产生 sandbox/docker 缺失项。
- [ ] AC-5：`install.ps1` 与 `install.sh` 中不存在安装 Docker 的分支。
- [ ] AC-6：`PURRCAT_EXEC_BACKEND=docker` 时仍可选择 Docker 后端（回归，不要求本机有 Docker 也能通过单测）。
- [ ] AC-7：`docs/develop/README.md`、`AGENTS.md` 不再把 Docker 描述为必需前置。

## 非目标

- 不做操作系统级强隔离（AppContainer / Job Object 仅用于终止进程树，不用于文件系统隔离）。
- 不重写部署页中 Docker 容器磁盘运维（`disk_ops` / `disk_maintenance` / `disk_probe`）的界面；本地模式直接跳过这些入口。
- 不改变 Agent 主循环、工具批次或 Hook 阶段顺序。

## 测试矩阵

| 层级 | 位置 | 覆盖的验收标准 |
| --- | --- | --- |
| L0 | `tests/l0/test_bash_local_backend.py` | AC-1 命令构造、AC-3、AC-6 后端选择 |
| L1 | `tests/l1/test_bash_local_execution.py` | AC-1 真实执行、AC-2 超时 |
| L0 | `tests/l0/test_dependency_check_local.py` | AC-4 |
| L3 | `tests/l3/test_no_docker_requirement.py` | AC-5、AC-7 |

## 风险与回滚

- 本地执行没有容器隔离，命令直接作用于本机；`AGENT_VM_DIR` 只是默认工作目录，不是强制边界。需要在工具描述与设置页明确风险。
- 本地 shell 的工具链取决于宿主环境（python/node/git 由依赖检查单独提示），不再有镜像内预装环境。
- 回滚：`PURRCAT_EXEC_BACKEND=docker` 可切回原后端；`backends/local.py` 为新增文件，删除即可回到旧行为。
