from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from algos.operator_library import write_operator_library


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the builtin matching operator knowledge base.")
    parser.add_argument("--output", default=str(ROOT / "operator_library" / "builtin_operators.json"))
    args = parser.parse_args()
    write_operator_library(args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
