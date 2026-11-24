"""论文库：导入 PDF、分页落盘、按页读取原文。

论文库是本机数据，位于数据目录下的 papers/。导入时按页提取文本层并落盘，
之后读取某页原文只是文件读，不必再解析 PDF。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.utils.config import DATA_ROOT

PAPERS_DIRNAME = "papers"
_PAGES_DIRNAME = "pages"
_META_FILENAME = "meta.json"
_INDEX_FILENAME = "index.json"
_SLUG_RE = re.compile(r"[^0-9a-z一-鿿]+")


class PaperError(Exception):
    """论文库操作失败。"""


def papers_root() -> Path:
    """论文库根目录。"""
    return Path(DATA_ROOT) / PAPERS_DIRNAME


def _slug(title: str) -> str:
    slug = _SLUG_RE.sub("-", (title or "").casefold()).strip("-")
    return slug[:40] or "paper"


def _paper_id(source_path: str, title: str) -> str:
    """论文 id：可读短名 + 来源路径哈希，同一文件重复导入落到同一处。"""
    digest = hashlib.sha1(os.path.abspath(source_path).encode("utf-8")).hexdigest()
    return f"{_slug(title)}-{digest[:8]}"


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def _extract_pages(source: str) -> list[str]:
    """提取 PDF 的逐页文本层。

    没有文本层（扫描件）时抛 PaperError——空页只会让后续核对给出误导结论。
    """
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的兜底
        raise PaperError("缺少 PDF 解析依赖 pdfplumber") from exc

    pages: list[str] = []
    try:
        with pdfplumber.open(source) as pdf:
            for page in pdf.pages:
                pages.append((page.extract_text() or "").strip())
    except PaperError:
        raise
    except Exception as exc:
        raise PaperError(f"PDF 解析失败: {exc}") from exc

    if not pages:
        raise PaperError("PDF 里没有可提取的页面")
    if not any(pages):
        raise PaperError(
            "这份 PDF 没有文本层（可能是扫描件），本轮不做 OCR，无法用于证据核对"
        )
    return pages


def _title_from(path: Path, pages: list[str]) -> str:
    """论文标题：优先取首页首行，否则用文件名。"""
    for line in pages[0].splitlines():
        stripped = line.strip()
        if len(stripped) >= 4:
            return stripped[:120]
    return path.stem


def import_paper(source_path: str) -> dict:
    """导入一篇 PDF 到论文库，返回它的元数据。

    重复导入同一文件会覆盖旧版本，论文 id 不变。
    """
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise PaperError(f"找不到文件: {source_path}")

    pages = _extract_pages(str(source))
    title = _title_from(source, pages)
    paper_id = _paper_id(str(source), title)

    root = papers_root() / paper_id
    pages_dir = root / _PAGES_DIRNAME
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    for number, text in enumerate(pages, start=1):
        page_path = pages_dir / f"{number:04d}.txt"
        with open(page_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    meta = {
        "id": paper_id,
        "title": title,
        "source_path": str(source.resolve()),
        "file_name": source.name,
        "page_count": len(pages),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_json(root / _META_FILENAME, meta)
    _rebuild_index()
    return meta


def _rebuild_index() -> None:
    """重建论文索引。索引只是加速用的缓存，坏了也不影响逐篇读取。"""
    entries = []
    root = papers_root()
    if root.is_dir():
        for item in sorted(root.iterdir()):
            meta = _read_json(item / _META_FILENAME)
            if isinstance(meta, dict) and meta.get("id"):
                entries.append(meta)
    try:
        _write_json(root / _INDEX_FILENAME, {"papers": entries})
    except OSError:
        pass


def list_papers() -> list[dict]:
    """列出论文库中的论文。"""
    root = papers_root()
    if not root.is_dir():
        return []
    papers = []
    for item in sorted(root.iterdir()):
        if not item.is_dir():
            continue
        meta = _read_json(item / _META_FILENAME)
        if isinstance(meta, dict) and meta.get("id"):
            papers.append(meta)
    return papers


def get_paper(paper_id: str) -> dict | None:
    """取一篇论文的元数据。"""
    meta = _read_json(papers_root() / paper_id / _META_FILENAME)
    return meta if isinstance(meta, dict) else None


def page_count(paper_id: str) -> int:
    """论文页数。"""
    meta = get_paper(paper_id)
    return int(meta.get("page_count") or 0) if meta else 0


def page_text(paper_id: str, page: int) -> str:
    """读取某篇论文某一页的原文。"""
    meta = get_paper(paper_id)
    if meta is None:
        raise PaperError(f"论文库中没有这篇论文: {paper_id}")
    total = int(meta.get("page_count") or 0)
    if page < 1 or page > total:
        raise PaperError(f"页码超出范围: {page}（共 {total} 页）")
    path = papers_root() / paper_id / _PAGES_DIRNAME / f"{page:04d}.txt"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise PaperError(f"读取第 {page} 页失败: {exc}") from exc


def all_pages(paper_id: str) -> list[str]:
    """论文的全部页面原文。"""
    total = page_count(paper_id)
    return [page_text(paper_id, number) for number in range(1, total + 1)]
