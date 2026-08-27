# Gold Set（种子期 v0）

- `seed_zh.jsonl`：LLM 预标种子 30 条，`status: pending_review`，**未经人工复核，禁止用于任何对外数字**。
- 复核流程见 `../codebook/frames_zh.md` §3：人工接受/修正/驳回 → `status: reviewed` → 双人 α ≥ 0.7 后升格 gold。
- 字段：text（句子）、frames（概率分布，Σ=1）、engine（预标引擎）、status、reviewer（复核后填）、notes。
