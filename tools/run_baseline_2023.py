from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algos import MatchContext, evaluate_labels
from daos.tron import discover_transfer_files, load_transfer_events


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run non-agent baseline operators on the 2023 stablecoin label set.")
    parser.add_argument("--labels", default=str(ROOT / "data" / "label" / "stablecoins_2023" / "stablecoin_label_tags_2023.json"))
    parser.add_argument("--output", default=str(ROOT / "eval_results" / "baseline_2023.json"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--no-cases", action="store_true", help="Omit per-case details from the output JSON.")
    parser.add_argument("--candidate-jsonl", default=None, help="Optional decoded transfer JSONL file or directory.")
    parser.add_argument(
        "--candidate-direction",
        default="both",
        choices=["both", "chain_withdrawal", "chain_deposit", "chain_transfer"],
        help="Direction assigned to decoded transfer candidates.",
    )
    args = parser.parse_args()

    context = MatchContext(window_days=args.window_days, top_k=args.top_k)
    payload = load_json(Path(args.labels))
    external_events = None
    candidate_source = "oracle_candidate_pool_baseline"
    if args.candidate_jsonl:
        files = discover_transfer_files(args.candidate_jsonl)
        external_events = load_transfer_events(files, direction=args.candidate_direction)
        candidate_source = f"decoded_transfer_jsonl:{args.candidate_jsonl}"

    result = evaluate_labels(payload, context=context, include_cases=not args.no_cases, all_chain_events=external_events)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["input_labels"] = str(Path(args.labels).relative_to(ROOT))
    result["candidate_source"] = candidate_source
    result["note"] = (
        "Without --candidate-jsonl this is an oracle candidate-pool baseline over label-contained chain events, "
        "not a raw-chain experiment result. With --candidate-jsonl it evaluates decoded raw-chain candidates."
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    printable = {key: result[key] for key in ("generated_at", "input_labels", "candidate_source", "totals", "metrics", "per_type")}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
