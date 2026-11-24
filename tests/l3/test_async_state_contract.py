"""前端与后端读的是同一份状态词表（SPEC-031 AC-4）。

词表只写在 ``ui/web-minimal/assets/async-state.js`` 里：Python 从那段 JSON 读，
浏览器加载同一个文件。契约测试保证两边不会各自漂移。
"""

from __future__ import annotations

import json
import re

from src.utils import async_state

JS_PATH = "ui/web-minimal/assets/async-state.js"

_SPEC_RE = re.compile(
    r"/\*\s*purrcat:async-state:spec\s*\*/(.*?)/\*\s*purrcat:async-state:spec:end\s*\*/",
    re.DOTALL,
)


def _js_spec(repo_root) -> dict:
    text = (repo_root / JS_PATH).read_text(encoding="utf-8")
    match = _SPEC_RE.search(text)
    assert match, "JS 里找不到状态词表块"
    body = match.group(1)
    start = body.find("{")
    end = body.rfind("}")
    assert start >= 0 and end > start, "JS 词表块里没有 JSON"
    return json.loads(body[start : end + 1])


def test_js_file_exists(repo_root):
    """词表文件必须在，否则打包后前端拿不到状态定义。"""
    assert (repo_root / JS_PATH).is_file()


def test_python_and_js_read_the_same_vocabulary(repo_root):
    """两个词表逐项相同。"""
    spec = _js_spec(repo_root)

    assert spec["data"] == list(async_state.data_values())
    assert spec["request"] == list(async_state.request_values())
    assert spec["result"] == list(async_state.result_values())
    assert spec["state"] == list(async_state.state_values())
    assert spec["reason"] == list(async_state.reason_values())
    assert spec["action"] == list(async_state.action_values())


def test_rules_match_between_python_and_js(repo_root):
    """规则表逐条相同：同一组三轴，两边推出同一个状态。"""
    spec = _js_spec(repo_root)

    assert spec["rules"] == async_state.load_spec()["rules"]


def test_python_derivation_matches_js_derivation(repo_root):
    """穷举三轴组合，Python 与 JS 必须推出同一个状态。

    这是「一份词表」最要紧的一条：两边各推一次，结果必须一致。
    """
    spec = _js_spec(repo_root)

    def js_derive(data: str, request: str, result: str) -> str:
        for rule in spec["rules"]:
            if "data" in rule and rule["data"] != data:
                continue
            if "request" in rule and rule["request"] != request:
                continue
            if "result" in rule and rule["result"] != result:
                continue
            return rule["state"]
        return "ready"

    checked = 0
    for data in async_state.data_values():
        for request in async_state.request_values():
            for result in async_state.result_values():
                assert async_state.derive(data, request, result) == js_derive(
                    data, request, result
                ), f"{data}/{request}/{result} 两边推出的状态不一致"
                checked += 1
    assert checked == len(async_state.data_values()) * len(
        async_state.request_values()
    ) * len(async_state.result_values())


def test_every_axis_value_is_covered_by_rules(repo_root):
    """词表里的每个取值都得能落到某个状态，不留「推不出状态」的组合。

    ``idle`` 不由任何一条规则点名——它是静止态，靠后面的规则（按 result/data
    判断）落位，所以这里检查的是「每个取值都能走到某个状态」。
    """
    spec = _js_spec(repo_root)
    rules = spec["rules"]

    def js_derive(data: str, request: str, result: str) -> str:
        for rule in rules:
            if "data" in rule and rule["data"] != data:
                continue
            if "request" in rule and rule["request"] != request:
                continue
            if "result" in rule and rule["result"] != result:
                continue
            return rule["state"]
        return "ready"

    for data in async_state.data_values():
        for request in async_state.request_values():
            for result in async_state.result_values():
                assert js_derive(data, request, result) in async_state.state_values()


def test_resting_request_value_is_reachable(repo_root):
    """静止态（idle）也要能推出状态——它是列表页最常见的情况。"""
    for result in async_state.result_values():
        state = async_state.derive("complete", "idle", result)
        assert state in async_state.state_values()
