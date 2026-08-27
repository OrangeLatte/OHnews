# OH!News — Agent 原生的市场叙事情报台（非商业）

把多语种财经新闻流炼成 **叙事分歧指数 NDI**（Narrative Divergence Index）：同一经济事件在不同信源簇（官方 / 市场化媒体 / 社媒）下的框架分布差异，配上假设卡与证据链，供研究员做情境感知。

> **措辞纪律（写死）**：NDI 是描述性监测指标（EPU 式条件变量），**不是收益预测器**；全项目禁用"预测 / 择时"表述。对外数字要求 `--min-per-source 10`。

- 架构真源：[docs/BLUEPRINT.md](docs/BLUEPRINT.md)（八项裁决 A–H + 三张 mermaid 架构图 + Phase 0–7）
- 红线：非商业研究用途；不输出买卖指令；所有结论强制证据链（claim → 原文摘录 + 来源 + PIT 时间）

## 架构一页

```
oh-sources ──► Bronze(parquet 分区) ──► 事件聚合 ──► Tagger(规则85/小模型10/LLM5%)
                                                        │ stance_table
                                                        ▼
                                            DivergenceEngine(纯统计 JSD) ──► NDI(Gold)
                                                        │ 只读
                                                        ▼
                                    hypothesis_gen / evidence_interpreter(LLM，永不写回 NDI)
                                                        │
                                        analysis_graph(langgraph) / research_graph / 晨报 / 预警
```

- **采集层无 LLM**：纯 Python + 幂等主键 `(source, external_id, ts)` + 指数退避 + 备用源链 + 健康度自动降级（裁决 C）
- **NDI 只来自 stance_table**：LLM 输出只读，永不写回分歧度量（裁决 A）
- **三级模型路由**：io=deepseek-v4-flash / execute=glm-5.3-flash / strategic=glm-5.3，fallback 链 + 输出 schema 契约不变（裁决 E）
- **单进程 + SQLite WAL**：FastAPI + langgraph 同进程；docker-compose 提供可选部署态（裁决 D）

## 快速开始（macOS / Linux / Windows）

依赖：[uv](https://docs.astral.sh/uv/)（唯一 Python 工具链）+ Node ≥ 20（仅前端）。

```bash
git clone <repo> OHnews && cd OHnews
uv sync                # 全部 7 个 workspace 包 + dev 依赖

# 可选：LLM 功能（补盲标注 / 假设卡 / 问诊）。无 key 时自动降级纯统计链路。
export DEEPSEEK_API_KEY=sk-...
export ZHIPU_API_KEY=...
```

### 1) 回填数据源 → Bronze

```bash
uv run python scripts/backfill.py --days 7          # 全部 enabled 源
uv run python scripts/backfill.py --days 2 --only wallstreetcn,fed_press
```

52+ 活源（中/英/日/韩/德/法/意/俄；L1 央行与官方 → L4 社媒），配置在 `config/sources.yaml`：
`enabled: false` 的源零开销；`fallbacks` 备用链；`window_days` 稀疏源窗口放大；`proxy_url` 代理。
源探活（不写库）：`uv run python scripts/probe_sources.py --hours 48`。

### 2) 日度流水线：Bronze → 事件 → NDI → Gold

```bash
# 纯统计（无 key 可跑）
uv run python scripts/dev/run_daily.py --days 7

# LLM 补盲（官方簇标注）+ 假设卡 + 证据解读
uv run python scripts/dev/run_daily.py --days 7 --llm

# within-language（裁决 F）：--language zh 或 en；缺省混算 all
uv run python scripts/dev/run_daily.py --days 7 --llm --language zh

# 分批：--limit 5 --skip 5
```

事件合格门：去重文章 ≥3 且涉及源 ≥2（`--min-articles/--min-sources`）；NDI 源级样本门 `--min-per-source`（开发态 2，**对外数字必须 10**）。样本不足时输出 `abstain`（弃权），不编数字。

### 3) 起服务看板

```bash
uv run python scripts/dev/serve.py                   # API + 轻量 dashboard: http://127.0.0.1:8787

cd web && npm install && npm run dev                 # Next.js 前端: http://localhost:3000
```

页面：`/` NDI 概览 · `/events/[id]` 证据链（一键复制引用）· `/brief` 晨报 · `/research` 问诊 · `/alerts` 预警订阅 · `/decisions` 决策日志 · `/dev/monitor` opencode 会话镜像。

### Docker 部署态（可选）

```bash
cd docker && docker compose up --build    # api:8787 + web:${WEB_PORT:-3100}
```

数据卷挂载宿主 `data/`、`config/`；keys 经环境变量注入。

## 定时调度

不内置调度器（零依赖原则），用系统 cron：

```cron
30 7 * * *  cd /path/to/OHnews && uv run python scripts/backfill.py --days 2 >> data/cron.log 2>&1
45 7 * * *  cd /path/to/OHnews && uv run python scripts/dev/run_daily.py --days 7 --llm >> data/cron.log 2>&1
```

## 配置一览

| 文件 | 用途 |
|---|---|
| `config/sources.yaml` | 采集源注册表（tier / language / credibility_prior / enabled / fallbacks） |
| `config/models.yaml` | 三级模型路由 + fallback 链 + 并发护栏（timeout 120s / max_concurrency 3 / retry 2） |
| `config/codebook/frames_zh.md` | 五框架标注 codebook（Entman 四功能操作化） |
| `config/gold_set/` | 标注委员会产物（`annotated_*.jsonl` 为生成物，gitignored） |
| `opencode.json.example` | opencode 开发环境三级路由模板（复制为 `opencode.json` 启用） |
| `config/sources.bpc.yaml.example` | 敏感源壳（裁决 G：绕过配置仅本地注入，gitignored，仓库零字节） |

## 仓库结构

```
packages/
  oh-contracts   schema/枚举/常量（零依赖零 IO，purity 测试强制）
  oh-storage     Bronze parquet + Silver/Gold SQLite(WAL) + 仓储 Protocol
  oh-sources     6 类适配器(RSS/JSON API/HTML/GDELT/FRED/Reddit-CDP) + 回退链 + 健康度
  oh-pipeline    实体注册表 / 事件聚合 / 规则 Tagger / 统计层(JSD+bootstrap) / 验证门禁
  oh-llm         Provider 抽象 + ModelRouter + 标注委员会（双标注员+裁决员+Krippendorff α）
  oh-agents      analysis_graph / research_graph / 晨报 / 预警 / 决策日志 / HITL
  oh-api         FastAPI(8 端点组) + SSE 总线 + dashboard
web/             Next.js 16 + Tailwind + shadcn + ECharts
docs/BLUEPRINT.md  架构真源
.specify/        SDD 流程（/speckit.* 命令）
```

## 开发

```bash
uv run ruff check packages && uv run ruff format packages
uv run pytest -v            # sensitive 默认跳过；sanity = Bronze→Silver→Gold 门禁
```

- QA Gate 与守则见 [AGENTS.md](AGENTS.md)；提交遵循 conventional commits（scope = 包名）
- opencode 会话镜像：`uv run python scripts/dev/collect_logs.py` → `.opencode/logs/`（gitignored）
- Reddit 数据需登录态：先 `scripts/dev/export_reddit_cookies.py`（CDP 连接已登录 Chrome），源默认 `enabled: false`

## 诚实局限

1. **基准=模型共识**：框架标注由双 LLM 独立标注 + 第三模型裁决（实测 Krippendorff α=0.88），非人工标注 ground truth；测量效度硬门禁（人工标注 50 事件，ρ≥0.8）未完成前，NDI 仅作内部描述性监测。
2. **官方簇稀疏**：L1 官方源日产出 1–5 条，无 LLM 补盲时 NDI 大概率 abstain（设计行为：样本门拒绝无官方对照的温差计算）。
3. **NDI 值区分度**：单行源经 Dirichlet 平滑后区分度有限；值区间窄不代表信号弱。
4. **中文主流媒体 RSS 生态已死**（实测大量 404/假 feed）：中文通道靠 JSON API + 政务搜索 API 补齐；JS 渲染站（统计局/证监会等）留待 playwright 壳（Phase 6+）。
5. **GDELT 仅作覆盖度信号**，不作 tone/frame（已知噪声大、英文中心）；网络可达性依赖代理环境。
6. 源 URL 存活以探测日为准，失效计入健康度自动降级；`sources.yaml` 死源台账留档。
