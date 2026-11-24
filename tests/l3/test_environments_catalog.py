"""环境能力词表的静态约束（SPEC-034 AC-4）。"""

from __future__ import annotations

from src.environments.catalog import CAPABILITY_IDS, READINESS_VALUES

EXPECTED_CAPABILITIES = ("process", "batch", "http", "terminal")
EXPECTED_READINESS = ("ready", "missing", "unknown")


def test_capability_vocabulary_is_frozen():
    """能力词表冻结：加能力要显式决定，不能顺手。"""
    assert CAPABILITY_IDS == EXPECTED_CAPABILITIES


def test_readiness_vocabulary_is_frozen():
    """就绪度必须保持三态。"""
    assert READINESS_VALUES == EXPECTED_READINESS
