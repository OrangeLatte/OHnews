# OH!News 项目宪法 v1.0

> 完整架构依据：`docs/BLUEPRINT.md`（蓝图 v2，五专家辩论裁决 A-H）。

## 原则

1. **Spec-First**：任何功能先过 `/speckit.specify → clarify → plan → tasks`，无 spec 不实现。
2. **Idempotent**：采集与分析全链路幂等——双 hash（url_hash + content_hash）+ item_key 唯一主键；重复执行零副作用。
3. **Compliance-First**：非商业用途；公开仓库零 zlibrary/BPC 关联；敏感规则仅本地注入（`config/sources.bpc.yaml`，gitignored）；尊重 robots 与限速；绝不静默换源。
4. **Verification**：三效度分离——测量效度（ρ≥0.8 硬门禁）/ 方向性（软门禁）/ 认知价值（UX）；NDI 措辞纪律：**永不使用"预测器/择时"**。
5. **Modularity**：`packages/*` 单向依赖；oh-contracts 零内部依赖、零 IO（CI purity 测试强制）；模块 = commit 边界（conventional commits + scope）。
6. **Non-Commercial**：输出为分析与风险信号，不构成投资建议，不输出买卖指令。

## 工程约定

- Python 工具链：**uv workspace**（本仓库唯一工具链）；QA Gate = `uv run ruff check packages && uv run ruff format packages && uv run pytest -v`。
- PIT 纪律：一切指标只用 t-1 及更早信息。
- 敏感测试 marker `sensitive` 默认跳过。
