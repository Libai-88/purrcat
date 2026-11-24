"""论文库与证据核对。

导入 PDF 后分页落盘，Agent 可以按页读原文、把引文定位到具体页码与上下文，
并核对自己的断言是否真有原文支撑。
"""

from src.papers.library import (
    PaperError,
    all_pages,
    get_paper,
    import_paper,
    list_papers,
    page_count,
    page_text,
    papers_root,
)
from src.papers.records import (
    ACCEPTANCE_ACCEPTED,
    ACCEPTANCE_NEEDS_REVIEW,
    ACCEPTANCE_REJECTED,
    ACCEPTANCE_UNVERIFIED,
    RecordError,
    build_record,
    get_record,
    list_records,
    save_record,
)
from src.papers.verify import NOT_FOUND, PARTIAL, SUPPORTED, verify_claim

__all__ = [
    "ACCEPTANCE_ACCEPTED",
    "ACCEPTANCE_NEEDS_REVIEW",
    "ACCEPTANCE_REJECTED",
    "ACCEPTANCE_UNVERIFIED",
    "PaperError",
    "RecordError",
    "build_record",
    "get_record",
    "list_records",
    "save_record",
    "NOT_FOUND",
    "PARTIAL",
    "SUPPORTED",
    "all_pages",
    "get_paper",
    "import_paper",
    "list_papers",
    "page_count",
    "page_text",
    "papers_root",
    "verify_claim",
]
