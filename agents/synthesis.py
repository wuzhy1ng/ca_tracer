from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from algos.baseline import MatchContext, MatchResult, candidate_pool
from algos.operator_library import behavior_signature, is_too_similar

from .llm_client import ClaudeMessagesClient, LLMClient, LLMError, OperatorProposal
from .sandbox import SandboxError, load_operator_from_source
from .validator import validate_operator_source


@dataclass
class FailureAnalysis:
    anchor_event_id: str
    label_type: str
    truth_ids: list[str]
    observed_top_ids: list[str]
    failure_type: str
    likely_causes: list[str]
    synthesis_plan: list[str]


@dataclass
class SynthesisRound:
    case_id: str
    failure: FailureAnalysis
    proposed_operator_name: str
    proposed_operator_source: str
    similarity_blocked: bool
    similarity_report: dict
    decision: str
    notes: list[str] = field(default_factory=list)
    llm_used: bool = False
    validation_report: dict | None = None
    operator_metadata: dict | None = None


def classify_failure(truth_ids: set[str], results: list[MatchResult], candidate_count: int) -> tuple[str, list[str]]:
    if candidate_count == 0:
        return "no_candidates", ["检索层没有召回任何候选，优先扩大时间窗或放宽预过滤"]
    if not results:
        return "no_ranked_results", ["候选存在但算子没有输出结果，可能是组合搜索约束过严"]
    top_sets = [set(item.candidate_ids) for item in results]
    if truth_ids in top_sets[1:]:
        return "rank_error", ["真实候选已召回但排序靠后，需要调整金额/时间/唯一性权重"]
    if any(truth_ids & top_set for top_set in top_sets):
        return "partial_combination", ["部分真实候选被召回，组合搜索需要更好地扩展或剪枝"]
    if len(truth_ids) > 1:
        return "missed_combination", ["真实关系是一对多，现有组合算子没有找到完整集合"]
    return "missed_single", ["真实单笔候选未进入 Top-K，可能存在高频整数金额竞争或时间延迟模式"]


def analyze_failure_case(case: dict) -> FailureAnalysis:
    truth_ids = set(case.get("truth_ids", []))
    results = [MatchResult(**item) for item in case.get("results", [])]
    failure_type, causes = classify_failure(truth_ids, results, int(case.get("candidate_count", 0)))
    observed_top_ids = results[0].candidate_ids if results else []
    plan_by_type = {
        "no_candidates": ["检查时间方向", "扩大窗口", "记录预过滤漏召回原因"],
        "no_ranked_results": ["放宽组合长度", "加入候选池兜底排序"],
        "rank_error": ["学习失败样本中的时间延迟分布", "对多竞争整数金额增加惩罚"],
        "partial_combination": ["围绕已命中候选做邻域扩展", "尝试非连续组合搜索"],
        "missed_combination": ["增加组合长度上限", "按金额残差做 beam search"],
        "missed_single": ["加入交易所地址/账户上下文", "对长延迟单笔单独建模"],
    }
    return FailureAnalysis(
        anchor_event_id=str(case.get("anchor_event_id")),
        label_type=str(case.get("label_type")),
        truth_ids=sorted(truth_ids),
        observed_top_ids=observed_top_ids,
        failure_type=failure_type,
        likely_causes=causes,
        synthesis_plan=plan_by_type.get(failure_type, ["人工复核失败模式"]),
    )


def propose_operator_source(failure: FailureAnalysis) -> tuple[str, str]:
    if failure.failure_type in {"partial_combination", "missed_combination"}:
        name = "residual_beam_sum_transfer"
        source = '''def residual_beam_sum_transfer(anchor, candidates, context):
    """Prefer combinations that reduce the remaining amount gap step by step."""
    beams = [([], event_amount(anchor))]
    for candidate in sorted(candidates, key=lambda item: event_time(item)):
        next_beams = list(beams)
        amount = event_amount(candidate)
        for group, residual in beams:
            if len(group) >= context.max_sequence_length:
                continue
            next_group = group + [candidate]
            next_beams.append((next_group, abs(residual - amount)))
        beams = sorted(next_beams, key=lambda item: item[1])[: context.subset_pool_size]
    return [make_result("residual_beam_sum_transfer", anchor, group, context, 0.83) for group, _ in beams if group]
'''
        return name, source
    name = "competition_aware_single_transfer"
    source = '''def competition_aware_single_transfer(anchor, candidates, context):
    """Penalize round-amount collisions when many near-amount candidates compete."""
    ranked = []
    target = event_amount(anchor)
    for candidate in candidates:
        gap = amount_gap(anchor, [candidate])
        competitor_penalty = Decimal("0.02") if is_round_amount(target) else Decimal("0")
        ranked.append((gap / max(target, Decimal("1")) + competitor_penalty, candidate))
    ranked.sort(key=lambda item: item[0])
    return [make_result("competition_aware_single_transfer", anchor, [item[1]], context, 0.84) for item in ranked[:context.top_k]]
'''
    return name, source


def _template_proposal(failure: FailureAnalysis) -> OperatorProposal:
    name, source = propose_operator_source(failure)
    return OperatorProposal(
        name=name,
        source=source,
        scenario="Template fallback generated from failure type.",
        limitations=["No LLM was used; validate before promotion."],
        trigger_features=[failure.failure_type],
        explanation_template="Use result evidence emitted by make_result.",
    )


def _llm_proposal(case: dict, failure: FailureAnalysis, llm_client: LLMClient | None) -> OperatorProposal:
    from .prompts import SYSTEM_PROMPT, build_operator_prompt

    client = llm_client or ClaudeMessagesClient()
    return client.generate_operator(SYSTEM_PROMPT, build_operator_prompt(failure, case))


def run_synthesis_round(
    case: dict,
    use_llm: bool = False,
    llm_client: LLMClient | None = None,
    label_payload: dict | None = None,
    validation_cases: list[dict] | None = None,
    context: MatchContext | None = None,
) -> SynthesisRound:
    failure = analyze_failure_case(case)
    notes = []
    try:
        proposal = _llm_proposal(case, failure, llm_client) if use_llm else _template_proposal(failure)
        llm_used = use_llm
    except LLMError as exc:
        proposal = _template_proposal(failure)
        llm_used = False
        notes.append(f"LLM generation failed; used template fallback: {exc}")

    sample_cases = build_similarity_sample_cases(label_payload, validation_cases or [case], context or MatchContext())
    candidate_signature = None
    if sample_cases:
        try:
            sandboxed = load_operator_from_source(proposal.source)
            candidate_signature = behavior_signature(sandboxed.function, sample_cases)
        except SandboxError:
            candidate_signature = None
    blocked, report = is_too_similar(proposal.source, candidate_signature=candidate_signature, sample_cases=sample_cases or None)
    validation_report = None
    if label_payload is not None:
        validation_report = validate_operator_source(
            proposal.source,
            label_payload,
            validation_cases or [case],
            context=context or MatchContext(),
        ).to_dict()

    if blocked:
        decision = "blocked_as_similar"
    elif validation_report is not None and not validation_report.get("runnable"):
        decision = "blocked_by_sandbox"
    elif validation_report is not None:
        decision = "validated_candidate_ready_for_review"
    else:
        decision = "candidate_ready_for_sandbox"
    notes = [
        *notes,
        "Generated operators are promoted only after sandbox validation and validation-set improvement.",
        "Promote the operator only after validation-set recall improves without unacceptable false-match growth.",
    ]
    return SynthesisRound(
        case_id=str(case.get("anchor_event_id")),
        failure=failure,
        proposed_operator_name=proposal.name,
        proposed_operator_source=proposal.source,
        similarity_blocked=blocked,
        similarity_report=report,
        decision=decision,
        notes=notes,
        llm_used=llm_used,
        validation_report=validation_report,
        operator_metadata={
            "scenario": proposal.scenario,
            "limitations": proposal.limitations,
            "trigger_features": proposal.trigger_features,
            "explanation_template": proposal.explanation_template,
        },
    )


def load_failed_cases(baseline_result_path: Path | str, limit: int = 10) -> list[dict]:
    payload = json.loads(Path(baseline_result_path).read_text(encoding="utf-8"))
    failed = [case for case in payload.get("cases", []) if not case.get("top10_hit")]
    return failed[:limit]


def build_similarity_sample_cases(
    label_payload: dict | None,
    cases: list[dict],
    context: MatchContext,
) -> list[tuple[dict, list[dict], MatchContext]]:
    if label_payload is None:
        return []
    events = {event["event_id"]: event for event in label_payload["events"]}
    all_chain_events = [event for event in label_payload["events"] if event.get("event_class") == "chain_transfer"]
    samples = []
    for case in cases[:10]:
        anchor = events.get(case.get("anchor_event_id"))
        if not anchor:
            continue
        candidates = candidate_pool(anchor, all_chain_events, str(case.get("label_type")), context)
        samples.append((anchor, candidates, context))
    return samples


def write_synthesis_report(
    baseline_result_path: Path | str,
    output_path: Path | str,
    limit: int = 10,
    use_llm: bool = False,
    label_payload_path: Path | str | None = None,
    llm_client: LLMClient | None = None,
) -> dict:
    cases = load_failed_cases(baseline_result_path, limit=limit)
    label_payload = None
    if label_payload_path is not None:
        label_payload = json.loads(Path(label_payload_path).read_text(encoding="utf-8"))
    rounds = [
        run_synthesis_round(
            case,
            use_llm=use_llm,
            llm_client=llm_client,
            label_payload=label_payload,
            validation_cases=cases,
        )
        for case in cases
    ]
    payload = {"source": str(baseline_result_path), "rounds": [asdict(item) for item in rounds]}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
