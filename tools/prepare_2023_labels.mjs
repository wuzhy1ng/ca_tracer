import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const inputPath = path.join(root, "data", "label", "stablecoins", "stablecoin_label_tags.json");
const outputDir = path.join(root, "data", "label", "stablecoins_2023");
const outputPath = path.join(outputDir, "stablecoin_label_tags_2023.json");
const readmePath = path.join(outputDir, "README.md");

const payload = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const eventById = new Map(payload.events.map((event) => [event.event_id, event]));

function is2023Time(value) {
  return typeof value === "string" && value.startsWith("2023-");
}

function allReferencedChainEventsIn2023(label) {
  return (label.chain_event_ids || []).every((eventId) => {
    const event = eventById.get(eventId);
    return event && is2023Time(event.time);
  });
}

const labels = {};
const referenced = new Set();

for (const [labelType, items] of Object.entries(payload.labels)) {
  labels[labelType] = items.filter((label) => {
    const keep = is2023Time(label.anchor_time) && allReferencedChainEventsIn2023(label);
    if (!keep) return false;

    referenced.add(label.anchor_event_id);
    for (const eventId of label.candidate_event_ids || []) referenced.add(eventId);
    for (const eventId of label.fiat_event_ids || []) referenced.add(eventId);
    for (const eventId of label.chain_event_ids || []) referenced.add(eventId);
    return true;
  });
}

const events = payload.events.filter((event) => referenced.has(event.event_id));

function countBy(items, keyFn) {
  return items.reduce((acc, item) => {
    const key = keyFn(item);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

const labelCounts = Object.fromEntries(
  Object.entries(labels).map(([labelType, items]) => [labelType, items.length]),
);

const relationCounts = Object.fromEntries(
  Object.entries(labels).map(([labelType, items]) => [
    labelType,
    countBy(items, (item) => item.relation_shape),
  ]),
);

const output = {
  generated_at: new Date().toISOString(),
  source_file: path.relative(root, inputPath),
  filter: {
    year: 2023,
    rule: "Keep labels whose anchor_time is in 2023 and whose referenced chain events are all in 2023.",
  },
  summary: {
    event_count: events.length,
    event_direction_counts: countBy(events, (event) => event.direction),
    label_counts: labelCounts,
    relation_counts: relationCounts,
  },
  events,
  labels,
};

const totalLabels = Object.values(labelCounts).reduce((sum, value) => sum + value, 0);
const readme = `# 2023 Stablecoin Labels

This directory contains a 2023-only subset of the high-confidence stablecoin labels.

Selection rule:

- Keep labels whose \`anchor_time\` is in 2023.
- Keep only labels whose referenced chain events are also in 2023, so the subset aligns with the 2023 Tron raw-data experiment scope.

Summary:

| Item | Count |
| --- | ---: |
| Referenced events | ${events.length} |
| Total labels | ${totalLabels} |
| fiat_buy_to_chain_withdrawal | ${labelCounts.fiat_buy_to_chain_withdrawal || 0} |
| fiat_sell_to_chain_deposit | ${labelCounts.fiat_sell_to_chain_deposit || 0} |

Generated from \`${path.relative(root, inputPath).replaceAll("\\", "/")}\`.
`;

fs.mkdirSync(outputDir, { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
fs.writeFileSync(readmePath, readme, "utf8");

console.log(`Wrote ${path.relative(root, outputPath)}`);
console.log(JSON.stringify(output.summary, null, 2));
