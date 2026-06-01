from __future__ import annotations

import inspect
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import baseline


OperatorFn = Callable[[dict, list[dict], baseline.MatchContext], list[baseline.MatchResult]]


@dataclass
class OperatorSpec:
    name: str
    function: str
    scenario: str
    limitations: list[str]
    trigger_features: list[str]
    explanation_template: str
    passed_cases: list[str] = field(default_factory=list)
    failed_cases: list[str] = field(default_factory=list)


BUILTIN_OPERATORS: dict[str, OperatorFn] = {
    "nearest_single_transfer": baseline.nearest_single_transfer,
    "time_decay_single_transfer": baseline.time_decay_single_transfer,
    "sequence_sum_transfer": baseline.sequence_sum_transfer,
    "subset_sum_limited_transfer": baseline.subset_sum_limited_transfer,
}


BUILTIN_SPECS = [
    OperatorSpec(
        name="nearest_single_transfer",
        function="algos.baseline.nearest_single_transfer",
        scenario="单笔链上转账与链下锚点金额接近的一对一匹配。",
        limitations=["常见整数金额竞争者多时容易误排第一", "不处理拆单组合"],
        trigger_features=["one_to_one", "small_amount_gap"],
        explanation_template="按金额差排序，并报告时间差与竞争风险。",
    ),
    OperatorSpec(
        name="time_decay_single_transfer",
        function="algos.baseline.time_decay_single_transfer",
        scenario="金额接近且时间越近越可信的一对一匹配。",
        limitations=["长延迟真实交易可能被压低", "不处理拆单组合"],
        trigger_features=["one_to_one", "small_amount_gap", "short_time_gap"],
        explanation_template="综合金额相似和时间衰减给出排序。",
    ),
    OperatorSpec(
        name="sequence_sum_transfer",
        function="algos.baseline.sequence_sum_transfer",
        scenario="多笔时间连续链上转账合计接近链下金额的一对多匹配。",
        limitations=["只搜索连续片段", "候选过多时依赖时间排序"],
        trigger_features=["one_to_many", "ordered_split"],
        explanation_template="枚举时间连续组合，报告组合长度、金额差和跨度。",
    ),
    OperatorSpec(
        name="subset_sum_limited_transfer",
        function="algos.baseline.subset_sum_limited_transfer",
        scenario="多笔非连续候选合计接近链下金额的一对多匹配。",
        limitations=["组合长度与候选池大小受限", "候选池太宽时可能漏召回"],
        trigger_features=["one_to_many", "non_contiguous_split"],
        explanation_template="在金额近邻候选中搜索有限子集和，并输出组合证据。",
    ),
]


def tokenize_source(source: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?", source))


def source_jaccard(left: str, right: str) -> float:
    left_tokens = tokenize_source(left)
    right_tokens = tokenize_source(right)
    if not left_tokens and not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def operator_source(fn: OperatorFn) -> str:
    return inspect.getsource(fn)


def behavior_signature(fn: OperatorFn, sample_cases: list[tuple[dict, list[dict], baseline.MatchContext]]) -> set[tuple[str, ...]]:
    signature: set[tuple[str, ...]] = set()
    for anchor, candidates, context in sample_cases:
        for result in fn(anchor, candidates, context)[:3]:
            signature.add(tuple(sorted(result.candidate_ids)))
    return signature


def behavior_jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / max(len(left | right), 1)


def is_too_similar(
    candidate_source: str,
    candidate_signature: set[tuple[str, ...]] | None = None,
    source_threshold: float = 0.85,
    behavior_threshold: float = 0.85,
    sample_cases: list[tuple[dict, list[dict], baseline.MatchContext]] | None = None,
) -> tuple[bool, dict]:
    comparisons = []
    for name, fn in BUILTIN_OPERATORS.items():
        src_score = source_jaccard(candidate_source, operator_source(fn))
        behavior_score = 0.0
        if candidate_signature is not None and sample_cases is not None:
            behavior_score = behavior_jaccard(candidate_signature, behavior_signature(fn, sample_cases))
        comparisons.append({"operator": name, "source_jaccard": src_score, "behavior_jaccard": behavior_score})

    source_hit = any(item["source_jaccard"] >= source_threshold for item in comparisons)
    behavior_hit = any(item["behavior_jaccard"] >= behavior_threshold for item in comparisons if candidate_signature is not None)
    return source_hit or behavior_hit, {"comparisons": comparisons}


def write_operator_library(path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"operators": [asdict(spec) for spec in BUILTIN_SPECS]}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
