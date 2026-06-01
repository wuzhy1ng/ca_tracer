# CA Tracer Implementation Status

This repository now contains a runnable first version of the CA Tracer pipeline skeleton.

## Implemented

- Raw Tron CSV inspection:
  - `tools/inspect_raw_tron_csv.py`
  - `tools/build_raw_manifest.py`
  - Streams a raw CSV and reports row count, timestamp range, transfer-like rows, and USDT TRC20 transfer-like rows.
- USDT TRC20 transfer decoding:
  - `tools/decode_tron_stablecoin_transfers.py`
  - Decodes `TriggerSmartContract` rows for the USDT TRC20 contract into JSONL records.
  - Handles Tron ABI address words with or without the `41` prefix and emits `time_utc`, `time_local`, and `direction_hint`.
- Baseline matching operators:
  - `algos/baseline.py`
  - Includes single-transfer ranking, time-decay ranking, contiguous sequence sum, limited subset sum, round-amount risk flags, and unique-candidate confirmation.
- 2023 label evaluation:
  - `tools/run_baseline_2023.py`
  - Produces `eval_results/baseline_2023.json` with Top-1, Top-5, Top-10, false-match, manual-review, candidate-count, and runtime metrics.
- Decoded transfer retrieval interface:
  - `daos.tron.discover_transfer_files`
  - `daos.tron.load_transfer_events`
  - `daos.tron.query_transfer_window`
  - `tools/run_baseline_2023.py --candidate-jsonl ...`
- Operator knowledge base:
  - `algos/operator_library.py`
  - `tools/build_operator_library.py`
  - Produces `operator_library/builtin_operators.json`.
- Agent synthesis skeleton:
  - `agents/synthesis.py`
  - `agents/llm_client.py`
  - `agents/prompts.py`
  - `agents/sandbox.py`
  - `agents/validator.py`
  - `tools/run_synthesis_round.py`
  - Produces failure analyses and auditable operator proposals with source-similarity blocking, behavior-similarity blocking, process-level sandbox execution, and validation reports.

## 2026-05-31 Audit Fixes

- Renamed the default label-contained candidate baseline to `oracle_candidate_pool_baseline`.
- Added txid-aware hit evaluation:
  - Cases now include `truth_ids` and `truth_txids`.
  - `MatchResult` includes `candidate_ids` and `candidate_txids`.
  - Hit checks prefer exact txid-set matches when txids are available, then fall back to event IDs.
- Renamed the old `false_match_rate` interpretation:
  - Primary metric is now `top1_exact_miss_rate`.
  - `false_match_rate_deprecated` is retained only for backward compatibility.
- Added process-level generated-operator validation with timeout.
- Added behavior signatures to similarity blocking.
- Added lightweight core tests in `tests/test_core.py`.
- Added `pyproject.toml` and `requirements.txt` for reproducible setup.

## Claude Integration

The synthesis path can call Claude through the Python client in `agents/llm_client.py`.

Required environment variable:

```text
ANTHROPIC_API_KEY=...
```

Optional environment variables:

```text
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
ANTHROPIC_BASE_URL=https://api.anthropic.com
```

Run with Claude:

```text
python tools/run_synthesis_round.py --use-llm --limit 3
```

Run the same LLM path without network using the fixture response:

```text
python tools/run_synthesis_round.py --fixture-response agents/fixtures/operator_response.json --limit 2
```

## Current Baseline Result

The current baseline uses chain-transfer events already present in `data/label/stablecoins_2023/stablecoin_label_tags_2023.json` as the candidate pool. It validates the ranking, combination search, and explanation path before the full raw-chain retrieval layer is ready.

Latest run:

| Metric | Value |
| --- | ---: |
| Cases | 2345 |
| Top-1 Recall | 0.4665 |
| Top-5 Recall | 0.8738 |
| Top-10 Recall | 0.9736 |
| Top-1 Exact Miss Rate | 0.5335 |
| Manual Review Rate | 0.6887 |
| Avg Candidate Count | 12.1629 |
| Avg Runtime ms | 6.7775 |
| P95 Runtime ms | 12.8661 |

## Example Raw Data Note

`data/raw_data/2023-01-01.csv` is treated as an interface-development sample, not the real experiment data. A 1000-row sample reports:

- First time: `2024-07-01 00:00:18`
- Min time: `2024-07-01 00:00:00`
- Max time: `2024-07-01 00:00:27`
- USDT transfer-like rows: `231 / 1000`

The decoded-transfer path has been developed and smoke-tested on this sample. Real-data recall should be evaluated only after aligned raw data is supplied.

## Next Milestone

1. Add a sandbox executor for generated operator code.
2. Promote only validated operator proposals into `operator_library/`.
3. Add address-label context so decoded on-chain transfers can be classified as deposit or withdrawal.
4. Add a small UI or report generator for manual review cases.
