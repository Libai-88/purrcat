"""连接器的拉取运行时：把外部数据源的结果，变成能进本机库的东西。

每个源一个 ``fetch_*`` 函数，负责三件事：

1. 按该源真实的接口形态发请求（字段名以实际返回为准）；
2. 把返回**归一**成同一套条目：``{source_id, title, authors, year, url, abstract, pdf_url, doi}``；
3. 报错时说明是哪一类失败（连不上 / 没授权 / 限流 / 没结果 / 形态不对）。

**归一之后才进库。** 各源字段名各不相同（OpenAlex 叫 ``display_name``、
Crossref 叫 ``title`` 且是数组、arXiv 是 Atom XML），不进库就永远对不上。
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ElementTree

from src.connectors.catalog import PullError
from src.utils.http_fetch import FetchError, fetch_bytes

# 这些源都是公开接口，带上联系方式是它们的礼貌要求，也换更宽的限额。
USER_AGENT = "PurrCat/0.1 (research tool; mailto:purrcat@localhost)"
DEFAULT_MAILTO = "purrcat@localhost"

# NCBI 要求每个请求都带 tool 与 email；不带会被限流。
TOOL_NAME = "purrcat"
CONTACT_EMAIL = "purrcat@localhost"

MAX_RESULTS = 25
MAX_RESULTS_CAP = 100

# arXiv 的使用条款要求「每三秒不超过一次请求，且同时只开一条连接」。
# 这里按源记住上一次请求时间，到点就等一下——不是礼貌问题，是条款。
_MIN_INTERVAL = {"arxiv": 3.0}
_last_request: dict[str, float] = {}
_interval_lock = threading.Lock()


def _clamp(count: int) -> int:
    return max(1, min(int(count or 10), MAX_RESULTS_CAP))


def _respect_interval(source: str) -> None:
    """按源的最小请求间隔等一下。

    arXiv 的条款要求每三秒不超过一次请求。别的源没有硬性要求，
    不为了「显得礼貌」而让用户干等。
    """
    interval = _MIN_INTERVAL.get(source)
    if not interval:
        return
    import time

    with _interval_lock:
        last = _last_request.get(source, 0.0)
        wait = interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request[source] = time.monotonic()


def _fetch(url: str, source: str = "") -> bytes:
    """取一个 URL，失败时按类型分类。

    ``source`` 给了就按该源的最小请求间隔等一下（arXiv 要求三秒一次）。
    """
    _respect_interval(source)
    try:
        return fetch_bytes(
            url,
            user_agent=USER_AGENT,
            timeout=60,
            retries=3,
            wait_for_limit=True,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PullError(
                "no_auth", f"这个源需要授权（HTTP {exc.code}）：{url}"
            ) from exc
        if exc.code == 429:
            raise PullError(
                "rate_limited", f"被源站限流了（HTTP 429），等一会儿再试：{url}"
            ) from exc
        if exc.code == 404:
            raise PullError(
                "no_results", f"源站说没有这个对象（HTTP 404）：{url}"
            ) from exc
        raise PullError("unreachable", f"源站返回了 HTTP {exc.code}：{url}") from exc
    except FetchError as exc:
        raise PullError("unreachable", f"取不到这个源：{exc}") from exc
    except Exception as exc:
        raise PullError("unreachable", f"取不到这个源：{exc}") from exc


def _text(value) -> str:
    """把可能缺失、可能是列表的字段压成一行文本。"""
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    return str(value).strip()


def _authors(names) -> list[str]:
    """把各源的作者字段压成字符串列表。

    各源的作者嵌套深度不一样：OpenAlex 是
    ``authorships[].author.display_name``，Crossref 是 ``author[].given/family``，
    Zenodo 是 ``creators[].name``。这里把几种形态都认一遍。
    """
    out = []
    for item in names or []:
        if isinstance(item, str):
            if item.strip():
                out.append(item.strip())
        elif isinstance(item, dict):
            # OpenAlex：作者信息嵌在 author 子对象里
            nested = item.get("author")
            if isinstance(nested, dict):
                item = nested
            name = item.get("name") or item.get("display_name")
            if not name:
                family = item.get("family") or item.get("last")
                given = item.get("given") or item.get("first")
                if family or given:
                    name = " ".join(x for x in (given, family) if x)
            if name:
                out.append(str(name))
    return out


def _year(value) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


# —— arXiv ——

_ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def fetch_arxiv(query: str, count: int = 10) -> list[dict]:
    """arXiv：返回 Atom XML 里的 entry，归一成条目。"""
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}" if query else "all:*",
            "start": 0,
            "max_results": _clamp(count),
        }
    )
    raw = _fetch(f"https://export.arxiv.org/api/query?{params}", source="arxiv")
    try:
        feed = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise PullError("bad_shape", f"arXiv 返回的不是能解析的 Atom：{exc}") from exc

    entries = feed.findall("atom:entry", _ARXIV_NS)
    if not entries:
        raise PullError("no_results", f"arXiv 上没有匹配「{query}」的结果")

    items = []
    for entry in entries:
        abs_url = _text(entry.findtext("atom:id", "", _ARXIV_NS))
        source_id = abs_url.rsplit("/abs/", 1)[-1] if "/abs/" in abs_url else abs_url
        pdf_url = ""
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
        published = entry.findtext("atom:published", "", _ARXIV_NS)
        items.append(
            {
                "source_id": source_id,
                "title": " ".join(
                    _text(entry.findtext("atom:title", "", _ARXIV_NS)).split()
                ),
                "authors": _authors(
                    [
                        {"name": _text(a.findtext("atom:name", "", _ARXIV_NS))}
                        for a in entry.findall("atom:author", _ARXIV_NS)
                    ]
                ),
                "year": _year(published),
                "url": abs_url,
                "abstract": " ".join(
                    _text(entry.findtext("atom:summary", "", _ARXIV_NS)).split()
                ),
                "pdf_url": pdf_url,
                "doi": "",
                "venue": "arXiv 预印本",
            }
        )
    return items


# —— OpenAlex ——


def fetch_openalex(query: str, count: int = 10) -> list[dict]:
    """OpenAlex：开放的学术图谱。"""
    params = urllib.parse.urlencode(
        {
            "search": query,
            "per-page": _clamp(count),
            "mailto": DEFAULT_MAILTO,
        }
    )
    raw = _fetch(f"https://api.openalex.org/works?{params}", source="openalex")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PullError("bad_shape", f"OpenAlex 返回的不是 JSON：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise PullError("bad_shape", "OpenAlex 返回的 JSON 里没有 results 数组")

    results = data["results"]
    if not results:
        raise PullError("no_results", f"OpenAlex 上没有匹配「{query}」的结果")

    items = []
    for work in results:
        if not isinstance(work, dict):
            continue
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        # content_urls.pdf 是免 key 的全文 PDF；primary_location.pdf_url
        # 常常指向出版商付费墙，反而拿不到。
        content_urls = work.get("content_urls") or {}
        pdf_url = str(content_urls.get("pdf") or "") or str(
            location.get("pdf_url") or ""
        )
        items.append(
            {
                "source_id": str(work.get("id") or "").rsplit("/", 1)[-1],
                "title": _text(work.get("title") or work.get("display_name")),
                "authors": _authors(work.get("authorships")),
                "year": _year(work.get("publication_year")),
                "url": str(location.get("landing_page_url") or work.get("id") or ""),
                "abstract": "",
                "pdf_url": pdf_url,
                "doi": str(work.get("doi") or ""),
                "venue": _text(source.get("display_name")),
            }
        )
    return items


# —— Crossref ——


def _crossref_year(work: dict) -> int | None:
    """Crossref 的年份在 date-parts 里，可能在 published-print / published-online / issued。"""
    for key in ("published-print", "published-online", "issued", "created"):
        block = work.get(key)
        if not isinstance(block, dict):
            continue
        parts = block.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
        ):
            year = _year(parts[0][0])
            if year:
                return year
    return None


def fetch_crossref(query: str, count: int = 10) -> list[dict]:
    """Crossref：出版商登记的 DOI 题录。"""
    params = urllib.parse.urlencode(
        {"query": query, "rows": _clamp(count), "mailto": DEFAULT_MAILTO}
    )
    raw = _fetch(f"https://api.crossref.org/works?{params}", source="crossref")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PullError("bad_shape", f"Crossref 返回的不是 JSON：{exc}") from exc
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("items"), list):
        raise PullError("bad_shape", "Crossref 返回的 JSON 里没有 message.items 数组")

    results = message["items"]
    if not results:
        raise PullError("no_results", f"Crossref 上没有匹配「{query}」的结果")

    items = []
    for work in results:
        if not isinstance(work, dict):
            continue
        doi = str(work.get("DOI") or "")
        items.append(
            {
                "source_id": doi,
                "title": _text(work.get("title")),
                "authors": _authors(work.get("author")),
                "year": _crossref_year(work),
                "url": f"https://doi.org/{doi}" if doi else "",
                "abstract": "",
                "pdf_url": "",
                "doi": doi,
                "venue": _text(work.get("container-title")),
            }
        )
    return items


# —— PubMed ——


def fetch_pubmed(query: str, count: int = 10) -> list[dict]:
    """PubMed：生物医学文献。esearch 拿 PMID，efetch 拿题录。

    NCBI 要求每个请求都带 ``tool`` 与 ``email``；不带会被限流。
    """
    params = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "term": query,
            "retmax": _clamp(count),
            "retmode": "json",
            "tool": TOOL_NAME,
            "email": CONTACT_EMAIL,
        }
    )
    raw = _fetch(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{params}",
        source="pubmed",
    )
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PullError("bad_shape", f"PubMed 返回的不是 JSON：{exc}") from exc
    result = data.get("esearchresult") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise PullError("bad_shape", "PubMed 返回的 JSON 里没有 esearchresult")

    ids = result.get("idlist") or []
    if not ids:
        raise PullError("no_results", f"PubMed 上没有匹配「{query}」的结果")

    fetch_params = urllib.parse.urlencode(
        {
            "db": "pubmed",
            "id": ",".join(str(i) for i in ids),
            "retmode": "xml",
            "tool": TOOL_NAME,
            "email": CONTACT_EMAIL,
        }
    )
    xml_raw = _fetch(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?{fetch_params}",
        source="pubmed",
    )
    try:
        root = ElementTree.fromstring(xml_raw)
    except ElementTree.ParseError as exc:
        raise PullError("bad_shape", f"PubMed 返回的不是能解析的 XML：{exc}") from exc

    items = []
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article.findtext(".//PMID", "", {"": ""}))
        title = " ".join(_text(article.findtext(".//ArticleTitle")).split())
        # DOI 在 ArticleIdList 里最干净：IdType="doi"
        doi = ""
        for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid.text)
                break
        if not doi:
            for eid in article.findall(".//ELocationID"):
                if eid.get("EIdType") == "doi":
                    doi = _text(eid.text)
                    break
        year = None
        for path in (
            ".//Article/ArticleDate/Year",
            ".//Journal/JournalIssue/PubDate/Year",
        ):
            year = _year(article.findtext(path))
            if year:
                break
        items.append(
            {
                "source_id": pmid,
                "title": title,
                "authors": _authors(
                    [
                        {
                            "given": _text(a.findtext("ForeName")),
                            "family": _text(a.findtext("LastName")),
                        }
                        for a in article.findall(".//AuthorList/Author")
                    ]
                ),
                "year": year,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                "abstract": " ".join(
                    " ".join(_text(node.text).split())
                    for node in article.findall(".//AbstractText")
                ),
                "pdf_url": "",
                "doi": doi,
                "venue": _text(article.findtext(".//Journal/Title")),
            }
        )
    if not items:
        raise PullError("bad_shape", "PubMed 的 XML 里没有可读的条目")
    return items


# —— Zenodo ——


def fetch_zenodo(query: str, count: int = 10) -> list[dict]:
    """Zenodo：开放数据仓库。"""
    params = urllib.parse.urlencode({"q": query, "size": _clamp(count)})
    raw = _fetch(f"https://zenodo.org/api/records?{params}", source="zenodo")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PullError("bad_shape", f"Zenodo 返回的不是 JSON：{exc}") from exc
    hits = data.get("hits") if isinstance(data, dict) else None
    records = hits.get("hits") if isinstance(hits, dict) else None
    if not isinstance(records, list):
        raise PullError("bad_shape", "Zenodo 返回的 JSON 里没有 hits.hits 数组")
    if not records:
        raise PullError("no_results", f"Zenodo 上没有匹配「{query}」的结果")

    items = []
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") or {}
        doi = str(record.get("doi") or "")
        # files 可能为空——真找到过没有附件的记录，不能假设一定有。
        file_url = ""
        file_name = ""
        file_size = 0
        files = record.get("files") or []
        if files and isinstance(files[0], dict):
            file_url = str((files[0].get("links") or {}).get("self") or "")
            file_name = str(files[0].get("key") or "")
            try:
                file_size = int(files[0].get("size") or 0)
            except (TypeError, ValueError):
                file_size = 0
        items.append(
            {
                "source_id": str(record.get("id") or doi),
                "title": _text(metadata.get("title")),
                "authors": _authors(metadata.get("creators")),
                "year": _year(metadata.get("publication_date")),
                "url": str(record.get("doi_url") or "")
                or (f"https://doi.org/{doi}" if doi else ""),
                "abstract": _text(metadata.get("description"))[:2000],
                "pdf_url": file_url,
                "doi": doi,
                "venue": "Zenodo",
                "file_name": file_name,
                "file_size": file_size,
            }
        )
    return items


# —— UniProt ——


def _uniprot_doi(entry: dict) -> str:
    """UniProt 的 DOI 不在交叉引用里，而在参考文献的 citation 里。

    ``uniProtKBCrossReferences`` 里没有 DOI；要翻
    ``references[].citation.citationCrossReferences[]``，挑 ``database=="DOI"`` 的那条。
    """
    for reference in entry.get("references") or []:
        if not isinstance(reference, dict):
            continue
        citation = reference.get("citation") or {}
        for cross in citation.get("citationCrossReferences") or []:
            if isinstance(cross, dict) and cross.get("database") == "DOI":
                return _text(cross.get("id"))
    return ""


def _uniprot_title(entry: dict) -> str:
    """蛋白的推荐名：``proteinDescription.recommendedName.fullName.value``。"""
    description = entry.get("proteinDescription") or {}
    recommended = description.get("recommendedName") or {}
    full = recommended.get("fullName") or {}
    value = _text(full.get("value"))
    if value:
        return value
    submitted = description.get("submissionNames") or []
    for item in submitted:
        if isinstance(item, dict):
            inner = (item.get("fullName") or {}).get("value")
            if inner:
                return _text(inner)
    return ""


def fetch_uniprot(query: str, count: int = 10) -> list[dict]:
    """UniProt：蛋白质与基因的权威条目。"""
    params = urllib.parse.urlencode(
        {"query": query, "size": _clamp(count), "format": "json"}
    )
    raw = _fetch(
        f"https://rest.uniprot.org/uniprotkb/search?{params}", source="uniprot"
    )
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise PullError("bad_shape", f"UniProt 返回的不是 JSON：{exc}") from exc
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise PullError("bad_shape", "UniProt 返回的 JSON 里没有 results 数组")
    if not results:
        raise PullError("no_results", f"UniProt 上没有匹配「{query}」的结果")

    items = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        organism = entry.get("organism") or {}
        genes = entry.get("genes") or []
        gene_names = [
            _text(g.get("geneName", {}).get("value"))
            for g in genes
            if isinstance(g, dict) and isinstance(g.get("geneName"), dict)
        ]
        accession = str(entry.get("primaryAccession") or "")
        doi = _uniprot_doi(entry)
        items.append(
            {
                "source_id": accession,
                "title": _uniprot_title(entry),
                "authors": [],
                "year": None,
                "url": f"https://www.uniprot.org/uniprotkb/{accession}"
                if accession
                else "",
                "abstract": "",
                "pdf_url": "",
                "doi": doi,
                "venue": "UniProt",
                "organism": _text(organism.get("scientificName")),
                "genes": [name for name in gene_names if name],
            }
        )
    return items


# —— 分派 ——

_FETCHERS = {
    "arxiv": fetch_arxiv,
    "openalex": fetch_openalex,
    "crossref": fetch_crossref,
    "pubmed": fetch_pubmed,
    "zenodo": fetch_zenodo,
    "uniprot": fetch_uniprot,
}


def fetch(connector_id: str, query: str, count: int = 10) -> list[dict]:
    """按连接器 id 拉一批条目。"""
    fetcher = _FETCHERS.get(connector_id)
    if fetcher is None:
        raise PullError("unreachable", f"这个连接器还没有接上：{connector_id}")
    query = (query or "").strip()
    if not query:
        raise PullError("no_results", "要拉点什么？给个检索词。")
    return fetcher(query, count)
