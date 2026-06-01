from __future__ import annotations

import json
from dataclasses import asdict

from algos.operator_library import BUILTIN_SPECS

from .synthesis import FailureAnalysis


SYSTEM_PROMPT = """You are a program-synthesis agent for CA Tracer.

CA Tracer matches off-chain fiat stablecoin trade anchors to on-chain Tron stablecoin transfer candidates.
Generate one Python matching operator that follows this signature:

def operator_name(anchor, candidates, context):
    ...

The function must return list[MatchResult]. It may call these existing helpers only:
event_amount, event_time, amount_gap, time_gap_hours, make_result, is_round_amount, Decimal, sorted, min, max, abs, len, range, enumerate, sum, list.

Do not import modules. Do not read files. Do not use network. Do not use eval/exec/open/compile.
Prefer clear deterministic logic over cleverness.
"""


def build_operator_prompt(failure: FailureAnalysis, case: dict) -> str:
    specs = [asdict(spec) for spec in BUILTIN_SPECS]
    compact_case = {
        "label_type": case.get("label_type"),
        "anchor_event_id": case.get("anchor_event_id"),
        "truth_ids": case.get("truth_ids"),
        "candidate_count": case.get("candidate_count"),
        "top_results": case.get("results", [])[:5],
    }
    payload = {
        "failure": asdict(failure),
        "case": compact_case,
        "existing_operators": specs,
        "required_json_schema": {
            "name": "snake_case_operator_name",
            "source": "Python source code containing exactly one function definition",
            "scenario": "When this operator should be used",
            "limitations": ["Known failure boundaries"],
            "trigger_features": ["Feature names"],
            "explanation_template": "How to explain matches produced by this operator",
        },
    }
    return (
        "Generate one new matching operator for this failure case.\n"
        "Return only valid JSON matching required_json_schema. Do not wrap it in markdown.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
