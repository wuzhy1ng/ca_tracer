from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, getcontext
from itertools import combinations
from statistics import mean
from time import perf_counter
from typing import Iterable


getcontext().prec = 28


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ROUND_AMOUNTS = {
    Decimal("1000"),
    Decimal("2000"),
    Decimal("3000"),
    Decimal("5000"),
    Decimal("10000"),
    Decimal("20000"),
    Decimal("30000"),
    Decimal("50000"),
    Decimal("100000"),
}


@dataclass(frozen=True)
class MatchContext:
    window_days: int = 7
    top_k: int = 10
    amount_rel_tolerance: Decimal = Decimal("0.10")
    amount_abs_tolerance: Decimal = Decimal("1")
    max_sequence_length: int = 6
    max_subset_length: int = 3
    subset_pool_size: int = 10
    unique_candidate_rel_tolerance: Decimal = Decimal("0.01")


@dataclass
class MatchResult:
    candidate_ids: list[str]
    score: float
    rank: int = 0
    candidate_txids: list[str] = field(default_factory=list)
    amount_gap: str = "0"
    time_gap_hours: float = 0.0
    relation_shape: str = "one_to_one"
    operator: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    def key(self) -> tuple[str, ...]:
        return tuple(sorted(self.candidate_ids))

    def to_dict(self) -> dict:
        return asdict(self)


def parse_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def event_amount(event: dict) -> Decimal:
    return parse_decimal(event.get("quantity") or event.get("amount"))


def event_time(event: dict) -> datetime:
    value = event.get("time")
    if not isinstance(value, str):
        raise ValueError(f"event has no string time: {event.get('event_id')}")
    return parse_time(value)


def label_mode(label_type: str) -> tuple[str, str]:
    if label_type == "fiat_buy_to_chain_withdrawal":
        return "forward", "chain_withdrawal"
    if label_type == "fiat_sell_to_chain_deposit":
        return "backward", "chain_deposit"
    raise ValueError(f"unsupported label_type: {label_type}")


def time_gap_hours(anchor: dict, candidates: Iterable[dict]) -> float:
    anchor_ts = event_time(anchor)
    gaps = [abs((event_time(candidate) - anchor_ts).total_seconds()) / 3600 for candidate in candidates]
    return max(gaps) if gaps else 0.0


def amount_gap(anchor: dict, candidates: Iterable[dict]) -> Decimal:
    return abs(sum((event_amount(candidate) for candidate in candidates), Decimal("0")) - event_amount(anchor))


def amount_score(gap: Decimal, target: Decimal) -> float:
    denom = max(abs(target), Decimal("1"))
    rel_gap = gap / denom
    return max(0.0, 1.0 - min(float(rel_gap), 1.0))


def time_score(hours: float, window_days: int) -> float:
    window_hours = max(window_days * 24, 1)
    return max(0.0, 1.0 - min(hours / window_hours, 1.0))


def relation_shape(candidates: list[dict]) -> str:
    return "one_to_one" if len(candidates) == 1 else "one_to_many"


def is_round_amount(amount: Decimal) -> bool:
    if amount in ROUND_AMOUNTS:
        return True
    return amount == amount.to_integral_value() and amount >= Decimal("1000") and amount % Decimal("1000") == 0


def candidate_pool(anchor: dict, all_chain_events: list[dict], label_type: str, context: MatchContext) -> list[dict]:
    mode, wanted_direction = label_mode(label_type)
    anchor_ts = event_time(anchor)
    target = event_amount(anchor)
    lower = anchor_ts - timedelta(days=context.window_days) if mode == "backward" else anchor_ts
    upper = anchor_ts if mode == "backward" else anchor_ts + timedelta(days=context.window_days)
    amount_limit = target * (Decimal("1") + context.amount_rel_tolerance) + context.amount_abs_tolerance

    pool = []
    for event in all_chain_events:
        if event.get("asset") != anchor.get("asset"):
            continue
        if event.get("direction") != wanted_direction:
            continue
        ts = event_time(event)
        if ts < lower or ts > upper:
            continue
        amount = event_amount(event)
        if amount <= 0 or amount > amount_limit:
            continue
        pool.append(event)
    pool.sort(key=lambda item: event_time(item))
    return pool


def make_result(operator: str, anchor: dict, candidates: list[dict], context: MatchContext, base_score: float) -> MatchResult:
    gap = amount_gap(anchor, candidates)
    hours = time_gap_hours(anchor, candidates)
    target = event_amount(anchor)
    score = 0.72 * amount_score(gap, target) + 0.28 * time_score(hours, context.window_days)
    score = min(1.0, max(0.0, 0.65 * score + 0.35 * base_score))
    risks: list[str] = []
    evidence = [
        f"amount target={target}, candidate_total={sum((event_amount(c) for c in candidates), Decimal('0'))}, gap={gap}",
        f"time_gap_hours={hours:.4f}",
    ]
    if is_round_amount(target):
        risks.append("round_amount_competition")
        evidence.append("anchor amount is a high-frequency round amount")
    if len(candidates) > 1:
        evidence.append(f"combination_length={len(candidates)}")
        if len(candidates) > 4:
            risks.append("long_combination")
    return MatchResult(
        candidate_ids=[str(candidate["event_id"]) for candidate in candidates],
        candidate_txids=[str(candidate.get("txid") or "") for candidate in candidates if candidate.get("txid")],
        score=score,
        amount_gap=str(gap.normalize()),
        time_gap_hours=round(hours, 4),
        relation_shape=relation_shape(candidates),
        operator=operator,
        evidence=evidence,
        risk_flags=risks,
    )


def nearest_single_transfer(anchor: dict, candidates: list[dict], context: MatchContext) -> list[MatchResult]:
    ranked = sorted(candidates, key=lambda item: (amount_gap(anchor, [item]), time_gap_hours(anchor, [item])))
    return [make_result("nearest_single_transfer", anchor, [item], context, 0.80) for item in ranked[: context.top_k]]


def time_decay_single_transfer(anchor: dict, candidates: list[dict], context: MatchContext) -> list[MatchResult]:
    ranked = sorted(candidates, key=lambda item: (float(amount_gap(anchor, [item])) / max(float(event_amount(anchor)), 1.0), time_gap_hours(anchor, [item])))
    return [make_result("time_decay_single_transfer", anchor, [item], context, 0.86) for item in ranked[: context.top_k]]


def sequence_sum_transfer(anchor: dict, candidates: list[dict], context: MatchContext) -> list[MatchResult]:
    results: list[MatchResult] = []
    limit = min(context.max_sequence_length, len(candidates))
    for start in range(len(candidates)):
        total = Decimal("0")
        group: list[dict] = []
        for end in range(start, min(len(candidates), start + limit)):
            group.append(candidates[end])
            total += event_amount(candidates[end])
            if total > event_amount(anchor) * Decimal("1.15") + context.amount_abs_tolerance:
                break
            if len(group) >= 2:
                results.append(make_result("sequence_sum_transfer", anchor, list(group), context, 0.84))
    results.sort(key=lambda item: (parse_decimal(item.amount_gap), -item.score))
    return results[: context.top_k]


def subset_sum_limited_transfer(anchor: dict, candidates: list[dict], context: MatchContext) -> list[MatchResult]:
    if len(candidates) < 2:
        return []
    seed_pool = sorted(candidates, key=lambda item: amount_gap(anchor, [item]))[: context.subset_pool_size]
    results: list[MatchResult] = []
    for length in range(2, min(context.max_subset_length, len(seed_pool)) + 1):
        for group_tuple in combinations(seed_pool, length):
            group = sorted(group_tuple, key=lambda item: event_time(item))
            results.append(make_result("subset_sum_limited_transfer", anchor, group, context, 0.82))
    results.sort(key=lambda item: (parse_decimal(item.amount_gap), item.time_gap_hours, -item.score))
    return results[: context.top_k]


def apply_domain_confirmation(anchor: dict, candidates: list[dict], results: list[MatchResult], context: MatchContext) -> list[MatchResult]:
    near_single_count = 0
    target = event_amount(anchor)
    for candidate in candidates:
        gap = amount_gap(anchor, [candidate])
        if gap / max(target, Decimal("1")) <= context.unique_candidate_rel_tolerance:
            near_single_count += 1

    for result in results:
        if near_single_count == 1 and result.relation_shape == "one_to_one":
            result.score = min(1.0, result.score + 0.05)
            result.evidence.append("unique high-similarity single candidate in window")
        elif near_single_count > 1:
            result.risk_flags.append("multiple_near_amount_candidates")
            result.evidence.append(f"{near_single_count} near-amount single candidates in window")

        if parse_decimal(result.amount_gap) > max(context.amount_abs_tolerance, target * context.amount_rel_tolerance):
            result.risk_flags.append("large_amount_gap")
        if result.time_gap_hours > context.window_days * 24 * 0.8:
            result.risk_flags.append("edge_of_time_window")
    return results


def dedupe_rank(results: list[MatchResult], top_k: int) -> list[MatchResult]:
    best: dict[tuple[str, ...], MatchResult] = {}
    for result in results:
        key = result.key()
        if key not in best or result.score > best[key].score:
            best[key] = result
    ranked = sorted(best.values(), key=lambda item: (-item.score, parse_decimal(item.amount_gap), item.time_gap_hours))
    for idx, item in enumerate(ranked[:top_k], start=1):
        item.rank = idx
    return ranked[:top_k]


def match_with_baselines(anchor: dict, all_chain_events: list[dict], label_type: str, context: MatchContext | None = None) -> tuple[list[MatchResult], list[dict]]:
    context = context or MatchContext()
    candidates = candidate_pool(anchor, all_chain_events, label_type, context)
    results: list[MatchResult] = []
    results.extend(nearest_single_transfer(anchor, candidates, context))
    results.extend(time_decay_single_transfer(anchor, candidates, context))
    results.extend(sequence_sum_transfer(anchor, candidates, context))
    results.extend(subset_sum_limited_transfer(anchor, candidates, context))
    results = apply_domain_confirmation(anchor, candidates, results, context)
    return dedupe_rank(results, context.top_k), candidates


def exact_hit(
    results: list[MatchResult],
    truth_ids: set[str],
    k: int,
    truth_txids: set[str] | None = None,
) -> bool:
    truth_txids = truth_txids or set()
    for result in results[:k]:
        if truth_txids and set(result.candidate_txids) == truth_txids:
            return True
        if set(result.candidate_ids) == truth_ids:
            return True
    return False


def truth_keys_for_label(label: dict, events: dict[str, dict]) -> tuple[set[str], set[str]]:
    truth_ids = set(label.get("chain_event_ids") or label.get("candidate_event_ids") or [])
    truth_txids = {
        str(events[event_id].get("txid"))
        for event_id in truth_ids
        if event_id in events and events[event_id].get("txid")
    }
    return truth_ids, truth_txids


def evaluate_labels(
    payload: dict,
    context: MatchContext | None = None,
    include_cases: bool = True,
    all_chain_events: list[dict] | None = None,
) -> dict:
    context = context or MatchContext()
    events = {event["event_id"]: event for event in payload["events"]}
    if all_chain_events is None:
        all_chain_events = [event for event in payload["events"] if event.get("event_class") == "chain_transfer"]
    totals = {"case_count": 0, "top1_hits": 0, "top5_hits": 0, "top10_hits": 0, "top1_exact_misses": 0, "manual_review": 0}
    runtimes: list[float] = []
    candidate_counts: list[int] = []
    per_type: dict[str, dict[str, int]] = {}
    cases: list[dict] = []

    for label_type, labels in payload["labels"].items():
        per_type[label_type] = {"case_count": 0, "top1_hits": 0, "top5_hits": 0, "top10_hits": 0}
        for label in labels:
            anchor = events.get(label["anchor_event_id"])
            if not anchor:
                continue
            truth_ids, truth_txids = truth_keys_for_label(label, events)
            started = perf_counter()
            results, candidates = match_with_baselines(anchor, all_chain_events, label_type, context)
            elapsed_ms = (perf_counter() - started) * 1000

            totals["case_count"] += 1
            per_type[label_type]["case_count"] += 1
            runtimes.append(elapsed_ms)
            candidate_counts.append(len(candidates))

            hit1 = exact_hit(results, truth_ids, 1, truth_txids)
            hit5 = exact_hit(results, truth_ids, 5, truth_txids)
            hit10 = exact_hit(results, truth_ids, 10, truth_txids)
            for name, hit in (("top1_hits", hit1), ("top5_hits", hit5), ("top10_hits", hit10)):
                if hit:
                    totals[name] += 1
                    per_type[label_type][name] += 1
            if results and not hit1:
                totals["top1_exact_misses"] += 1
            if not results or results[0].score < 0.88 or results[0].risk_flags:
                totals["manual_review"] += 1

            if include_cases:
                cases.append(
                    {
                        "label_type": label_type,
                        "anchor_event_id": label["anchor_event_id"],
                        "truth_ids": sorted(truth_ids),
                        "truth_txids": sorted(truth_txids),
                        "candidate_count": len(candidates),
                        "top1_hit": hit1,
                        "top5_hit": hit5,
                        "top10_hit": hit10,
                        "runtime_ms": round(elapsed_ms, 4),
                        "results": [result.to_dict() for result in results],
                    }
                )

    case_count = totals["case_count"] or 1
    metrics = {
        "top1_recall": totals["top1_hits"] / case_count,
        "top5_recall": totals["top5_hits"] / case_count,
        "top10_recall": totals["top10_hits"] / case_count,
        "top1_exact_miss_rate": totals["top1_exact_misses"] / case_count,
        "false_match_rate_deprecated": totals["top1_exact_misses"] / case_count,
        "manual_review_rate": totals["manual_review"] / case_count,
        "avg_candidate_count": mean(candidate_counts) if candidate_counts else 0,
        "avg_runtime_ms": mean(runtimes) if runtimes else 0,
        "p95_runtime_ms": sorted(runtimes)[int(len(runtimes) * 0.95) - 1] if runtimes else 0,
    }
    return {
        "context": {key: str(value) if isinstance(value, Decimal) else value for key, value in asdict(context).items()},
        "totals": totals,
        "metrics": metrics,
        "per_type": per_type,
        "cases": cases if include_cases else [],
    }
