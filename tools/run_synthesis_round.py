from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.synthesis import write_synthesis_report
from agents.llm_client import FixtureLLMClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze failed baseline cases and produce auditable operator proposals.")
    parser.add_argument("--baseline", default=str(ROOT / "eval_results" / "baseline_2023.json"))
    parser.add_argument("--output", default=str(ROOT / "eval_results" / "synthesis_round_2023.json"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--use-llm", action="store_true", help="Call Claude through the Python client.")
    parser.add_argument("--fixture-response", default=None, help="Use a local text file as a fake LLM response.")
    parser.add_argument(
        "--labels",
        default=str(ROOT / "data" / "label" / "stablecoins_2023" / "stablecoin_label_tags_2023.json"),
        help="Label payload used for sandbox validation.",
    )
    args = parser.parse_args()
    llm_client = None
    use_llm = args.use_llm
    if args.fixture_response:
        llm_client = FixtureLLMClient(Path(args.fixture_response).read_text(encoding="utf-8"))
        use_llm = True

    payload = write_synthesis_report(
        args.baseline,
        args.output,
        limit=args.limit,
        use_llm=use_llm,
        label_payload_path=args.labels,
        llm_client=llm_client,
    )
    print(
        json.dumps(
            {"output": args.output, "rounds": len(payload["rounds"]), "use_llm": use_llm},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
