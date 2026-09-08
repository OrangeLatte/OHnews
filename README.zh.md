# OH!News — 认知闭环情报终端（非商业）

OH!News 把多语种财经新闻流炼成**叙事分歧监测**，并引导用户走完一条完整的认知闭环：

> **发现变化 → 检验证据 → 形成自己的判断 → 持续追踪。**

四个入口：**NOW**（`/observe`）· **INVESTIGATE**（`/cases`）· **WATCH**（`/watch`）· **MEMORY**（`/archive`）。

> **措辞纪律（写死）**：NDI（叙事分歧指数）是**描述性**监测指标（EPU 式条件变量），**不是收益预测器**；全项目禁用「预测 / 择时 / 买卖」表述。所有结论强制证据链（主张 → 原文摘录 + 来源 + PIT 时间）。

## 你能得到什么

| 层 | 职责 |
|---|---|
| `oh-sources` | 8 种适配器（rss / gdelt / fred / json_api / html / browser / reddit_cdp 等）→ Bronze parquet 分区 |
| `oh-pipeline` | 事件聚类、立场标注、NDI（Jeffreys 平滑 JSD + bootstrap 置信区间）、Hero 质量门、叙事场 |
| `oh-storage` | SQLite 存储族：silver（事件/立场/NDI/标注/拆解）、research（案例/元素提取/证据 span）、tracking、archive、belief、产品埋点 |
| `oh-agents` | langgraph Agent 族：18 元素**文章拆解**（分块并发+span 三级锚点）、六型**研究报告**、**跟踪预警**统一单元、**档案与档案报纸**、跨语言翻译（「翻译学家」prompt 工作流）、parent 总控台 |
| `oh-api` | FastAPI 门面：observe 看板、cases、tracking、archive、agent/*、简报与变化总览聚合 |
| `oh-llm` | 三层模型路由（io/execute/strategic）+ JSON 模式护栏 + 候选降级 + 并发限制 |
| `web` | Next.js 16 + React 19 报纸风浅色界面，21 语言 i18n（含 RTL）、「ⓘ」术语浮窗、带弃权语义的图表封装 |

## 快速开始

```bash
# 后端（FastAPI，端口 8787）
uv run python scripts/dev/serve.py --port 8787

# 前端（Next.js dev，端口 3001）
cd web && npx next dev -p 3001

# 采集 + 标注（适合 cron；采集后自动补词典标注）
uv run python scripts/dev/cron_collect.py --days 1
uv run python scripts/dev/run_daily.py --days 15   # 管道：事件 → 立场 → NDI
```

模型 Key（DeepSeek / 智谱 / Tavily）在 `/settings/developer` 配置，落盘 `data/runtime_keys.json`（chmod 600）。未配置 Key 时所有 LLM 功能**诚实降级**（词典/离线引擎并如实标注）。

## 演示

仓库当前处于**演示态**：15 天数据、两条全文信源（英文 `guardian_world`、中文 `wallstreetcn`）、两条端到端种子案例（收件箱 → 案例研究 → 追踪 → 档案）。

- 英文导览：[`docs/demo_en/`](docs/demo_en/)（10 张截图，界面英文）
- 中文导览：[`docs/demo_zh/`](docs/demo_zh/)（10 张截图，界面中文）

## 测试与质量门

```bash
uv run ruff check packages && uv run pytest -q        # 后端（600+ 测试）
cd web && npx tsc --noEmit && npx eslint .            # 前端
```

## 文档

- 架构与数据模型真源：[`docs/RECONSTRUCTION.md`](docs/RECONSTRUCTION.md)（另见 `ARCHITECTURE_MAP.md`、`archi.svg`）
- 已被取代的规格与规划记录迁出至 `../OHnews_backup_20260909/docs_migrated/`（迁移原因见该目录 `MIGRATION_NOTES.md`）；裁剪前完整数据备份同目录。

## 许可与边界

仅限非商业研究用途。不输出交易建议；系统永不改写用户判断；Agent 不修改确定性指标。
