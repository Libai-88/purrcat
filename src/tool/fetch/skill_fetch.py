"""Skill 获取模块 - 加载和解析技能文件"""

import os
import shutil
import stat
import time
from src.utils.config import AGENT_VM_DIR
from src.utils.skill_helper import _find_skill_md_file, _parse_skill_md
from src.utils import research_catalog
from .exceptions import SkillNotFoundError


def install_from_catalog(name: str) -> tuple[str, str]:
    """从科研技能目录按需安装一个技能。

    返回 (安装后的技能名, 失败原因)；目录里没有该技能时两者都为空串。
    目录条目记录了来源仓库与固定 commit，因此安装内容可复现。
    """
    entry = research_catalog.find_entry(name)
    if entry is None:
        return "", ""

    from src.server.api.research_install import install_catalog_skill

    try:
        installed = install_catalog_skill(entry)
    except Exception as exc:
        source = entry.get("source") or {}
        return "", (
            f"目录条目安装失败: {exc}（来源 {source.get('repository')} "
            f"@{source.get('commit', '')[:8]}）"
        )
    if not installed:
        return "", f"目录条目安装后未落地技能目录（来源 {entry.get('source')}）"

    from src.tool.search.skill_search import reload_skill_index

    reload_skill_index()
    return installed, ""


def _force_rmtree(path: str, max_retries: int = 3, retry_delay: float = 0.1):
    """
    强制删除目录，处理 Windows 上的只读属性和文件锁定问题

    Args:
        path: 要删除的目录路径
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
    """

    def _on_exc(exc):
        os.chmod(exc.filename, stat.S_IWRITE)
        return True

    for attempt in range(max_retries):
        try:
            shutil.rmtree(path, onexc=_on_exc)
            return
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise


def load_skill(name: str) -> tuple:
    """
    加载技能文件详情

    Args:
        name: 技能名称（frontmatter name，可能与目录名不同）

    Returns:
        (skill_dict, error_message)
    """
    try:
        # 先定位真实主库目录：技能目录名可能与 frontmatter name 不同
        # （如 soft-skill 目录内技能的 name 是 high-end-visual-design）
        md_file, sandbox_dir = _find_skill_md_file(name)
        reason = ""
        if not md_file.exists():
            # 本地没有就查科研技能目录，命中则按需安装
            _installed, reason = install_from_catalog(name)
            md_file, sandbox_dir = _find_skill_md_file(name)
        if not md_file.exists():
            raise SkillNotFoundError(name, reason)

        # ==== 载入前从主库拉取最新的一份覆盖进沙盒中 ====
        # 以定位到的真实目录为复制源，按技能名落到沙盒（与 sandbox_dir 对齐），
        # 强制覆盖沙盒里的缓存，保证 Agent 在沙盒里执行时是最新的
        source_dir = str(md_file.parent)
        target_dir = os.path.join(AGENT_VM_DIR, "skills", name)

        os.makedirs(os.path.dirname(target_dir), exist_ok=True)
        if os.path.exists(target_dir):
            _force_rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        # =======================================================

        parsed_data = _parse_skill_md(md_file)
        metadata = parsed_data["metadata"]

        return {
            "name": metadata.get("name", name),
            "description": metadata.get("description", metadata.get("desc", "")),
            "content": parsed_data["content"],
            "directory": str(sandbox_dir),
        }, None
    except SkillNotFoundError:
        raise
    except Exception as e:
        return None, f"解析技能文件失败: {str(e)}"
