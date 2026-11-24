"""按科研技能目录条目安装单个技能。

上游仓库动辄上千个技能，整仓归档下载代价过高，慢网络下尤其明显。
这里只拉该技能目录下的文件：优先用目录条目里固定好的文件清单，
清单缺失时才去要一次文件树，再不行才退回整仓归档。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor

from src.utils.config import SKILL_DIR
from src.utils.http_fetch import fetch_bytes

_API_TREE = "https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1"
_RAW_FILE = "https://raw.githubusercontent.com/{repository}/{commit}/{path}"

_USER_AGENT = "purrcat-research-skills/1.0"
_TIMEOUT = 60
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_FILES = 200
_WORKERS = 8

_tree_cache: dict[tuple[str, str], dict] = {}


def _http_get(url: str, retries: int = 3) -> bytes:
    """取一个 URL 的内容。

    到 GitHub 的链路时快时慢，交给共用封装处理重试与断点续传。
    """
    return fetch_bytes(url, timeout=_TIMEOUT, retries=retries, user_agent=_USER_AGENT)


def fetch_tree(repository: str, commit: str) -> dict:
    """取仓库文件树；同一仓库同一 commit 只请求一次。"""
    key = (repository, commit)
    cached = _tree_cache.get(key)
    if cached is not None:
        return cached
    payload = json.loads(
        _http_get(_API_TREE.format(repository=repository, commit=commit)).decode(
            "utf-8", errors="replace"
        )
    )
    if "tree" not in payload:
        raise RuntimeError(f"仓库不可访问: {repository}")
    _tree_cache[key] = payload
    return payload


def list_skill_files(repository: str, commit: str, path: str) -> list[tuple[str, int]]:
    """列出技能目录下的文件；返回 (仓库内路径, 字节数)。"""
    payload = fetch_tree(repository, commit)
    prefix = path.rstrip("/") + "/"
    files = []
    for item in payload.get("tree", []):
        if item.get("type") != "blob":
            continue
        item_path = item.get("path", "")
        if not item_path.startswith(prefix):
            continue
        files.append((item_path, int(item.get("size") or 0)))
    files.sort()
    return files


def _safe_relative(relative: str) -> bool:
    """相对路径是否安全：不越出技能目录。"""
    if not relative or relative.startswith("/"):
        return False
    return ".." not in relative.split("/")


def _write_file(dest: str, relative: str, data: bytes) -> None:
    local_path = os.path.join(dest, relative.replace("/", os.sep))
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as handle:
        handle.write(data)


def _fetch_many(
    repository: str, commit: str, prefix: str, relatives: list[str], dest: str
) -> None:
    """并发下载一组文件到目标目录。"""

    def _one(relative: str):
        url = _RAW_FILE.format(
            repository=repository, commit=commit, path=f"{prefix}/{relative}"
        )
        return relative, _http_get(url)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        for relative, data in pool.map(_one, relatives):
            _write_file(dest, relative, data)


def _finish_install(staging: str, dest: str, skill_name: str, path: str) -> str:
    """校验并落盘：先在暂存目录备齐，再整体搬到位。"""
    if not os.path.isfile(os.path.join(staging, "SKILL.md")):
        raise RuntimeError(f"技能目录缺少 SKILL.md: {path}")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(SKILL_DIR, exist_ok=True)
    shutil.move(staging, dest)
    return skill_name


def install_by_files(repository: str, commit: str, path: str, files: list[str]) -> str:
    """按目录条目记录的文件清单安装；不需要 api.github.com。

    目录在发布时就固定了文件清单，安装时逐个按 commit 取原文即可。
    """
    relatives = [item for item in files if _safe_relative(item)]
    if not relatives:
        raise RuntimeError(f"目录条目没有可用文件清单: {path}")
    if len(relatives) > _MAX_FILES:
        raise RuntimeError(f"技能文件过多（{len(relatives)}），已跳过")

    skill_name = os.path.basename(path.rstrip("/")) or repository
    dest = os.path.join(SKILL_DIR, skill_name)

    staging = tempfile.mkdtemp(prefix="purrcat-skill-")
    try:
        _fetch_many(repository, commit, path.rstrip("/"), relatives, staging)
        return _finish_install(staging, dest, skill_name, path)
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def install_by_tree(repository: str, commit: str, path: str) -> str:
    """按文件树安装单个技能，返回安装后的目录名。"""
    tree_files = list_skill_files(repository, commit, path)
    if not tree_files:
        raise RuntimeError(f"技能目录为空: {path}")
    if len(tree_files) > _MAX_FILES:
        raise RuntimeError(f"技能目录文件过多（{len(tree_files)}），已跳过")

    prefix = path.rstrip("/") + "/"
    relatives = []
    for item_path, size in tree_files:
        relative = item_path[len(prefix) :]
        if size <= _MAX_FILE_BYTES and _safe_relative(relative):
            relatives.append(relative)

    skill_name = os.path.basename(path.rstrip("/")) or repository
    dest = os.path.join(SKILL_DIR, skill_name)

    staging = tempfile.mkdtemp(prefix="purrcat-skill-")
    try:
        _fetch_many(repository, commit, path.rstrip("/"), relatives, staging)
        return _finish_install(staging, dest, skill_name, path)
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _install_by_archive(repository: str, commit: str, path: str) -> str:
    """归档兜底：下载整个仓库 zip 再解出技能目录。

    走的是 github.com，比文件树慢不少，且要下整个仓库；
    但它不依赖 api.github.com，限流时只有这条路可用。
    """
    url = f"https://github.com/{repository}/archive/{commit}.zip"
    data = _http_get(url, retries=2)

    from src.server.api.market_archive import extract_skill_from_zip

    repo_name = repository.split("/", 1)[-1]
    return extract_skill_from_zip(data, repo_name, path)


def install_catalog_skill(entry: dict) -> str:
    """安装目录条目对应的技能，返回安装后的目录名；失败返回空串。

    优先用目录里的文件清单（不依赖 api.github.com）；清单缺失时退回文件树，
    再不行才下整个仓库归档。
    """
    source = entry.get("source") or {}
    repository = str(source.get("repository") or "")
    commit = str(source.get("commit") or "")
    path = str(source.get("path") or "")
    if not (repository and commit and path):
        return ""

    files = entry.get("files") or []
    if files:
        try:
            return install_by_files(repository, commit, path, list(files))
        except Exception:
            pass

    try:
        return install_by_tree(repository, commit, path)
    except Exception:
        return _install_by_archive(repository, commit, path)
