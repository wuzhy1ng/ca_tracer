# CA Tracer Research Plan

## 0. 当前状态

项目目标是从链下银行卡交易记录出发，在波场链稳定币转账记录中发现候选匹配，并用大模型程序合成智能体自动生成、迭代和沉淀匹配算子。

当前仓库已经具备三类基础资产：

- 原始链上数据：`data/raw_data/2023-01-01.csv`，目前是 Tron 原始交易 CSV，约 3GB。
- 交易所取证标签：`data/raw_label/{binance,gate,okx}`，包含 Binance、Gate、OKX Excel 取证记录。
- 已整理标签：`data/label/all/label_tags.json` 与 `data/label/stablecoins/stablecoin_label_tags.json`。

本轮已补充 2023 年实验专用标签子集：

- 路径：`data/label/stablecoins_2023/stablecoin_label_tags_2023.json`
- 筛选规则：保留 `anchor_time` 在 2023 年，且引用到的链上事件也在 2023 年的 high 置信度稳定币标签。
- 规模：2421 个被引用事件，2345 条标签。
- 标签类型：
  - `fiat_buy_to_chain_withdrawal`: 1709 条
  - `fiat_sell_to_chain_deposit`: 636 条

## 1. 数据层整理

### 1.1 标签数据标准化

目标：把标签文件整理成可复现实验输入，而不是只作为说明材料存在。

需要完成：

- 固定主实验标签文件：`data/label/stablecoins_2023/stablecoin_label_tags_2023.json`。
- 明确每条标签的实验语义：
  - `fiat_buy_to_chain_withdrawal`: 从链下买币记录出发，找后续链上提币。
  - `fiat_sell_to_chain_deposit`: 从链下卖币记录出发，回溯此前链上充币。
- 保留 `event_id`、`anchor_event_id`、`candidate_event_ids` 作为唯一索引。
- 后续评测只把 `high` 标签作为正例，`medium/low` 暂不作为 ground truth。

输出物：

- `data/label/stablecoins_2023/README.md`
- `data/label/stablecoins_2023/stablecoin_label_tags_2023.json`
- 后续可追加：`data/label/stablecoins_2023/eval_cases.jsonl`

### 1.2 2023 原始链上数据按日期落盘

目标：将 2023 年全量 Tron 原始交易数据按日切分，支持快速按时间窗检索。

建议目录：

```text
data/raw_data/tron_daily/2023/01/2023-01-01.csv
data/raw_data/tron_daily/2023/01/2023-01-02.csv
...
data/raw_data/tron_daily/2023/12/2023-12-31.csv
```

处理原则：

- 每个日文件保留原始字段：`block_hash`、`block_number`、`raw_data`、`timestamp`、`transaction_hash`、`transaction_index`。
- 时间统一使用毫秒时间戳 `timestamp`。
- 不在原始日文件中做复杂解析，避免破坏可追溯性。
- 另建解码后的稳定币转账文件，和原始日文件分离。

### 1.3 TRC20 稳定币转账解码

目标：从 Tron 原始交易中提取稳定币 transfer 事件，形成检索友好的标准表。

建议输出目录：

```text
data/processed/tron_stablecoin_transfers/2023/01/2023-01-01.parquet
```

标准字段：

| 字段 | 说明 |
| --- | --- |
| `txid` | 交易哈希 |
| `block_number` | 区块号 |
| `timestamp` | 毫秒时间戳 |
| `time` | 标准时间字符串 |
| `token_contract` | TRC20 合约地址 |
| `asset` | `USDT`、`USDC` 等 |
| `from_address` | 转出地址 |
| `to_address` | 转入地址 |
| `amount_raw` | 原始整数金额 |
| `amount` | 按 decimals 归一化金额 |
| `direction_hint` | 可选，后续结合交易所地址库推断 deposit/withdrawal |

第一阶段先支持 USDT TRC20。USDT 合约地址以配置文件维护，不写死在算子里。

## 2. 检索层设计

目标：给一个银行卡交易或标签锚点，快速找出时间窗内的链上候选集合。

### 2.1 时间窗索引

按日期切分后，检索逻辑应只读取覆盖窗口内的日文件。例如：

- 买币到提币：读取 `[anchor_time, anchor_time + window]`
- 卖币回溯充币：读取 `[anchor_time - window, anchor_time]`

默认窗口建议：

- 快速扫描：1 天
- 主实验：7 天
- 宽松消融：30 天

### 2.2 候选预过滤

候选预过滤只做低风险过滤：

- 资产一致：默认 USDT。
- 金额上限：候选单笔金额不超过目标金额加容差。
- 时间方向正确。
- 金额粗筛：保留相对误差不超过 10% 的单笔，组合搜索可以放宽。

不要在检索层做过强规则，否则会把真实召回提前过滤掉。

## 3. 匹配算子库

目标：先有一组可运行 baseline，再让 agent 在此基础上合成和修复新算子。

### 3.1 算子接口

建议接口：

```python
def match(anchor, candidates, context) -> list[MatchResult]:
    ...
```

`MatchResult` 至少包含：

- `candidate_ids`
- `score`
- `rank`
- `amount_gap`
- `time_gap`
- `relation_shape`
- `evidence`
- `risk_flags`

### 3.2 第一批 baseline 算子

优先实现以下算子：

- `nearest_single_transfer`: 单笔金额最接近。
- `time_decay_single_transfer`: 金额接近基础上引入时间衰减。
- `sequence_sum_transfer`: 按时间连续组合求和，支持一对多。
- `subset_sum_limited_transfer`: 限制组合长度的近似子集和。
- `round_amount_penalty`: 对 1000、5000、10000、50000 等常见整数金额加误匹配风险提示。
- `unique_candidate_boost`: 当候选集合内只有一个高相似候选时提升置信度。

### 3.3 领域一致性确认模块

确认模块不直接生成候选，而是在候选生成后做二次审查：

- 金额相似：相对误差、绝对误差、是否整数高频金额。
- 时间相似：方向正确、窗口长度、是否异常延迟。
- 候选唯一性：同窗口内是否存在多个近似金额竞争者。
- 组合合理性：组合笔数、是否连续、是否跨越过长时间。

输出应是解释而不是单一分数，便于司法复核。

## 4. Agent 程序合成流程

目标：从固定规则系统升级为可生成、测试、修复和沉淀算子的智能体系统。

### 4.1 流程

1. 输入一个失败或低置信 case。
2. 先跑现有算子库。
3. 若 Top-K 未命中或解释不充分，进入 agent synthesis。
4. Agent 生成 plan：分析失败原因、提出新算子假设、说明适用边界。
5. 代码相似度拦截：如果新算子和已有算子过近，不进入执行。
6. 多 agent 生成若干候选算子。
7. 在验证集 case 上评估召回、误匹配和解释质量。
8. 选择最优算子，沉淀为带注释函数代码。
9. 写入算子库和经验库。

### 4.2 算子知识库

每个算子沉淀时记录：

- 名称
- 适用场景
- 不适用场景
- 核心代码
- 触发特征
- 通过的 case
- 失败的 case
- 解释模板

### 4.3 相似度拦截

第一版可以用两层判断：

- 文本层：函数源码 token Jaccard 相似度。
- 行为层：在固定小样本上的输出候选集合相似度。

只有文本和行为都明显不同的新算子，才进入候选库。

## 5. 实验设计

### 5.1 主任务

输入：2023 年链下稳定币相关法币交易锚点。

输出：在 2023 年 Tron 稳定币转账记录中召回真实链上候选交易。

主评测文件：

- `data/label/stablecoins_2023/stablecoin_label_tags_2023.json`

### 5.2 数据划分

建议按时间切分，避免同一模式泄漏：

- 训练/开发：2023-01 至 2023-08
- 验证：2023-09 至 2023-10
- 测试：2023-11 至 2023-12

如果后续样本在年底偏少，可改为按 account/source_file 分组切分。

### 5.3 指标

主指标：

- Top-1 Recall
- Top-5 Recall
- Top-10 Recall
- False Match Rate
- Manual Review Rate

系统指标：

- 平均候选数量
- 平均运行时间
- P95 运行时间
- 平均组合搜索次数
- 算子修复轮数

解释指标：

- 金额解释覆盖率
- 时间解释覆盖率
- 竞争候选风险提示覆盖率
- 组合关系解释覆盖率

### 5.4 消融实验

建议消融：

- 无一对多组合搜索。
- 无常见整数金额风险提示。
- 无候选唯一性确认。
- 无 agent 合成，仅 baseline 算子库。
- 时间窗从 1 天、3 天、7 天、30 天变化。
- 组合长度从 1、2、3、5、8 变化。

## 6. 推荐开发顺序

### Phase 1: 数据可用

- 固化 2023 标签子集。
- 完成 2023 Tron 原始 CSV 按日切分。
- 实现 TRC20 USDT transfer 解码。
- 建立日级稳定币转账检索接口。

验收标准：

- 给定任意 2023 标签锚点，能读取对应时间窗的链上候选集合。
- 能根据 txid 回溯原始 CSV 行。

### Phase 2: Baseline 可跑

- 实现统一算子接口。
- 实现 4 到 6 个 baseline 算子。
- 生成 Top-K 排名和解释。
- 跑通 2023 标签集评测。

验收标准：

- 输出 `eval_results/baseline_2023.json`。
- 至少包含 Top-1、Top-5、Top-10、误匹配率、运行时间。

### Phase 3: Agent 闭环

- 实现 case 失败分析。
- 实现算子生成、执行沙箱、相似度拦截。
- 实现算子经验库。
- 对失败 case 进行自动修复实验。

验收标准：

- 至少展示 10 个 baseline 失败 case 被新算子修复。
- 每个新增算子都有适用边界和解释模板。

### Phase 4: 论文实验

- 完成主实验表。
- 完成消融表。
- 完成典型案例分析。
- 完成误匹配风险分析。
- 整理贡献叙事：数据集、智能体、实验论证。

验收标准：

- 能支撑论文中的实验章节和方法章节。
- 所有数字可从脚本复现。

## 7. 近期最优先的三件事

1. 把 2023 全年 Tron 原始数据按日存好，并建立文件清单。
2. 写 USDT TRC20 transfer 解码器，生成标准化链上转账表。
3. 用 `stablecoin_label_tags_2023.json` 跑第一个非 agent baseline，先拿到 Top-K 召回的基线数字。

## 8. 2026-05-31 实现审计与修正计划

另一个 agent 已经实现了第一版骨架，包括 raw CSV 检查、USDT TRC20 解码、baseline 算子、候选检索接口、算子知识库和 agent synthesis skeleton。当前版本可以作为原型继续推进，但不能把现有 baseline 数字作为论文实验结果。主要原因是候选池、raw 数据时间、txid 对齐、方向判定和沙箱安全还没有闭环。

### 8.1 当前实现可保留的部分

- `algos/baseline.py` 已经形成了统一的 `MatchContext`、`MatchResult` 和多个 baseline 算子，适合作为第一版算子库入口。
- `tools/run_baseline_2023.py` 已经能输出 Top-K、候选数和运行时间等指标，后续可继续作为评测入口。
- `daos/tron.py` 已经提供 raw CSV 流式读取、USDT calldata 解码、JSONL 读取和时间窗查询接口，方向正确。
- `agents/synthesis.py`、`agents/sandbox.py`、`agents/validator.py` 已经把“失败 case -> 算子 proposal -> 相似度检查 -> 验证报告”的结构搭出来，可以继续扩展。

### 8.2 P0 阻塞问题

#### P0-1: 当前 raw sample 不是 2023 年数据

证据：

- `data/processed/raw_tron_csv_inspection_sample.json` 显示 `data/raw_data/2023-01-01.csv` 的前 1000 行时间范围是 `2024-07-01 00:00:00` 到 `2024-07-01 00:00:27`。
- `IMPLEMENTATION_STATUS.md` 也记录了同样结论。

影响：

- 现有 raw CSV 不能用于 2023 年标签实验。
- 任何基于该文件解码出的 transfer 都不能和 `stablecoin_label_tags_2023.json` 对齐。

修正：

- 重新确认 `data/raw_data` 中每个文件的真实时间范围。
- 按真实日期重命名或移动，不能仅凭文件名判断日期。
- 增加 `data/raw_data/manifest_2023.json`，记录每个日文件的 `min_time`、`max_time`、`row_count`、`usdt_transfer_count`。

验收：

- 2023 年实验只读取 manifest 中 `min_time/max_time` 覆盖 2023 年的文件。
- 文件名、manifest 时间范围和标签时间三者一致。

#### P0-2: baseline 默认候选池来自标签文件，存在候选泄漏

证据：

- `tools/run_baseline_2023.py` 默认 `candidate_source = "label_events_chain_transfer_pool"`。
- `algos/baseline.py` 在 `all_chain_events is None` 时使用 `payload["events"]` 中的 chain_transfer 事件作为候选池。
- `eval_results/baseline_2023_summary.json` 的候选源就是 `label_events_chain_transfer_pool`。

影响：

- 候选池只包含标签文件里出现过的链上事件，不是 2023 年 Tron 全量候选。
- Top-K recall 会显著高估，false match rate 也不是真实链上检索场景下的误匹配率。

修正：

- 将当前结果明确标记为 `oracle_candidate_pool_baseline`。
- 主实验必须使用 decoded raw Tron transfer 作为候选源。
- 报告中分开列出：
  - `oracle_candidate_pool_baseline`
  - `raw_chain_candidate_pool_baseline`
  - `agent_synthesis_result`

验收：

- `baseline_2023_summary.json` 中不得再把标签候选池结果命名为主 baseline。
- 论文表格只使用 raw-chain candidate pool 结果。

#### P0-3: 外部 decoded transfer 与标签 truth id 不能命中

证据：

- `daos/tron.py` 的 `transfer_to_chain_event` 默认生成 `event_id = "tx_{txid}"`。
- `algos/baseline.py` 的 `exact_hit` 使用 `candidate_ids == truth_ids`，truth id 是 `evt_...`。
- 因此使用 `--candidate-jsonl` 时，即使 txid 相同，也会因为 id 空间不同而判为未命中。

影响：

- 一旦切到 raw decoded transfer，Top-K recall 可能接近 0，评测失真。

修正：

- 评测命中逻辑改为支持多键匹配：
  - 首选 `txid` 集合匹配。
  - 若无 txid，再退回 `event_id`。
- 在构建 case 时保存 `truth_event_ids` 和 `truth_txids`。
- `MatchResult` 保留 `candidate_ids`，同时增加 `candidate_txids`。

验收：

- 对标签中有 txid 的链上事件，raw decoded transfer 中同 txid 能被判为 hit。
- `--candidate-jsonl` 路径至少能在一个已知样例上命中。

#### P0-4: TRC20 calldata 地址解码疑似错误

证据：

- `daos/tron.py` 中 `to_hex = "41" + data[8 + 24 : 8 + 64]`。
- Tron ABI 样例中 address 参数通常已经包含 `41` 前缀。当前逻辑可能重复添加 `41` 并截断尾部字节。

影响：

- `to_address` 可能错误，后续无法做交易所地址识别、deposit/withdrawal 方向推断和人工复核。

修正：

- 用已知 txid 对照 Tronscan 或原始标签地址，验证解码地址。
- 正确逻辑应显式处理两种情况：
  - ABI 参数含 21 字节 Tron 地址：取最后 42 hex。
  - ABI 参数只含 20 字节 EVM 地址：补 `41` 后再 base58。
- 增加单元测试，至少覆盖当前 CSV 第一条 USDT transfer 样例。

验收：

- decoded `to_address` 与链上浏览器或标签地址一致。
- 地址转换函数有固定样例测试。

#### P0-5: 时间体系没有统一

证据：

- `daos/tron.py` 的 `timestamp_to_iso` 使用 UTC 时间并去掉 tzinfo。
- 标签数据中 Binance 已做 +8 小时校正，其他交易所也更像本地时间语义。

影响：

- raw 链上候选和标签锚点可能相差 8 小时，直接影响时间窗、排序和召回。

修正：

- 明确全系统时间标准：建议内部统一 UTC，展示时再转本地时间。
- 标签事件增加 `time_utc` 或在加载时转换。
- raw decoded transfer 增加 `time_utc` 和 `time_local`，评测只使用一个标准字段。

验收：

- 任一标签样例的 txid 在 raw decoded transfer 中匹配时，时间差与链上浏览器一致。

### 8.3 P1 重要改进

#### P1-1: deposit/withdrawal 方向不能靠 `--candidate-direction both`

当前 `load_transfer_events(direction="both")` 会把每个 transfer 复制成 deposit 和 withdrawal 两条候选，而且 `event_id` 相同。这会制造重复候选，也不能证明方向正确。

修正：

- 建立交易所地址库或案件地址上下文。
- 根据 `from_address/to_address` 与交易所地址、涉案地址关系推断 `chain_deposit` 或 `chain_withdrawal`。
- 在无法判断时标记 `chain_transfer_unknown`，不混入主实验方向指标。

#### P1-2: sandbox 不是强隔离执行环境

当前 `agents/sandbox.py` 使用 AST 限制后直接 `exec`。虽然禁用了 import/open/eval/exec 等名称，但没有超时、内存限制或进程隔离。生成代码可以用允许的 `range/list/sorted` 构造超大计算，导致进程卡死。

修正：

- 把生成算子放到独立进程执行。
- 设置 timeout、内存上限和最大候选数。
- validation 超时应记录为 sandbox failure。

#### P1-3: similarity blocking 只有源码相似度实际生效

`agents/synthesis.py` 调用 `is_too_similar(proposal.source)` 时没有传入 `candidate_signature` 和 `sample_cases`，所以行为相似度始终是 0。

修正：

- 对候选算子在固定 case 集上运行，生成 behavior signature。
- 同时使用 source similarity 和 behavior similarity。
- 把相似度报告写入 operator proposal。

#### P1-4: generated operator 验证只看召回，不看误匹配退化

`agents/validator.py` 当前只统计 generated operator 在失败 case 上的 Top-K recall，没有和 baseline 合并比较，也没有控制 false match growth。

修正：

- validation 输入应分为 failed cases、held-out validation cases、round-amount hard negatives。
- 记录新算子加入前后的 Top-K recall、Top-1 precision proxy、manual review rate。
- 只有验证集提升且 hard negatives 不退化时，才能进入 operator library。

#### P1-5: 当前 false match 和 manual review 指标定义过粗

当前 `false_match_rate = false_top1 / case_count`，本质是 Top-1 exact miss rate，不是真正误匹配率。`manual_review_rate` 基于固定分数阈值和 risk flag，也没有人工复核成本标定。

修正：

- 将现有指标重命名为 `top1_exact_miss_rate`。
- 新增 `competitive_false_positive_rate`：在同金额/同时间窗 hard negative 集上统计错误高分候选。
- manual review 规则单独版本化，例如 `review_policy_v1`。

### 8.4 P2 工程质量改进

- Python 环境不可用时，当前项目无法复跑脚本。需要补 `requirements.txt` 或 `pyproject.toml`，并修复 `.venv` 指向失效的问题。
- `settings.json` 中存在 Tronscan API key，应迁移到环境变量并从仓库中移除。
- `eval_results/*.json` 是生成物，建议只保留 summary 或加入 `.gitignore`，避免大文件和旧结果混淆。
- `PLAN.md`、部分 PowerShell 输出会出现 mojibake，文件本身是 UTF-8。Windows 下建议统一用 `Get-Content -Encoding utf8` 或 Node/Python 读取。
- `operator_library/builtin_operators.json` 应增加版本号、生成脚本 hash、适用数据范围和验证结果。

### 8.5 修正后的最近执行顺序

1. 先修复 Python 环境，保证 `python tools/run_baseline_2023.py --help` 能运行。
2. 重新盘点 raw CSV 时间范围，生成 `data/raw_data/manifest_2023.json`。
3. 修复 TRC20 地址解码，并用已知 txid 做单元测试。
4. 将评测命中逻辑改为支持 `txid` 对齐。
5. 生成 raw-chain candidate pool 的 baseline 结果，并与 oracle candidate pool 结果分表记录。
6. 再继续 agent synthesis，且必须加进程级 sandbox 和 held-out validation。

