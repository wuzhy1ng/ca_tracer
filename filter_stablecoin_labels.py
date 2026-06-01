from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_JSON = ROOT_DIR / "data" / "label" / "all" / "label_tags.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "label" / "stablecoins"

OUTPUT_JSON_NAME = "stablecoin_label_tags.json"
OUTPUT_MD_NAME = "stablecoin_label_tags说明.md"

STABLECOINS = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "PYUSD", "USDP", "GUSD"}
ALLOWED_LABEL_TYPES = (
    "fiat_buy_to_chain_withdrawal",
    "fiat_sell_to_chain_deposit",
)

TIME_WINDOWS = [
    ("<=1小时", 1 / 24),
    ("1-6小时", 6 / 24),
    ("6-24小时", 1),
    ("1-3天", 3),
    ("3-7天", 7),
    ("7-30天", 30),
    ("30-90天", 90),
    ("90-120天", 120),
]

LABEL_TYPE_DESC = {
    "fiat_buy_to_chain_withdrawal": "法币买入 -> 后续链上提币",
    "fiat_sell_to_chain_deposit": "法币卖出 -> 回溯此前链上充币",
}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def dump_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def bucket_name(days: float) -> str:
    for name, upper in TIME_WINDOWS:
        if days <= upper:
            return name
    return ">120天"


def time_window_coverage(items: list[dict]) -> dict[str, int]:
    counts = {name: 0 for name, _ in TIME_WINDOWS}
    counts[">120天"] = 0
    for item in items:
        counts[bucket_name(float(item["farthest_gap_days"]))] += 1
    return counts


def filter_payload(payload: dict, input_file: Path) -> dict:
    stable_events = [event for event in payload["events"] if event.get("asset") in STABLECOINS]

    stable_high_labels: dict[str, list[dict]] = {}
    label_counts: dict[str, int] = {}
    relation_counts: dict[str, dict[str, int]] = {}
    time_window_counts: dict[str, dict[str, int]] = {}
    referenced_event_ids: set[str] = set()

    for label_type in ALLOWED_LABEL_TYPES:
        items = payload["labels"].get(label_type, [])
        filtered = [
            item
            for item in items
            if item.get("asset") in STABLECOINS and item.get("confidence") == "high"
        ]
        stable_high_labels[label_type] = filtered
        label_counts[label_type] = len(filtered)
        relation_counts[label_type] = dict(Counter(item["relation_shape"] for item in filtered))
        time_window_counts[label_type] = time_window_coverage(filtered)

        for item in filtered:
            referenced_event_ids.add(item["anchor_event_id"])
            referenced_event_ids.update(item["candidate_event_ids"])
            referenced_event_ids.update(item.get("fiat_event_ids", []))
            referenced_event_ids.update(item.get("chain_event_ids", []))

    referenced_stable_events = [event for event in stable_events if event["event_id"] in referenced_event_ids]
    stable_event_asset_counts = dict(Counter(event["asset"] for event in referenced_stable_events))
    stable_event_direction_counts = dict(Counter(event["direction"] for event in referenced_stable_events))

    sample_labels = {}
    for label_type, items in stable_high_labels.items():
        sample_labels[label_type] = items[:2]

    filtered_payload = {
        "generated_at": payload.get("generated_at"),
        "source_root": payload.get("source_root"),
        "filter": {
            "type": "stablecoins_high_only",
            "assets": sorted(STABLECOINS),
            "confidence": ["high"],
            "label_types": list(ALLOWED_LABEL_TYPES),
            "input_file": str(input_file.relative_to(ROOT_DIR)),
        },
        "assumptions": payload.get("assumptions", {}),
        "metadata": {
            **payload.get("metadata", {}),
            "filter_summary": {
                "stable_referenced_event_count": len(referenced_stable_events),
                "stable_high_label_count": sum(label_counts.values()),
            },
        },
        "summary": {
            "stable_referenced_event_count": len(referenced_stable_events),
            "stable_event_asset_counts": stable_event_asset_counts,
            "stable_event_direction_counts": stable_event_direction_counts,
            "stable_high_label_counts": label_counts,
            "stable_high_label_relation_counts": relation_counts,
            "stable_high_label_time_window_counts": time_window_counts,
        },
        "events": referenced_stable_events,
        "labels": stable_high_labels,
        "sample_labels": sample_labels,
    }
    return filtered_payload


def build_event_field_table() -> str:
    rows = [
        ("event_id", "string", "事件唯一 ID"),
        ("exchange", "string", "来源交易所"),
        ("source_file", "string", "来源 Excel 文件名"),
        ("source_sheet", "string", "来源 sheet 名"),
        ("source_row", "number", "来源 Excel 行号"),
        ("event_class", "string", "`fiat_trade` 或 `chain_transfer`"),
        ("direction", "string", "方向，如 `fiat_buy`、`chain_withdrawal`"),
        ("asset", "string", "币种"),
        ("quantity", "string", "币数量，字符串保存以避免精度误差"),
        ("time", "string", "标准化后的时间"),
        ("raw_time", "string", "原始时间值"),
        ("account_id", "string/null", "账户 ID、订单号或用户标识"),
        ("fiat_currency", "string/null", "法币币种，如 `CNY`"),
        ("fiat_amount", "string/null", "法币金额"),
        ("status", "string/null", "原始状态"),
        ("txid", "string/null", "链上哈希"),
        ("address", "string/null", "充提币地址"),
        ("counterparty", "string/null", "对手方或来源地址"),
        ("onchain", "boolean", "是否识别为明确链上记录"),
        ("match_eligible", "boolean", "是否允许进入标签匹配"),
        ("raw_direction", "string/null", "原始买卖方向"),
        ("note", "string/null", "备注"),
    ]
    lines = ["| 字段 | 类型 | 说明 |", "| --- | --- | --- |"]
    lines.extend(f"| `{name}` | `{kind}` | {desc} |" for name, kind, desc in rows)
    return "\n".join(lines)


def build_label_field_table() -> str:
    rows = [
        ("label_type", "string", "标签类型"),
        ("anchor_event_id", "string", "锚点事件 ID"),
        ("anchor_direction", "string", "锚点方向"),
        ("candidate_event_ids", "array[string]", "配对候选事件 ID 列表"),
        ("candidate_count", "number", "候选事件数量"),
        ("relation_shape", "string", "`one_to_one` 或 `one_to_many`"),
        ("asset", "string", "匹配币种"),
        ("anchor_quantity", "string", "锚点数量"),
        ("candidate_total_quantity", "string", "候选合计数量"),
        ("quantity_gap", "string", "数量差的绝对值"),
        ("confidence", "string", "这里只保留 `high`"),
        ("anchor_time", "string", "锚点时间"),
        ("candidate_time_start", "string", "候选事件最早时间"),
        ("candidate_time_end", "string", "候选事件最晚时间"),
        ("farthest_gap_days", "number", "锚点到最远候选事件的时间差，单位天"),
        ("fiat_event_ids", "array[string]", "该标签里的法币事件 ID"),
        ("chain_event_ids", "array[string]", "该标签里的链上事件 ID"),
    ]
    lines = ["| 字段 | 类型 | 说明 |", "| --- | --- | --- |"]
    lines.extend(f"| `{name}` | `{kind}` | {desc} |" for name, kind, desc in rows)
    return "\n".join(lines)


def build_time_window_table(counts: dict[str, int]) -> str:
    ordered = [name for name, _ in TIME_WINDOWS] + [">120天"]
    total = sum(counts.values()) or 1
    lines = ["| 时间窗 | 样本数 | 覆盖率 |", "| --- | ---: | ---: |"]
    running = 0
    for name in ordered:
        running += counts.get(name, 0)
        lines.append(f"| `{name}` | {counts.get(name, 0)} | {running / total:.2%} |")
    return "\n".join(lines)


def format_json_sample(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_markdown(payload: dict) -> str:
    summary = payload["summary"]
    filter_info = payload["filter"]
    label_counts = summary["stable_high_label_counts"]
    relation_counts = summary["stable_high_label_relation_counts"]
    time_window_counts = summary["stable_high_label_time_window_counts"]
    events = {event["event_id"]: event for event in payload["events"]}
    sample_labels = payload["sample_labels"]

    total_labels = sum(label_counts.values())

    sample_blocks: list[str] = []
    for label_type in ALLOWED_LABEL_TYPES:
        items = sample_labels.get(label_type, [])
        if not items:
            continue
        label = items[0]
        anchor = events.get(label["anchor_event_id"])
        candidates = [events[cid] for cid in label["candidate_event_ids"] if cid in events]
        sample_blocks.append(
            f"### 样例：`{label_type}`\n\n"
            f"{LABEL_TYPE_DESC[label_type]}\n\n"
            f"标签样例：\n\n```json\n{format_json_sample(label)}\n```\n\n"
            f"锚点事件样例：\n\n```json\n{format_json_sample(anchor)}\n```\n\n"
            f"候选事件样例：\n\n```json\n{format_json_sample(candidates[0])}\n```\n"
        )

    time_window_sections: list[str] = []
    for label_type in ALLOWED_LABEL_TYPES:
        counts = time_window_counts.get(label_type, {})
        time_window_sections.append(
            f"### `{label_type}`\n\n"
            f"{LABEL_TYPE_DESC[label_type]}\n\n"
            f"{build_time_window_table(counts)}"
        )

    return f"""# `stablecoin_label_tags.json` 说明

## 文件说明

该文件位于：

`data/label/stablecoins/stablecoin_label_tags.json`

它是从：

`data/label/all/label_tags.json`

中筛选出来的“稳定币 + 仅 high 置信度”标签结果。

本次筛选规则：

1. `asset` 必须属于稳定币集合
2. `confidence` 必须等于 `high`
3. `label_type` 只保留“法币买卖追踪链上交易”的正向标签

当前稳定币集合为：

`{", ".join(filter_info["assets"])}`

当前保留标签为：

`{", ".join(filter_info["label_types"])}`

## 结果概况

| 项目 | 数量 |
| --- | ---: |
| 被标签引用到的稳定币事件数 | {summary["stable_referenced_event_count"]} |
| high 稳定币标签总数 | {total_labels} |

### high 标签按类型统计

| 标签类型 | 含义 | 数量 |
| --- | --- | ---: |
| `fiat_buy_to_chain_withdrawal` | {LABEL_TYPE_DESC["fiat_buy_to_chain_withdrawal"]} | {label_counts.get("fiat_buy_to_chain_withdrawal", 0)} |
| `fiat_sell_to_chain_deposit` | {LABEL_TYPE_DESC["fiat_sell_to_chain_deposit"]} | {label_counts.get("fiat_sell_to_chain_deposit", 0)} |

### high 标签按关系形态统计

| 标签类型 | one_to_one | one_to_many |
| --- | ---: | ---: |
| `fiat_buy_to_chain_withdrawal` | {relation_counts.get("fiat_buy_to_chain_withdrawal", {}).get("one_to_one", 0)} | {relation_counts.get("fiat_buy_to_chain_withdrawal", {}).get("one_to_many", 0)} |
| `fiat_sell_to_chain_deposit` | {relation_counts.get("fiat_sell_to_chain_deposit", {}).get("one_to_one", 0)} | {relation_counts.get("fiat_sell_to_chain_deposit", {}).get("one_to_many", 0)} |

## 字段说明

### `events` 字段

{build_event_field_table()}

### `labels` 字段

{build_label_field_table()}

## high 的含义

这里的 `high` 不是人工主观评级，而是脚本规则筛出来的高置信度候选。用大白话说：

- 数量差得不大
- 时间离得比较近
- 时间顺序也必须对

具体规则是：

- 数量差要落在系统允许的误差范围内
- 且最远配对时间差不超过 `7` 天

所以这个文件里的标签，相比全量稳定币标签，更适合直接优先研判。

## 样例

{chr(10).join(sample_blocks)}

## 不同分类下，不同时间窗能覆盖多少配对

下面的“覆盖率”是累计覆盖率，意思是：

- `<=1小时`：时间窗放到 1 小时以内，能覆盖多少 high 配对
- `1-6小时`：时间窗放到 6 小时以内，累计能覆盖多少
- 以此类推

{chr(10).join(time_window_sections)}

## 备注

- 本文件只保留 `high` 标签，因此 `labels` 中所有记录的 `confidence` 都应为 `high`
- `events` 只保留被这些 `high` 标签实际引用到的稳定币事件
- 当前 high 稳定币标签几乎都来自 `USDT`
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Filter stablecoin high-confidence labels from label_tags.json.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    input_json = args.input
    output_dir = args.output_dir
    output_json = output_dir / OUTPUT_JSON_NAME
    output_md = output_dir / OUTPUT_MD_NAME

    payload = load_json(input_json)
    filtered = filter_payload(payload, input_json)
    dump_json(output_json, filtered)
    dump_md(output_md, build_markdown(filtered))

    print(f"Wrote {output_json}")
    print(f"Wrote {output_md}")
    print(json.dumps(filtered["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
