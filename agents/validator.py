from __future__ import annotations

import json
import multiprocessing as mp
from dataclasses import dataclass, asdict
from pathlib import Path

from algos.baseline import MatchContext, candidate_pool, exact_hit

from .sandbox import SandboxError, load_operator_from_source


@dataclass
class ValidationReport:
    runnable: bool
    evaluated_cases: int
    top1_hits: int
    top5_hits: int
    top10_hits: int
    errors: list[str]

    def to_dict(self) -> dict:
        payload = asdict(self)
        denominator = self.evaluated_cases or 1
        payload["top1_recall"] = self.top1_hits / denominator
        payload["top5_recall"] = self.top5_hits / denominator
        payload["top10_recall"] = self.top10_hits / denominator
        return payload


def validate_operator_source(
    source: str,
    label_payload: dict,
    cases: list[dict],
    context: MatchContext | None = None,
    timeout_seconds: float = 2.0,
) -> ValidationReport:
    context = context or MatchContext()
    errors: list[str] = []
    try:
        load_operator_from_source(source)
    except SandboxError as exc:
        return ValidationReport(False, 0, 0, 0, 0, [str(exc)])

    events = {event["event_id"]: event for event in label_payload["events"]}
    all_chain_events = [event for event in label_payload["events"] if event.get("event_class") == "chain_transfer"]
    evaluated = 0
    top1 = 0
    top5 = 0
    top10 = 0
    for case in cases:
        anchor = events.get(case.get("anchor_event_id"))
        if not anchor:
            errors.append(f"missing anchor: {case.get('anchor_event_id')}")
            continue
        truth_ids = set(case.get("truth_ids", []))
        truth_txids = set(case.get("truth_txids", []))
        candidates = candidate_pool(anchor, all_chain_events, str(case.get("label_type")), context)
        results, error = run_operator_in_process(source, anchor, candidates, context, timeout_seconds=timeout_seconds)
        if error:
            errors.append(f"{case.get('anchor_event_id')}: {error}")
            continue
        evaluated += 1
        top1 += int(exact_hit(results, truth_ids, 1, truth_txids))
        top5 += int(exact_hit(results, truth_ids, 5, truth_txids))
        top10 += int(exact_hit(results, truth_ids, 10, truth_txids))
    return ValidationReport(True, evaluated, top1, top5, top10, errors[:20])


def load_label_payload(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _operator_worker(source: str, anchor: dict, candidates: list[dict], context: MatchContext, queue: mp.Queue) -> None:
    try:
        sandboxed = load_operator_from_source(source)
        results = sandboxed.function(anchor, candidates, context)
        queue.put({"results": [result.to_dict() for result in results[: context.top_k]], "error": None})
    except Exception as exc:  # noqa: BLE001 - isolate generated-code failures.
        queue.put({"results": [], "error": f"{type(exc).__name__}: {exc}"})


def run_operator_in_process(
    source: str,
    anchor: dict,
    candidates: list[dict],
    context: MatchContext,
    timeout_seconds: float = 2.0,
) -> tuple[list, str | None]:
    queue: mp.Queue = mp.Queue()
    process = mp.Process(target=_operator_worker, args=(source, anchor, candidates[:200], context, queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1)
        return [], f"timeout after {timeout_seconds}s"
    if queue.empty():
        return [], "sandbox process produced no result"
    payload = queue.get()
    from algos.baseline import MatchResult

    return [MatchResult(**item) for item in payload.get("results", [])], payload.get("error")
