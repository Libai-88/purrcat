"""采集公开第三方仓库里的科研 SKILL.md，产出目录条目。

只读不执行：仓库内容仅作为文本解析，绝不运行其中任何脚本。

文件树走 api.github.com（一次请求拿到整棵树与 commit），文件内容走
raw.githubusercontent.com（无严格限流），两者都比 git 协议路径快且稳。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sources import REPOSITORIES

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.http_fetch import fetch_text  # noqa: E402

_API_TREE = "https://api.github.com/repos/{repository}/git/trees/HEAD?recursive=1"
_RAW_FILE = "https://raw.githubusercontent.com/{repository}/{commit}/{path}"

_USER_AGENT = "purrcat-research-skills/1.0"
_TIMEOUT = 30
_MAX_WORKERS = 12
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_SKILL_FILES = 80
_LICENSE_NAME_RE = re.compile(r"^(LICENSE|LICENCE|COPYING)[\w.\-]*$", re.IGNORECASE)
_SPDX_RE = re.compile(r"SPDX-License-Identifier:\s*([\w.\-]+)")


class CollectError(RuntimeError):
    """采集失败。"""


class _RateLimited(Exception):
    """命中 api.github.com 的未认证限额。"""

    def __init__(self, reset_at: int):
        self.reset_at = reset_at
        super().__init__(f"触发速率限制，重置时刻 {reset_at}")


def _http_get(url: str, retries: int = 3, wait_for_limit: bool = True) -> str:
    """取一个 URL 的文本内容。

    复用运行时的取数封装：网络抖动重试、大响应断点续传、撞上限额时等重置。
    """
    return fetch_text(
        url, retries=retries, wait_for_limit=wait_for_limit, user_agent=_USER_AGENT
    )


_TREE_CACHE_DIR = Path(".tree-cache")


def _tree_cache_path(repository: str) -> Path:
    return _TREE_CACHE_DIR / (repository.replace("/", "__") + ".json")


def fetch_tree(
    repository: str,
) -> tuple[str, list[str], list[str], list[tuple[str, int]]]:
    """取仓库的文件树与 commit。

    返回 (commit, SKILL.md 路径, 许可文件路径, 全部 blob 的 (路径, 字节数))。
    文件树按仓库缓存到磁盘，重跑采集不必再消耗 api.github.com 配额。
    """
    cache_path = _tree_cache_path(repository)
    payload = None
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
    if payload is None:
        payload = json.loads(_http_get(_API_TREE.format(repository=repository)))
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass
    if "tree" not in payload:
        raise CollectError(f"仓库不可访问: {repository}")
    commit = payload.get("sha", "")
    if payload.get("truncated"):
        raise CollectError(f"仓库文件树过大被截断: {repository}")
    skill_paths = []
    license_paths = []
    blobs = []
    for item in payload["tree"]:
        if item.get("type") != "blob":
            continue
        path = item["path"]
        size = int(item.get("size") or 0)
        blobs.append((path, size))
        if path.endswith("SKILL.md"):
            skill_paths.append(path)
        elif _LICENSE_NAME_RE.match(path.rsplit("/", 1)[-1]):
            license_paths.append(path)
    return commit, sorted(skill_paths), sorted(license_paths), blobs


def group_skill_files(
    skill_paths: list[str], blobs: list[tuple[str, int]]
) -> dict[str, list[str]]:
    """按技能目录归拢该技能下的文件（相对路径）。

    写进目录条目后，运行时安装按清单取原文，不必再要文件树。
    SKILL.md 永远保留，其余按数量上限截断，避免个别超大技能把目录撑爆。
    """
    directories = sorted(
        {path.rsplit("/", 1)[0] for path in skill_paths if "/" in path}
    )
    grouped: dict[str, list[str]] = {directory: [] for directory in directories}
    for path, size in blobs:
        for directory in directories:
            prefix = directory + "/"
            if path.startswith(prefix):
                relative = path[len(prefix) :]
                if relative and size <= _MAX_FILE_BYTES and len(relative) < 200:
                    grouped[directory].append(relative)
    for directory in directories:
        relatives = sorted(set(grouped[directory]))
        if len(relatives) > _MAX_SKILL_FILES:
            kept = ["SKILL.md"] if "SKILL.md" in relatives else []
            rest = [item for item in relatives if item != "SKILL.md"]
            kept += rest[: _MAX_SKILL_FILES - len(kept)]
            relatives = sorted(kept)
        grouped[directory] = relatives
    return grouped


def fetch_license(repository: str, commit: str, license_paths: list[str]) -> str:
    """从仓库许可文件推断 SPDX 标识；优先根目录，其次任意层级。"""
    if not license_paths:
        return ""

    def _rank(path: str) -> tuple:
        depth = path.count("/")
        return (depth, path)

    for path in sorted(license_paths, key=_rank):
        try:
            content = _http_get(
                _RAW_FILE.format(repository=repository, commit=commit, path=path),
                retries=2,
            )
        except CollectError:
            continue
        match = _SPDX_RE.search(content[:4000])
        if match:
            return match.group(1)
        return "unknown"
    return ""


_BLOCK_SCALAR_MARKERS = {"|", ">", "|-", ">-", "|+", ">+"}


def parse_frontmatter(text: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter。

    只认顶层键——嵌套结构（如 metadata.openclaw）里的同名键会覆盖真正的描述。
    块标量（``description: >`` 后接缩进行）也要展开，否则描述整个丢掉。
    """
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    lines = parts[1].splitlines()
    metadata: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line[:1].isspace() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value in _BLOCK_SCALAR_MARKERS:
            folded = value.startswith(">")
            chunk: list[str] = []
            while index < len(lines) and (
                not lines[index].strip() or lines[index][:1].isspace()
            ):
                chunk.append(lines[index].strip())
                index += 1
            joined = " ".join(part for part in chunk if part).strip()
            metadata[key] = joined if folded else "\n".join(chunk).strip()
            continue
        metadata[key] = value.strip("'\"")
    return metadata


def _entry_from_text(
    repository: str,
    commit: str,
    path: str,
    text: str,
    license_id: str,
    files: list[str] | None = None,
):
    """由 SKILL.md 原文生成一个目录条目。

    files 是该技能目录下的相对文件清单；写进目录后，运行时安装不再需要
    向 api.github.com 要文件树，直接按清单取原文即可。
    """
    metadata = parse_frontmatter(text)
    skill_dir = path.rsplit("/", 1)[0] if "/" in path else ""
    name = (metadata.get("name") or skill_dir.rsplit("/", 1)[-1]).strip()
    description = (metadata.get("description") or metadata.get("desc") or "").strip()
    license_value = (metadata.get("license") or license_id or "").strip()
    return {
        "name": name,
        "description": description,
        "license": license_value,
        "files": list(files or []),
        "source": {
            "repository": repository,
            "commit": commit,
            "path": skill_dir,
            "url": f"https://github.com/{repository}/tree/{commit}/{skill_dir}",
        },
    }


def collect_repository(repository: str) -> list[dict]:
    """采集单个仓库的 SKILL.md 条目。"""
    commit, skill_paths, license_paths, blobs = fetch_tree(repository)
    if not skill_paths:
        raise CollectError("未找到 SKILL.md")

    license_id = fetch_license(repository, commit, license_paths)
    skill_files = group_skill_files(skill_paths, blobs)

    def _read(path: str):
        try:
            text = _http_get(
                _RAW_FILE.format(repository=repository, commit=commit, path=path),
                retries=2,
            )
        except CollectError:
            return None
        skill_dir = path.rsplit("/", 1)[0] if "/" in path else ""
        return _entry_from_text(
            repository,
            commit,
            path,
            text,
            license_id,
            files=skill_files.get(skill_dir, []),
        )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = list(pool.map(_read, skill_paths))

    entries = [item for item in results if item]
    if not entries:
        raise CollectError("SKILL.md 内容读取失败")
    return entries


def collect_all(repositories: list[str]) -> tuple[list[dict], list[dict]]:
    """采集全部仓库；返回 (条目列表, 失败记录)。"""
    entries: list[dict] = []
    failures: list[dict] = []

    for repository in repositories:
        try:
            found = collect_repository(repository)
        except Exception as exc:
            failures.append({"repository": repository, "error": str(exc)})
            print(f"[!] {repository} 采集失败: {exc}")
            continue
        entries.extend(found)
        print(f"[+] {repository}: {len(found)} 个技能")

    return entries, failures


def refresh_from_existing(previous: dict) -> tuple[list[dict], list[dict]]:
    """复用既有采集结果里的来源路径，只重新读取 SKILL.md 原文。

    来源路径与 commit 已经固定，内容重取只走 raw.githubusercontent.com，
    不消耗 api.github.com 配额；适合修正解析逻辑或补齐描述后重跑。
    """
    entries: list[dict] = []
    failures: list[dict] = []

    targets = []
    paired = []
    for raw in previous.get("skills", []):
        source = raw.get("source") or {}
        repository = source.get("repository")
        commit = source.get("commit")
        path = source.get("path")
        if not (repository and commit and path):
            continue
        skill_md = f"{path.rstrip('/')}/SKILL.md"
        targets.append((repository, commit, path, skill_md))
        paired.append((targets[-1], raw))

    def _read(item):
        target, raw = item
        repository, commit, path, skill_md = target
        try:
            text = _http_get(
                _RAW_FILE.format(repository=repository, commit=commit, path=skill_md),
                retries=2,
            )
        except CollectError:
            return None
        return _entry_from_text(
            repository,
            commit,
            skill_md,
            text,
            "",
            files=raw.get("files") or [],
        )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = list(pool.map(_read, paired))

    for (target, _raw), item in zip(paired, results):
        if item is None:
            failures.append({"repository": target[0], "error": "内容读取失败"})
            continue
        entries.append(item)

    return entries, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="采集公开科研 SKILL.md 目录")
    parser.add_argument(
        "--output", type=Path, required=True, help="采集结果 JSON 输出路径"
    )
    parser.add_argument(
        "--repo", action="append", default=[], help="只采集指定仓库，可重复"
    )
    parser.add_argument(
        "--refresh",
        type=Path,
        default=None,
        help="复用既有采集结果的来源路径，只重读原文（不消耗 API 配额）",
    )
    args = parser.parse_args()

    if args.refresh:
        previous = json.loads(args.refresh.read_text(encoding="utf-8"))
        entries, failures = refresh_from_existing(previous)
    else:
        repositories = args.repo or REPOSITORIES
        entries, failures = collect_all(repositories)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"skills": entries, "failures": failures}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    print(
        f"\n共采集 {len(entries)} 个技能，失败 {len(failures)} 个仓库 -> {args.output}"
    )


if __name__ == "__main__":
    main()
