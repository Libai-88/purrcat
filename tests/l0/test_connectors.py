"""科研连接器：目录、拉取归一、来源凭据（SPEC-033）。

这些用例**不打真实站点**：用假的 HTTP 响应喂给归一函数，
测的是「各源真实的字段形态能不能被正确归一」与「凭据该带什么、不该带什么」。
"""

from __future__ import annotations

import json

import pytest

from src.connectors import catalog, provenance, pull
from src.connectors.catalog import (
    FAIL_BAD_SHAPE,
    FAIL_NO_RESULTS,
    FAIL_UNREACHABLE,
    KIND_METADATA,
    KIND_PAPER,
)
from src.connectors.catalog import ConnectorError, PullError


@pytest.fixture
def connector_home(tmp_path, monkeypatch):
    """把凭据目录指向临时位置。"""
    monkeypatch.setattr(
        provenance, "provenance_root", lambda: str(tmp_path / "provenance")
    )
    return tmp_path


def _fake_fetch(payload: bytes):
    """造一个假的 _fetch，返回定长响应。"""

    def _fetch(url, source="", **kwargs):
        return payload

    return _fetch


# ---------- 目录 ----------


def test_catalog_is_a_closed_vocabulary():
    """未登记的源不能被拉取。"""
    assert catalog.connector_ids()
    with pytest.raises(ConnectorError):
        catalog.get_connector("not-a-source")


def test_catalog_entries_declare_their_shape():
    for item in catalog.list_connectors():
        assert item["id"]
        assert item["name"]
        assert item["description"]
        assert item["kinds"]
        for kind in item["kinds"]:
            assert kind in catalog.KIND_VALUES
        assert item["auth"] in catalog.AUTH_VALUES
        assert item["lands"] in catalog.LAND_VALUES


def test_catalog_ids_are_unique():
    ids = [item["id"] for item in catalog.list_connectors()]
    assert len(ids) == len(set(ids))


def test_supports_tells_what_a_source_can_pull():
    assert catalog.supports("arxiv", KIND_METADATA)
    assert catalog.supports("arxiv", KIND_PAPER)
    assert not catalog.supports("zenodo", KIND_PAPER)


# ---------- 归一：各源的真实字段形态 ----------

ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
<opensearch:totalResults>189339</opensearch:totalResults>
<entry>
  <id>http://arxiv.org/abs/2202.07171v1</id>
  <title>Investigating the genomic background of CRISPR-Cas genomes</title>
  <summary>  We report studies of the genomic background.  </summary>
  <published>2022-02-14T10:00:00Z</published>
  <author><name>Hyunjin Shim</name></author>
  <link href="https://arxiv.org/abs/2202.07171v1" rel="alternate" type="text/html"/>
  <link href="https://arxiv.org/pdf/2202.07171v1" rel="related" type="application/pdf" title="pdf"/>
</entry>
</feed>"""


def test_arxiv_atom_is_normalized(monkeypatch):
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(ARXIV_ATOM.encode()))

    items = pull.fetch_arxiv("crispr", 1)

    assert len(items) == 1
    item = items[0]
    assert item["source_id"] == "2202.07171v1"
    assert item["title"] == "Investigating the genomic background of CRISPR-Cas genomes"
    assert item["authors"] == ["Hyunjin Shim"]
    assert item["year"] == 2022
    assert item["pdf_url"] == "https://arxiv.org/pdf/2202.07171v1"
    assert item["url"].endswith("/abs/2202.07171v1")


OPENALEX_JSON = json.dumps(
    {
        "meta": {"count": 1},
        "results": [
            {
                "id": "https://openalex.org/W2239190724",
                "doi": "https://doi.org/10.1016/j.cell.2015.12.041",
                "title": "The Heroes of CRISPR",
                "display_name": "The Heroes of CRISPR",
                "publication_year": 2016,
                "primary_location": {
                    "landing_page_url": "https://doi.org/10.1016/j.cell.2015.12.041",
                    "pdf_url": "http://www.cell.com/paywall.pdf",
                    "source": {"display_name": "Cell"},
                },
                "content_urls": {
                    "pdf": "https://content.openalex.org/works/W2239190724.pdf"
                },
                "authorships": [{"author": {"display_name": "Eric S. Lander"}}],
            }
        ],
    }
).encode()


def test_openalex_authors_are_unwrapped(monkeypatch):
    """作者嵌在 ``authorships[].author.display_name``，不拆开就一个都拿不到。"""
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(OPENALEX_JSON))

    items = pull.fetch_openalex("crispr", 1)

    assert items[0]["authors"] == ["Eric S. Lander"]
    assert items[0]["year"] == 2016
    assert items[0]["venue"] == "Cell"


def test_openalex_prefers_the_free_full_text_pdf(monkeypatch):
    """``content_urls.pdf`` 免 key；``primary_location.pdf_url`` 常指向付费墙。"""
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(OPENALEX_JSON))

    items = pull.fetch_openalex("crispr", 1)

    assert items[0]["pdf_url"] == "https://content.openalex.org/works/W2239190724.pdf"


CROSSREF_JSON = json.dumps(
    {
        "status": "ok",
        "message": {
            "total-results": 1,
            "items": [
                {
                    "DOI": "10.1089/crispr.2018.29011.rba",
                    "title": ["Cultivating CRISPR"],
                    "container-title": ["The CRISPR Journal"],
                    "author": [{"given": "Kevin", "family": "Davies"}],
                    "published-print": {"date-parts": [[2018, 4]]},
                }
            ],
        },
    }
).encode()


def test_crossref_title_array_and_date_parts(monkeypatch):
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(CROSSREF_JSON))

    items = pull.fetch_crossref("crispr", 1)

    assert items[0]["title"] == "Cultivating CRISPR"
    assert items[0]["authors"] == ["Kevin Davies"]
    assert items[0]["year"] == 2018
    assert items[0]["url"] == "https://doi.org/10.1089/crispr.2018.29011.rba"


PUBMED_SEARCH = json.dumps(
    {"esearchresult": {"count": "73019", "idlist": ["43075256"]}}
).encode()

PUBMED_FETCH = """<?xml version="1.0" ?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID Version="1">43075256</PMID>
<Article>
<ArticleTitle>The growth period of cotton</ArticleTitle>
<ELocationID EIdType="doi" ValidYN="Y">10.3389/fpls.2026.1979403</ELocationID>
<Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue><Title>Frontiers in plant science</Title></Journal>
<AuthorList><Author><ForeName>Nan</ForeName><LastName>Hong</LastName></Author></AuthorList>
<Abstract><AbstractText>  The growth period.  </AbstractText></Abstract>
</Article>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.3389/fpls.2026.1979403</ArticleId></ArticleIdList></PubmedData>
</MedlineCitation></PubmedArticle></PubmedArticleSet>"""


def test_pubmed_two_step_search_then_fetch(monkeypatch):
    """PubMed 是两步：esearch 拿 PMID，efetch 拿题录。"""
    calls = []

    def _fetch(url, source="", **kwargs):
        calls.append(url)
        return PUBMED_SEARCH if "esearch" in url else PUBMED_FETCH.encode()

    monkeypatch.setattr(pull, "_fetch", _fetch)

    items = pull.fetch_pubmed("crispr", 1)

    assert len(calls) == 2
    assert "esearch" in calls[0]
    assert "efetch" in calls[1]
    assert items[0]["source_id"] == "43075256"
    assert items[0]["doi"] == "10.3389/fpls.2026.1979403"
    assert items[0]["year"] == 2026
    assert items[0]["authors"] == ["Nan Hong"]


def test_pubmed_sends_tool_and_email(monkeypatch):
    """NCBI 要求每个请求都带 tool 与 email，不带会被限流。"""
    calls = []

    def _fetch(url, source="", **kwargs):
        calls.append(url)
        return PUBMED_SEARCH if "esearch" in url else PUBMED_FETCH.encode()

    monkeypatch.setattr(pull, "_fetch", _fetch)
    pull.fetch_pubmed("crispr", 1)

    assert "tool=purrcat" in calls[0]
    assert "email=" in calls[0]


ZENODO_JSON = json.dumps(
    {
        "hits": {
            "total": 1,
            "hits": [
                {
                    "id": 7042164,
                    "doi": "10.5281/zenodo.7042164",
                    "doi_url": "https://doi.org/10.5281/zenodo.7042164",
                    "metadata": {
                        "title": "Precomputed gRNAs",
                        "publication_date": "2022-01-01",
                        "creators": [{"name": "Fortin, Jean-Philippe"}],
                        "description": "gRNA files",
                    },
                    "files": [
                        {
                            "key": "mouse.txt",
                            "size": 177749839,
                            "links": {
                                "self": "https://zenodo.org/api/records/7042164/files/mouse.txt/content"
                            },
                        }
                    ],
                }
            ],
        }
    }
).encode()


def test_zenodo_file_url_and_metadata(monkeypatch):
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(ZENODO_JSON))

    items = pull.fetch_zenodo("crispr", 1)

    assert items[0]["source_id"] == "7042164"
    assert items[0]["title"] == "Precomputed gRNAs"
    assert items[0]["year"] == 2022
    assert items[0]["pdf_url"].endswith("/files/mouse.txt/content")
    assert items[0]["url"] == "https://doi.org/10.5281/zenodo.7042164"


def test_zenodo_record_without_files_is_not_an_error(monkeypatch):
    """真找到过 files 为空的记录，不能假设一定有附件。"""
    payload = json.loads(ZENODO_JSON.decode())
    payload["hits"]["hits"][0]["files"] = []
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(json.dumps(payload).encode()))

    items = pull.fetch_zenodo("crispr", 1)

    assert items[0]["pdf_url"] == ""
    assert items[0]["file_name"] == ""


UNIPROT_JSON = json.dumps(
    {
        "results": [
            {
                "entryType": "UniProtKB reviewed (Swiss-Prot)",
                "primaryAccession": "P01308",
                "uniProtkbId": "INS_HUMAN",
                "organism": {"scientificName": "Homo sapiens"},
                "proteinDescription": {
                    "recommendedName": {"fullName": {"value": "Insulin"}}
                },
                "genes": [{"geneName": {"value": "INS"}}],
                "references": [
                    {
                        "citation": {
                            "citationCrossReferences": [
                                {"database": "PubMed", "id": "6243748"},
                                {"database": "DOI", "id": "10.1038/284026a0"},
                            ]
                        }
                    }
                ],
            }
        ]
    }
).encode()


def test_uniprot_doi_comes_from_references(monkeypatch):
    """DOI 不在交叉引用里，在 references[].citation.citationCrossReferences。"""
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(UNIPROT_JSON))

    items = pull.fetch_uniprot("insulin", 1)

    assert items[0]["source_id"] == "P01308"
    assert items[0]["title"] == "Insulin"
    assert items[0]["doi"] == "10.1038/284026a0"
    assert items[0]["genes"] == ["INS"]


# ---------- 失败分类 ----------


def test_unparsable_payload_is_a_shape_failure(monkeypatch):
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(b"not xml at all"))

    with pytest.raises(PullError) as excinfo:
        pull.fetch_arxiv("crispr", 1)
    assert excinfo.value.kind == FAIL_BAD_SHAPE


def test_empty_result_set_is_reported_as_no_results(monkeypatch):
    payload = json.dumps({"hits": {"total": 0, "hits": []}}).encode()
    monkeypatch.setattr(pull, "_fetch", _fake_fetch(payload))

    with pytest.raises(PullError) as excinfo:
        pull.fetch_zenodo("nothing", 1)
    assert excinfo.value.kind == FAIL_NO_RESULTS


def test_unreachable_is_its_own_kind():
    error = PullError(FAIL_UNREACHABLE, "连不上")
    assert error.kind == FAIL_UNREACHABLE
    assert str(error) == "连不上"


# ---------- 来源凭据 ----------


def test_provenance_records_where_it_came_from(connector_home):
    record = provenance.build(
        connector_id="arxiv",
        request={"query": "crispr", "count": 10},
        content_sha256="abc123",
        content_bytes=2048,
        landed="datasets",
        landed_id="ds-123",
        record_count=7,
        source_refs=["https://arxiv.org/abs/2202.07171v1"],
    )

    assert record["connector_id"] == "arxiv"
    assert record["request"] == {"query": "crispr", "count": 10}
    assert record["content_sha256"] == "abc123"
    assert record["landed_id"] == "ds-123"
    assert record["retrieved_at"]


def test_provenance_has_no_acceptance_or_verification(connector_home):
    """AC-4：凭据只说明出处，不说明可信。"""
    record = provenance.build(
        connector_id="arxiv", request={"query": "crispr"}, landed="datasets"
    )

    assert "acceptance" not in record
    assert "verification" not in record


def test_provenance_survives_a_round_trip(connector_home):
    record = provenance.build(
        connector_id="openalex",
        request={"query": "crispr"},
        content_sha256="deadbeef",
        landed="datasets",
        landed_id="ds-9",
    )
    provenance.save(record)

    loaded = provenance.get(record["provenance_id"])

    assert loaded["content_sha256"] == "deadbeef"
    assert loaded["landed_id"] == "ds-9"


def test_provenance_is_listed_newest_first(connector_home):
    first = provenance.build(connector_id="arxiv", request={"query": "a"})
    first["retrieved_at"] = "2026-01-01T00:00:00+00:00"
    provenance.save(first)
    second = provenance.build(connector_id="arxiv", request={"query": "b"})
    second["retrieved_at"] = "2026-02-01T00:00:00+00:00"
    provenance.save(second)

    listed = provenance.list_all()

    assert listed[0]["provenance_id"] == second["provenance_id"]


def test_provenance_can_be_found_by_landed_object(connector_home):
    record = provenance.build(
        connector_id="zenodo",
        request={"query": "x"},
        landed="datasets",
        landed_id="ds-42",
    )
    provenance.save(record)

    found = provenance.for_landed("ds-42")

    assert found["provenance_id"] == record["provenance_id"]
