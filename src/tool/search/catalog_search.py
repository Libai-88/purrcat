"""科研技能目录检索：目录条目不在本地 skills 目录，但 Agent 仍需检索到它们。

索引与本地 Skill 索引分开，避免目录规模拖慢本地检索的启动路径。
稠密矩阵在后台构建并缓存到磁盘，构建完成前先用 BM25 应答，保证首次检索不卡顿。
"""

from __future__ import annotations

import os
import threading
import time

import numpy as np

from src.tool.search import _shared
from src.tool.search.semantic_utils import LocalEmbeddingSearcher
from src.utils import research_catalog
from src.utils.config import RESEARCH_CATALOG_INDEX_DIR

_DENSE_BUILD_WAIT = 120
_MATRIX_FILE = "matrix.npy"
_SIGNATURE_FILE = "signature.txt"


class CatalogSearcher:
    """目录条目的混合检索器（线程安全单例）。

    条目来源是科研技能目录，不是本地 skills 目录，因此这里的命中项都标记为
    ``installed=False``，供上层与本地已装技能区分。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._reset()
            return cls._instance

    def _reset(self) -> None:
        self.entries: list[dict] = []
        self.corpus: list[str] = []
        self.corpus_matrix = None
        self.bm25 = None
        self.embedding_searcher = LocalEmbeddingSearcher()
        self._signature = None
        self._dense_building = False

    # ---------- 索引生命周期 ----------

    def _refresh_entries(self) -> None:
        """目录内容变化时重建语料与 BM25 索引。"""
        signature = research_catalog.catalog_signature()
        if signature == self._signature and self.bm25 is not None:
            return
        self.entries = research_catalog.catalog_entries()
        self.corpus = [
            _shared.skill_document_text(
                entry["name"],
                f"{entry['description']} {entry['category_zh']}",
                "",
            )
            for entry in self.entries
        ]
        self.bm25 = _shared.build_bm25(self.corpus) if self.corpus else None
        self.corpus_matrix = None
        self._signature = signature

    def _load_cached_matrix(self, signature: str):
        """读取磁盘上缓存的稠密矩阵；签名不匹配或文件损坏时返回 None。"""
        matrix_path = os.path.join(RESEARCH_CATALOG_INDEX_DIR, _MATRIX_FILE)
        signature_path = os.path.join(RESEARCH_CATALOG_INDEX_DIR, _SIGNATURE_FILE)
        if not (os.path.isfile(matrix_path) and os.path.isfile(signature_path)):
            return None
        try:
            with open(signature_path, "r", encoding="utf-8") as handle:
                cached_signature = handle.read().strip()
            if cached_signature != signature:
                return None
            matrix = np.load(matrix_path)
        except (OSError, ValueError):
            return None
        if matrix.shape[0] != len(self.corpus):
            return None
        return matrix

    def _store_matrix(self, matrix, signature: str) -> None:
        """把稠密矩阵缓存到磁盘，供下次启动直接加载。"""
        try:
            os.makedirs(RESEARCH_CATALOG_INDEX_DIR, exist_ok=True)
            matrix_path = os.path.join(RESEARCH_CATALOG_INDEX_DIR, _MATRIX_FILE)
            signature_path = os.path.join(RESEARCH_CATALOG_INDEX_DIR, _SIGNATURE_FILE)
            np.save(matrix_path, matrix)
            with open(signature_path, "w", encoding="utf-8") as handle:
                handle.write(signature)
        except OSError:
            pass

    def build_dense_index(self) -> None:
        """构建稠密矩阵（同步）。语料为空时直接返回。"""
        self._refresh_entries()
        if not self.corpus:
            return
        if self._dense_building:
            # 已有后台构建在进行，等它完成而不是直接空手返回
            deadline = time.time() + _DENSE_BUILD_WAIT
            while self._dense_building and time.time() < deadline:
                time.sleep(0.2)
            return
        self._dense_building = True
        try:
            cached = self._load_cached_matrix(self._signature)
            if cached is not None:
                self.corpus_matrix = cached
                return
            matrix = self.embedding_searcher.encode(self.corpus)
            self.corpus_matrix = matrix
            self._store_matrix(matrix, self._signature)
        finally:
            self._dense_building = False

    def build_dense_index_async(self) -> None:
        """后台线程构建稠密矩阵；失败只记录，不影响检索。"""
        if self._dense_building:
            return

        def _worker():
            try:
                self.build_dense_index()
            except Exception as exc:
                print(f"[-] 科研技能目录向量构建失败: {exc}")

        threading.Thread(
            target=_worker, daemon=True, name="Research-Catalog-Vector-Build"
        ).start()

    # ---------- 检索 ----------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """检索目录条目；稠密矩阵未就绪时退化为 BM25。"""
        with self._lock:
            self._refresh_entries()
            entries = list(self.entries)
            matrix = self.corpus_matrix
            bm25 = self.bm25

        if not entries or not bm25:
            return []

        if matrix is None:
            # 稠密索引未就绪：BM25 对中文查询几乎无命中（跨语言无词面重叠），
            # 宁可同步等一次索引构建，也不要让 Agent 看到空结果。
            # 矩阵有磁盘缓存，二次启动只需几毫秒。
            try:
                self.build_dense_index()
                matrix = self.corpus_matrix
            except Exception as exc:
                print(f"[-] 科研技能目录索引构建失败: {exc}")

        raw_bm25 = bm25.get_scores(_shared.hybrid_tokenize(query))
        if matrix is not None:
            query_vector = self.embedding_searcher.encode([query])
            dense = self.embedding_searcher.calculate_similarity(query_vector, matrix)
            scores = _shared.hybrid_scores(dense, raw_bm25, clamp_negative=True)
        else:
            scores = np.array([max(float(s), 0.0) for s in raw_bm25])

        order = _shared.top_k_indices(scores, top_k)
        results = []
        for idx in order:
            score = float(scores[idx])
            if score <= 0:
                continue
            entry = entries[idx]
            results.append(
                {
                    "score": round(score, 4),
                    "skill": {
                        "name": entry["name"],
                        "description": entry["description"],
                        "dir_name": entry["name"],
                        "installed": False,
                        "category": entry["category"],
                        "category_zh": entry["category_zh"],
                        "license": entry["license"],
                        "source": entry["source"],
                    },
                }
            )
        return results


def search_catalog(query: str, top_k: int = 5) -> tuple[list[dict], str | None]:
    """科研技能目录检索入口；异常时返回空结果与错误说明。"""
    try:
        return CatalogSearcher().search(query, top_k), None
    except Exception as exc:
        return [], f"科研技能目录检索异常: {exc}"


def rebuild_catalog_index_async() -> None:
    """启动时触发一次后台构建，让首次检索大概率命中稠密索引。"""
    try:
        CatalogSearcher().build_dense_index_async()
    except Exception as exc:
        print(f"[-] 科研技能目录索引启动失败: {exc}")
