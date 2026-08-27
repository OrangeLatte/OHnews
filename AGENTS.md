# OH!News 工程守则（项目级，与全局 AGENTS.md 合并）

- 工具链：uv workspace（本仓库唯一 Python 工具链，不用 conda）
- QA Gate：`uv run ruff check packages && uv run ruff format packages && uv run pytest -v`
- 测试：`sensitive` marker 默认跳过；`sanity` = Phase 0 门禁
- 结构：`packages/*` 单向依赖；oh-contracts 零内部依赖零 IO（purity 测试强制）
- PIT 纪律：一切指标只用 t-1 及更早信息
- 措辞：NDI = 叙事分歧指数（描述性监测）；禁用"预测器/择时"
- 提交：conventional commits，scope = 包名，模块单独 commit
- 架构真源：`docs/BLUEPRINT.md`；SDD 流程：`.specify/` + `/speckit.*`
- 日志：opencode 会话镜像 `uv run python scripts/dev/collect_logs.py` → `.opencode/logs/`（gitignored）
