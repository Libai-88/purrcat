"""把拉回来的条目落进本机库，并留下来源凭据。

**落库与凭据是一起的**：说不清从哪来的东西不进库。
先写凭据再落库——反过来万一落库失败，就留下一条指向空处的凭据。

落进去之后，这条东西就能被研究记录当证据引：
论文进论文库（可逐页读原文、引文可逐字核对），数据进数据集库。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile

from src.connectors import provenance
from src.connectors.catalog import PullError
from src.connectors.pull import fetch
from src.data import library as data_library
from src.papers import library as paper_library


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _record_payload(items: list[dict]) -> bytes:
    """条目列表落成一份可归档的 JSON。

    归一后的条目用 JSON 存：既有结构，又能被人读懂、能被别的工具吃。
    """
    return json.dumps(
        {"schema_version": 1, "records": items}, ensure_ascii=False, indent=2
    ).encode("utf-8")


def _paper_payload(item: dict) -> bytes:
    """一篇论文的题录落成 JSON（连同原文链接）。"""
    return json.dumps(
        {"schema_version": 1, "record": item}, ensure_ascii=False, indent=2
    ).encode("utf-8")


def land_metadata(
    connector_id: str,
    query: str,
    count: int = 10,
    fetch_fn=None,
) -> dict:
    """拉一批题录，落成数据集库里的一个数据集，并留凭据。

    题录落成**数据集**而不是论文：论文进论文库要的是 PDF 原文，
    这里只有元数据。当成论文塞进论文库，会让人以为能读到原文。
    """
    items = (fetch_fn or fetch)(connector_id, query, count)
    if not items:
        raise PullError("no_results", f"没有拿到任何条目：{query}")

    payload = _record_payload(items)
    digest = _sha256_bytes(payload)

    with tempfile.TemporaryDirectory(prefix="purrcat-connector-") as tmp:
        staged = os.path.join(tmp, "records.json")
        with open(staged, "wb") as handle:
            handle.write(payload)
        imported = data_library.import_dataset(
            staged,
            name=f"{connector_id}-{query[:40]}.json",
            kind="dataset",
            source=f"{connector_id}:{query}",
            license_name="见来源站点",
        )

    asset = imported["asset"]
    dataset = imported["dataset"]
    record = provenance.build(
        connector_id=connector_id,
        request={"query": query, "count": count},
        content_sha256=digest,
        content_bytes=len(payload),
        landed="datasets",
        landed_id=dataset["id"],
        record_count=len(items),
        source_refs=[str(item.get("url") or "") for item in items if item.get("url")],
    )
    provenance.save(record)

    return {
        "provenance": record,
        "dataset": dataset,
        "asset": asset,
        "records": items,
    }


def land_paper(connector_id: str, pdf_url: str, title: str = "") -> dict:
    """把一篇论文的 PDF 原文拉下来，进论文库，并留凭据。

    论文进论文库之后，研究记录才能引它的原文——
    引文必须逐字出现在论文库那一页，这就是这条路的意义。
    """
    if not pdf_url:
        raise PullError("no_results", "这篇没有可下载的原文链接。")

    from src.connectors.pull import _fetch

    payload = _fetch(pdf_url)
    if not payload.startswith(b"%PDF"):
        raise PullError("bad_shape", f"拉下来的不是 PDF（前几个字节：{payload[:8]!r}）")
    digest = _sha256_bytes(payload)

    with tempfile.TemporaryDirectory(prefix="purrcat-connector-") as tmp:
        staged = os.path.join(tmp, "paper.pdf")
        with open(staged, "wb") as handle:
            handle.write(payload)
        meta = paper_library.import_paper(staged)

    record = provenance.build(
        connector_id=connector_id,
        request={"pdf_url": pdf_url},
        content_sha256=digest,
        content_bytes=len(payload),
        landed="papers",
        landed_id=meta["id"],
        record_count=1,
        source_refs=[pdf_url],
    )
    provenance.save(record)

    return {"provenance": record, "paper": meta}


def search(connector_id: str, query: str, count: int = 10, fetch_fn=None) -> dict:
    """只检索，不落库。

    检索结果本身也是**候选**，不是结论——所以这里不写凭据，
    凭据是「真的拉下来并入库了」才有的。
    """
    items = (fetch_fn or fetch)(connector_id, query, count)
    if not items:
        raise PullError("no_results", f"没有匹配「{query}」的结果")
    return {"connector_id": connector_id, "query": query, "records": items}
