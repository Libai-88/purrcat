"""Bash 工具模块 - 通过可插拔后端执行命令（默认本地 shell）。"""

import traceback

from src.tool.utils.format import error_response, text_response, warning_response

from .backends import get_backend
from .exceptions import (
    BashTimeoutError,
    DockerImageNotFoundError,
    DockerNotRunningError,
)


def Bash(command: str, timeout: int = 30, session_id: str = "default", **kwarg) -> str:
    """
    在工作目录中执行 Shell 命令。

    默认使用本机 shell（Windows 优先 Git Bash，其次 PowerShell；Unix 用 bash）；
    显式设置 PURRCAT_EXEC_BACKEND=docker 时改用 Docker 沙盒。

    Args:
        command: 要执行的 Shell 命令（支持连串命令和多行文本，请注意正确的引号转义）
        timeout: 命令执行的超时时间（秒），默认 30 秒
        session_id: 会话 ID（由系统注入，模型无需关注）
    Returns:
        格式化后的 JSON 字符串，包含 timestamp, type, content, snip 字段
    """
    try:
        # 命令判空校验
        if not command or not command.strip():
            return error_response(
                "Bash command 不能为空，请提供要执行的 Shell 指令。", "❌ 参数错误"
            )

        backend = get_backend()
        exit_code, output, cwd = backend.execute(session_id, command, timeout)

        content_str = output if output else "[无输出]"

        if exit_code == 0:
            snip = "✅ 成功"
            return text_response(content_str, snip)
        else:
            close_session(session_id)
            snip = f"❌ 失败(exit={exit_code})"
            return warning_response(content_str, snip)

    except DockerNotRunningError:
        # 显式启用 Docker 后端但引擎未启动
        return error_response(
            "Docker 未连接。请启动 Docker Desktop，或改用本地执行"
            "（PURRCAT_EXEC_BACKEND=local）。",
            "❌ 环境异常",
        )

    except DockerImageNotFoundError:
        # 显式启用 Docker 后端但镜像/容器不可用
        return error_response(
            "Docker 镜像或容器启动失败，请检查沙盒镜像，或改用本地执行。",
            "❌ 环境异常",
        )

    except BashTimeoutError as e:
        # 超时异常携带超时前的部分输出，帮助定位卡点
        partial = str(e).strip()
        partial_hint = f"\n\n超时前的部分输出:\n{partial}" if partial else ""
        return error_response(
            f"执行超时（超过{timeout}秒）。涉及网络下载（如 pip install、apt-get）"
            f"时，可临时换国内源并重试；长耗时任务（测试、构建）请显式传更大的 "
            f"timeout，或把命令放后台执行后轮询结果。{partial_hint}",
            "❌ 执行超时(建议换源)",
        )

    except Exception as e:
        # 兜底捕获其他未知的运行时异常
        traceback.print_exc()
        return error_response(f"Shell 运行时异常: {str(e)}", "❌ 执行失败")


def close_session(session_id: str = "default") -> str:
    """
    关闭 Shell 会话（本地后端不维持持久会话，此调用为兼容保留）

    Args:
        session_id: 会话 ID，默认 "default"

    Returns:
        格式化后的 JSON 字符串
    """
    try:
        get_backend().close_shell(session_id)
        content = f"Shell session '{session_id}' successfully closed."
        return text_response(content, f"关闭会话: {session_id}")
    except Exception as e:
        traceback.print_exc()
        return error_response(f"关闭会话失败: {str(e)}", "操作失败")
