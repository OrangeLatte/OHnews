"""Research Store（Clean-slate Phase 1）：research.sqlite 新库读写层。

边界纪律：
- 不触碰 silver.sqlite / bronze Parquet（统计真源只读）。
- 新表新库，旧库零改动；迁移是复制+标记，回滚=删新库。
- Schema 用 PRAGMA user_version 版本化，MIGRATIONS 逐步幂等执行。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oh_contracts.agent_runtime import (
    WORKFLOWS,
    AgentRun,
    AgentThread,
    HITLRequest,
    ModelUsage,
    ToolCall,
)
from oh_contracts.artifacts import Artifact, ArtifactRevision, UserCommit
from oh_contracts.case import (
    AnalysisRun,
    Claim,
    ComparisonSet,
    ElementExtraction,
    EvidenceSpan,
    ResearchCase,
)
from oh_contracts.monitoring import (
    CollectionPlan,
    CollectionRun,
    Monitor,
    MonitorRun,
    MonitorUpdate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

from oh_storage.connection import connect

SCHEMA_VERSION = 13

_DDL_V1 = """
CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'candidate',
    origin      TEXT NOT NULL DEFAULT 'question',
    context_note TEXT NOT NULL DEFAULT '',
    created_by  TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases (status, updated_at);

CREATE TABLE IF NOT EXISTS document_revisions (
    document_revision_id TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    canonical_url   TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL DEFAULT '',
    language        TEXT NOT NULL DEFAULT '',
    published_at    TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    UNIQUE (document_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_revisions_document ON document_revisions (document_id);

CREATE TABLE IF NOT EXISTS claims (
    claim_id    TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    statement   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'unverified',
    span_ids    TEXT NOT NULL DEFAULT '[]',
    created_by  TEXT NOT NULL DEFAULT 'agent',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_case ON claims (case_id);

CREATE TABLE IF NOT EXISTS evidence_spans (
    span_id       TEXT PRIMARY KEY,
    document_revision_id TEXT NOT NULL REFERENCES document_revisions(document_revision_id),
    char_start    INTEGER NOT NULL,
    char_end      INTEGER NOT NULL,
    quote         TEXT NOT NULL,
    polarity      TEXT NOT NULL DEFAULT 'supports',
    CHECK (char_end > char_start)
);

CREATE TABLE IF NOT EXISTS extractions (
    extraction_id TEXT PRIMARY KEY,
    case_id       TEXT NOT NULL DEFAULT '',
    document_revision_id TEXT NOT NULL REFERENCES document_revisions(document_revision_id),
    element_key   TEXT NOT NULL,
    normalized_value TEXT NOT NULL DEFAULT '',
    span_ids      TEXT NOT NULL DEFAULT '[]',
    confidence    REAL NOT NULL DEFAULT 0,
    uncertainty_reason TEXT NOT NULL DEFAULT '',
    analysis_run_id TEXT NOT NULL DEFAULT '',
    human_status  TEXT NOT NULL DEFAULT 'unreviewed'
);
CREATE INDEX IF NOT EXISTS idx_extractions_rev ON extractions (document_revision_id);
CREATE INDEX IF NOT EXISTS idx_extractions_case ON extractions (case_id);

CREATE TABLE IF NOT EXISTS comparison_sets (
    comparison_id TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    revision_ids TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id      TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    engine      TEXT NOT NULL DEFAULT 'llm',
    model       TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'queued',
    input_refs  TEXT NOT NULL DEFAULT '[]',
    output_artifact_id TEXT,
    token_in    INTEGER NOT NULL DEFAULT 0,
    token_out   INTEGER NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_case ON analysis_runs (case_id, kind);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(case_id),
    klass       TEXT NOT NULL,
    title       TEXT NOT NULL,
    report_type TEXT,
    created_at  TEXT NOT NULL,
    current_revision_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_artifacts_case ON artifacts (case_id, klass);

CREATE TABLE IF NOT EXISTS artifact_revisions (
    revision_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    run_id      TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'draft',
    legacy      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_revisions_artifact ON artifact_revisions (artifact_id, status);

CREATE TABLE IF NOT EXISTS user_commits (
    commit_id   TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES artifact_revisions(revision_id),
    user_note   TEXT NOT NULL DEFAULT '',
    committed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitors (
    monitor_id  TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_ref  TEXT NOT NULL,
    question    TEXT NOT NULL,
    trigger_conditions TEXT NOT NULL DEFAULT '[]',
    window      TEXT NOT NULL DEFAULT '7d',
    schedule    TEXT NOT NULL DEFAULT '6h',
    status      TEXT NOT NULL DEFAULT 'active',
    notification TEXT NOT NULL DEFAULT 'in_app',
    last_confirmed_snapshot_at TEXT,
    case_id     TEXT,
    created_by  TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitor_runs (
    run_id      TEXT PRIMARY KEY,
    monitor_id  TEXT NOT NULL REFERENCES monitors(monitor_id),
    status      TEXT NOT NULL DEFAULT 'queued',
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS monitor_updates (
    update_id   TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES monitor_runs(run_id),
    monitor_id  TEXT NOT NULL REFERENCES monitors(monitor_id),
    summary     TEXT NOT NULL,
    delta       TEXT NOT NULL DEFAULT '{}',
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    suggested_case_action TEXT NOT NULL DEFAULT 'none',
    reviewed    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_updates_pending ON monitor_updates (monitor_id, reviewed);

CREATE TABLE IF NOT EXISTS collection_plans (
    plan_id     TEXT PRIMARY KEY,
    source_ids  TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'scheduled',
    schedule    TEXT NOT NULL DEFAULT '',
    time_range  TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT 'user',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id      TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES collection_plans(plan_id),
    status      TEXT NOT NULL DEFAULT 'queued',
    progress    REAL NOT NULL DEFAULT 0,
    items_collected INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_threads (
    thread_id   TEXT PRIMARY KEY,
    case_id     TEXT,
    title       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id      TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL REFERENCES agent_threads(thread_id),
    workflow    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    context     TEXT NOT NULL DEFAULT '{}',
    model       TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    tool_call_ids TEXT NOT NULL DEFAULT '[]',
    hitl_ids    TEXT NOT NULL DEFAULT '[]',
    checkpoint_ref TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread ON agent_runs (thread_id, status);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id     TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES agent_runs(run_id),
    tool        TEXT NOT NULL,
    ok          INTEGER NOT NULL DEFAULT 1,
    latency_ms  INTEGER NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS hitl_requests (
    hitl_id     TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES agent_runs(run_id),
    action      TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'awaiting_user',
    decided_by  TEXT NOT NULL DEFAULT '',
    decided_at  TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_hitl_pending ON hitl_requests (status);

CREATE TABLE IF NOT EXISTS prompt_versions (
    prompt_id   TEXT NOT NULL,
    version     TEXT NOT NULL,
    system_prompt_hash TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (prompt_id, version)
);

CREATE TABLE IF NOT EXISTS model_usage (
    usage_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    provider    TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL,
    token_in    INTEGER NOT NULL DEFAULT 0,
    token_out   INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT '',
    ts          TEXT NOT NULL
);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, _DDL_V1),
    (
        2,
        """
CREATE TABLE IF NOT EXISTS case_documents (
    case_id              TEXT NOT NULL,
    document_revision_id TEXT NOT NULL REFERENCES document_revisions (document_revision_id),
    added_at             TEXT NOT NULL,
    PRIMARY KEY (case_id, document_revision_id)
);
CREATE INDEX IF NOT EXISTS idx_case_documents_case ON case_documents (case_id, added_at);
""",
    ),
    (
        3,
        # HITL 决策留痕（审计）：MonitorUpdate 被用户处理时记录决策与关联 Case。
        """
ALTER TABLE monitor_updates ADD COLUMN decision TEXT NOT NULL DEFAULT '';
ALTER TABLE monitor_updates ADD COLUMN decision_case_id TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        4,
        # 异步运行协议：workflow 富结果（比较矩阵/质询清单等）随 run 终态持久化，
        # 轮询端点可取回（POST 202 后客户端只拿 run_id）。
        """
ALTER TABLE analysis_runs ADD COLUMN output_json TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        5,
        # 研究收件箱：记录 bronze item_key，支撑 cased/dissected 标记与跨库去重。
        """
ALTER TABLE document_revisions ADD COLUMN external_key TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        6,
        # Case 标题（列表展示主键；question 保留为研究问题正文）。
        """
ALTER TABLE cases ADD COLUMN title TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        7,
        # 三概念分离：needs_review 是 Update 审核状态，不是 Monitor 配置状态
        # （active/paused/error）。旧迁移/旧脚本把脏值写进 monitors.status，统一修复为 active。
        """
UPDATE monitors SET status = 'active' WHERE status = 'needs_review';
""",
    ),
    (
        8,
        # 文档唯一标识：入案文章保留原题（同源多文可区分，用户要求）。
        """
ALTER TABLE document_revisions ADD COLUMN title TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        9,
        # Monitor 执行闭环（P0-B）：阶段/计数随 run 终态持久化，轮询端点可取回
        # （模式同 analysis_runs.output_json v4）。
        """
ALTER TABLE monitor_runs ADD COLUMN output_json TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        10,
        # Archive 闭环（P0-C）：UserCommit 记录确认者（HITL 确认主体）。
        """
ALTER TABLE user_commits ADD COLUMN created_by TEXT NOT NULL DEFAULT '';
""",
    ),
    (
        11,
        # 拆解数据版本化（R1）：set_status 引入「当前发布集」语义（current|superseded）。
        # 迁移清理存量：每 document_revision 仅最新 analysis_run 批次保持 current，
        # 其余（旧 run 批次 + 无运行归属遗留行）置 superseded——不可变留痕，不物理删除；
        # 同一批次内幂等键重复（revision+element_key+span 坐标+normalized_value 全等）
        # 保留 rowid 最小一条 current，其余物理删除（同 run 重复是同一次运行产物）。
        """
ALTER TABLE extractions ADD COLUMN set_status TEXT NOT NULL DEFAULT 'current';

DROP TABLE IF EXISTS _v11_latest_run;
DROP TABLE IF EXISTS _v11_span_sig;
DROP TABLE IF EXISTS _v11_ext_sig;

CREATE TEMP TABLE _v11_latest_run AS
SELECT document_revision_id, analysis_run_id FROM (
    SELECT document_revision_id, analysis_run_id,
           ROW_NUMBER() OVER (
               PARTITION BY document_revision_id
               ORDER BY started_at DESC, first_rowid DESC
           ) AS rn
    FROM (
        SELECT e.document_revision_id AS document_revision_id,
               e.analysis_run_id AS analysis_run_id,
               COALESCE(MAX(r.started_at), '') AS started_at,
               MIN(e.rowid) AS first_rowid
        FROM extractions e
        LEFT JOIN analysis_runs r ON r.run_id = e.analysis_run_id
        WHERE e.analysis_run_id != ''
        GROUP BY e.document_revision_id, e.analysis_run_id
    )
) WHERE rn = 1;

UPDATE extractions SET set_status = 'superseded'
WHERE document_revision_id IN (SELECT document_revision_id FROM _v11_latest_run)
  AND NOT EXISTS (
      SELECT 1 FROM _v11_latest_run lr
      WHERE lr.document_revision_id = extractions.document_revision_id
        AND lr.analysis_run_id = extractions.analysis_run_id
  );

CREATE TEMP TABLE _v11_span_sig AS
SELECT x.rid AS rid, GROUP_CONCAT(ss.char_start || ':' || ss.char_end) AS sig
FROM (
    SELECT e.rowid AS rid, je.value AS span_id
    FROM extractions e
    JOIN json_each(CASE WHEN json_valid(e.span_ids) THEN e.span_ids ELSE '[]' END) je
) x
JOIN evidence_spans ss ON ss.span_id = x.span_id
GROUP BY x.rid;

CREATE TEMP TABLE _v11_ext_sig AS
SELECT e.rowid AS rid,
       e.document_revision_id AS document_revision_id,
       e.element_key AS element_key,
       e.normalized_value AS normalized_value,
       COALESCE(sg.sig, '') AS span_sig
FROM extractions e
LEFT JOIN _v11_span_sig sg ON sg.rid = e.rowid
WHERE e.set_status = 'current';

DELETE FROM extractions
WHERE rowid IN (
    SELECT rid FROM (
        SELECT rid, ROW_NUMBER() OVER (
            PARTITION BY document_revision_id, element_key, normalized_value, span_sig
            ORDER BY rid
        ) AS rn
        FROM _v11_ext_sig
    ) WHERE rn > 1
);

DROP TABLE IF EXISTS _v11_latest_run;
DROP TABLE IF EXISTS _v11_span_sig;
DROP TABLE IF EXISTS _v11_ext_sig;
""",
    ),
    (
        12,
        # 证据坐标重建（P0-2）：evidence_spans 增加 anchor 双重校验与分层语义列。
        # prefix/suffix = 原文中 span 前后各 ~30 字符切片（锚点校验原料，非 UI 渲染）；
        # mark = direct（逐字锚定原文高亮）| inferred（无合法原文位置，当前持久层只写 direct，
        # 无锚元素的诚实标记在 extractions.uncertainty_reason=span_anchor_failed）。
        """
ALTER TABLE evidence_spans ADD COLUMN prefix TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_spans ADD COLUMN suffix TEXT NOT NULL DEFAULT '';
ALTER TABLE evidence_spans ADD COLUMN mark TEXT NOT NULL DEFAULT 'direct';
""",
    ),
    (
        13,
        # Claim 状态机 7 态闭集：旧 4 态值改名对齐（refuted→contradicted, uncertain→disputed）。
        """
UPDATE claims SET status='contradicted' WHERE status='refuted';
UPDATE claims SET status='disputed' WHERE status='uncertain';
""",
    ),
)

# v3 新增的审计列不属于 MonitorUpdate 契约模型，行转换时剔除。
_MONITOR_UPDATE_EXTRA_COLS = ("decision", "decision_case_id")


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(text: str, default: Any) -> Any:
    if not text:
        return default
    return json.loads(text)


class ResearchStore:
    """research.sqlite 统一读写（单写者；方法内短事务）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---------- schema ----------

    def ensure_schema(self) -> int:
        """幂等执行 MIGRATIONS；返回最终 schema 版本。

        ALTER TABLE ADD COLUMN 在 SQLite 中不可重放（无 IF NOT EXISTS）。
        user_version 异常回拨后重放会报 duplicate column——此类语句先查
        table_info，列已存在则跳过该句（其余语句照常执行）。
        """
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version, ddl in MIGRATIONS:
            if version <= current:
                continue
            statements = [s.strip() for s in ddl.split(";") if s.strip()]
            for stmt in statements:
                m = re.search(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)", stmt, re.IGNORECASE)
                if m:
                    table, column = m.group(1), m.group(2)
                    cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
                    if column in cols:
                        continue
                self._conn.execute(stmt)
            self._conn.execute(f"PRAGMA user_version = {version}")
            self._conn.commit()
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    @classmethod
    def open(cls, db_path: Path | str) -> ResearchStore:
        conn = connect(db_path)
        store = cls(conn)
        store.ensure_schema()
        return store

    def close(self) -> None:
        """关闭底层连接（脚本/CLI 用；请求路径由 thread-local 工厂管理生命周期）。"""
        self._conn.close()

    # ---------- cases ----------

    def create_case(self, case: ResearchCase) -> None:
        self._conn.execute(
            "INSERT INTO cases (case_id, title, question, status, origin, context_note,"
            " created_by, created_at, updated_at, closed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                case.case_id,
                case.title,
                case.question,
                case.status,
                case.origin,
                case.context_note,
                case.created_by,
                case.created_at,
                case.updated_at,
                case.closed_at,
            ),
        )
        self._conn.commit()

    def get_case(self, case_id: str) -> ResearchCase | None:
        row = self._conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return ResearchCase(**dict(row)) if row else None

    def list_cases(self, status: str | None = None) -> list[ResearchCase]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM cases WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM cases ORDER BY updated_at DESC").fetchall()
        return [ResearchCase(**dict(r)) for r in rows]

    def update_case_status(
        self, case_id: str, status: str, *, updated_at: str, closed_at: str | None = None
    ) -> bool:
        cur = self._conn.execute(
            "UPDATE cases SET status = ?, updated_at = ?, closed_at = ? WHERE case_id = ?",
            (status, updated_at, closed_at, case_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---------- documents ----------

    def add_document_revision(
        self,
        document_revision_id: str,
        document_id: str,
        *,
        source_id: str,
        body: str,
        fetched_at: str,
        canonical_url: str = "",
        content_hash: str = "",
        language: str = "",
        published_at: str = "",
        external_key: str = "",
        title: str = "",
    ) -> None:
        """不可变正文版本；同 (document_id, content_hash) 重复写入幂等跳过。"""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO document_revisions"
            " (document_revision_id, document_id, source_id, canonical_url,"
            "  content_hash, language, published_at, body, fetched_at, external_key, title)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                document_revision_id,
                document_id,
                source_id,
                canonical_url,
                content_hash,
                language,
                published_at,
                body,
                fetched_at,
                external_key,
                title,
            ),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"document_revision conflict: {document_revision_id}")

    def cased_keys(self) -> set[str]:
        """已入案文章的 external_key 集合（收件箱 cased 标记）。"""
        rows = self._conn.execute(
            "SELECT DISTINCT external_key FROM document_revisions WHERE external_key != ''"
        ).fetchall()
        return {r["external_key"] for r in rows}

    def dissected_keys(self) -> set[str]:
        """已拆解文章的 external_key 集合（收件箱 dissected 标记）。"""
        rows = self._conn.execute(
            "SELECT DISTINCT dr.external_key FROM document_revisions dr"
            " JOIN extractions e ON e.document_revision_id = dr.document_revision_id"
            " WHERE dr.external_key != ''"
        ).fetchall()
        return {r["external_key"] for r in rows}

    def get_document_revision(self, document_revision_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM document_revisions WHERE document_revision_id = ?",
            (document_revision_id,),
        ).fetchone()
        return dict(row) if row else None

    def link_case_document(self, case_id: str, document_revision_id: str, added_at: str) -> None:
        """Case ↔ 版本挂载关系（幂等；schema v2）。"""
        self._conn.execute(
            "INSERT OR IGNORE INTO case_documents (case_id, document_revision_id, added_at)"
            " VALUES (?,?,?)",
            (case_id, document_revision_id, added_at),
        )
        self._conn.commit()

    def case_documents(self, case_id: str) -> list[dict]:
        """某 Case 挂载的全部不可变版本（按挂载时间倒序，不含正文）。"""
        rows = self._conn.execute(
            "SELECT r.document_revision_id, r.document_id, r.source_id, r.canonical_url,"
            " r.language, r.published_at, r.fetched_at, r.content_hash, r.title, c.added_at"
            " FROM case_documents c JOIN document_revisions r"
            " ON c.document_revision_id = r.document_revision_id"
            " WHERE c.case_id = ? ORDER BY c.added_at DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- claims & spans ----------

    def add_span(self, span: EvidenceSpan) -> None:
        self._conn.execute(
            "INSERT INTO evidence_spans"
            " (span_id, document_revision_id, char_start, char_end, quote, polarity,"
            "  prefix, suffix, mark)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                span.span_id,
                span.document_revision_id,
                span.char_start,
                span.char_end,
                span.quote,
                span.polarity,
                span.prefix,
                span.suffix,
                span.mark,
            ),
        )
        self._conn.commit()

    def spans_by_ids(self, span_ids: Sequence[str]) -> list[EvidenceSpan]:
        out: list[EvidenceSpan] = []
        for sid in span_ids:
            row = self._conn.execute(
                "SELECT * FROM evidence_spans WHERE span_id = ?", (sid,)
            ).fetchone()
            if row:
                out.append(EvidenceSpan(**dict(row)))
        return out

    def add_claim(self, claim: Claim) -> None:
        self._conn.execute(
            "INSERT INTO claims"
            " (claim_id, case_id, statement, kind, status, span_ids, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                claim.claim_id,
                claim.case_id,
                claim.statement,
                claim.kind,
                claim.status,
                _dumps(claim.span_ids),
                claim.created_by,
                claim.created_at,
            ),
        )
        self._conn.commit()

    def claims_for_case(self, case_id: str) -> list[Claim]:
        rows = self._conn.execute(
            "SELECT * FROM claims WHERE case_id = ? ORDER BY created_at", (case_id,)
        ).fetchall()
        return [Claim(**{**dict(r), "span_ids": _loads(r["span_ids"], [])}) for r in rows]

    def update_claim_status(self, claim_id: str, status: str) -> bool:
        """Claim 状态机流转（引擎 verdict 写回或用户终审 user_confirmed）。"""
        cur = self._conn.execute(
            "UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self._conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if row is None:
            return None
        return Claim(**{**dict(row), "span_ids": _loads(row["span_ids"], [])})

    # ---------- extractions ----------

    def add_extraction(self, extraction: ElementExtraction, *, set_status: str = "current") -> None:
        """写入拆解元素行；set_status 存储层概念（不入 ElementExtraction 契约）：
        current=当前发布集成员，superseded=被后续成功运行置换/降级兜底（隐藏不删）。"""
        self._conn.execute(
            "INSERT INTO extractions"
            " (extraction_id, case_id, document_revision_id, element_key,"
            "  normalized_value, span_ids, confidence, uncertainty_reason,"
            "  analysis_run_id, human_status, set_status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                extraction.extraction_id,
                extraction.case_id,
                extraction.document_revision_id,
                extraction.element_key,
                extraction.normalized_value,
                _dumps(extraction.span_ids),
                extraction.confidence,
                extraction.uncertainty_reason,
                extraction.analysis_run_id,
                extraction.human_status,
                set_status,
            ),
        )
        self._conn.commit()

    def supersede_extractions(self, document_revision_id: str) -> int:
        """发布集置换第一步：该版本全部 current 行置 superseded，返回置换单数。"""
        cur = self._conn.execute(
            "UPDATE extractions SET set_status = 'superseded'"
            " WHERE document_revision_id = ? AND set_status = 'current'",
            (document_revision_id,),
        )
        self._conn.commit()
        return cur.rowcount

    def extractions_for_revision(
        self, document_revision_id: str, *, include_superseded: bool = False
    ) -> list[dict]:
        """某版本的拆解结果；默认只返回当前发布集（current），旧批次隐藏。"""
        sql = "SELECT * FROM extractions WHERE document_revision_id = ?"
        if not include_superseded:
            sql += " AND set_status = 'current'"
        sql += " ORDER BY element_key"
        rows = self._conn.execute(sql, (document_revision_id,)).fetchall()
        return [{**dict(r), "span_ids": _loads(r["span_ids"], [])} for r in rows]

    def set_extraction_human_status(self, extraction_id: str, human_status: str) -> bool:
        cur = self._conn.execute(
            "UPDATE extractions SET human_status = ? WHERE extraction_id = ?",
            (human_status, extraction_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---------- comparisons ----------

    def add_comparison(self, comparison: ComparisonSet) -> None:
        self._conn.execute(
            "INSERT INTO comparison_sets (comparison_id, case_id, revision_ids, note, created_at)"
            " VALUES (?,?,?,?,?)",
            (
                comparison.comparison_id,
                comparison.case_id,
                _dumps(comparison.document_revision_ids),
                comparison.note,
                comparison.created_at,
            ),
        )
        self._conn.commit()

    # ---------- analysis runs ----------

    def add_analysis_run(self, run: AnalysisRun) -> None:
        self._conn.execute(
            "INSERT INTO analysis_runs"
            " (run_id, case_id, kind, engine, model, prompt_version, status,"
            "  input_refs, output_artifact_id, token_in, token_out, error,"
            "  started_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                run.case_id,
                run.kind,
                run.engine,
                run.model,
                run.prompt_version,
                run.status,
                _dumps(run.input_refs),
                run.output_artifact_id,
                run.token_in,
                run.token_out,
                run.error,
                run.started_at,
                run.finished_at,
            ),
        )
        self._conn.commit()

    def active_run(self, kind: str, case_id: str, input_refs_json: str) -> dict | None:
        """幂等协议：同 kind+case+输入引用的活跃（queued/running）运行。"""
        row = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE kind = ? AND case_id = ? AND input_refs = ?"
            " AND status IN ('queued','running')"
            " ORDER BY started_at DESC LIMIT 1",
            (kind, case_id, input_refs_json),
        ).fetchone()
        if row is None:
            return None
        return {**dict(row), "input_refs": _loads(row["input_refs"], [])}

    def start_analysis_run(self, run_id: str) -> bool:
        """queued → running（后台执行器领任务）。"""
        cur = self._conn.execute(
            "UPDATE analysis_runs SET status = 'running' WHERE run_id = ? AND status = 'queued'",
            (run_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def reap_stale_runs(self, finished_at: str = "") -> int:
        """启动清理：进程重启遗留的 queued/running → failed（interrupted）。"""
        cur = self._conn.execute(
            "UPDATE analysis_runs SET status = 'failed',"
            " error = 'interrupted by restart', finished_at = ?"
            " WHERE status IN ('queued','running')",
            (finished_at,),
        )
        self._conn.commit()
        return cur.rowcount

    def reap_stale_monitor_runs(self, finished_at: str = "") -> int:
        """启动清理：monitor_runs 遗留 queued/running → failed。

        僵尸 run 若不清理，POST /runs 的幂等复用会永久命中它，
        导致后续运行请求永远不被真实执行。
        """
        cur = self._conn.execute(
            "UPDATE monitor_runs SET status = 'failed',"
            " error = 'interrupted by restart', finished_at = ?"
            " WHERE status IN ('queued','running')",
            (finished_at,),
        )
        self._conn.commit()
        return cur.rowcount

    def cancel_analysis_run(self, run_id: str, finished_at: str = "") -> bool:
        """用户取消：仅 queued/running 可取消；终态不可逆转。"""
        cur = self._conn.execute(
            "UPDATE analysis_runs SET status = 'cancelled', error = 'cancelled by user',"
            " finished_at = ? WHERE run_id = ? AND status IN ('queued','running')",
            (finished_at, run_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def finish_analysis_run(
        self,
        run_id: str,
        *,
        status: str,
        token_in: int = 0,
        token_out: int = 0,
        error: str = "",
        output_artifact_id: str | None = None,
        output_json: str = "",
        finished_at: str = "",
    ) -> bool:
        """终态写入；已取消/已终态的运行不覆盖（防后台线程与 cancel 竞态）。"""
        cur = self._conn.execute(
            "UPDATE analysis_runs SET status = ?, token_in = ?, token_out = ?,"
            " error = ?, output_artifact_id = COALESCE(?, output_artifact_id),"
            " output_json = CASE WHEN ? != '' THEN ? ELSE output_json END,"
            " finished_at = ? WHERE run_id = ? AND status IN ('queued','running')",
            (
                status,
                token_in,
                token_out,
                error,
                output_artifact_id,
                output_json,
                output_json,
                finished_at,
                run_id,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def analysis_runs(self, limit: int = 50) -> list[AnalysisRun]:
        """最近分析运行（Agent 面板 / 案例时间线索引）。"""
        rows = self._conn.execute(
            "SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            AnalysisRun(
                **{
                    **{k: v for k, v in dict(r).items() if k != "output_json"},
                    "input_refs": _loads(r["input_refs"], []),
                }
            )
            for r in rows
        ]

    def get_analysis_run(self, run_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        data = {k: v for k, v in dict(row).items() if k != "output_json"}
        data["input_refs"] = _loads(row["input_refs"], [])
        data["output"] = _loads(row["output_json"] or "", None)
        return data

    def has_case_run(self, case_id: str, kind: str, status: str = "") -> bool:
        """B6 校验用：case 内是否跑过指定 kind 的分析（如 challenge 必经门）。

        status 非空时限定该状态（异步协议下只有 succeeded 的 challenge 才过门）。
        """
        sql = "SELECT 1 FROM analysis_runs WHERE case_id = ? AND kind = ?"
        params: list[str] = [case_id, kind]
        if status:
            sql += " AND status = ?"
            params.append(status)
        row = self._conn.execute(sql + " LIMIT 1", params).fetchone()
        return row is not None

    def run_outputs_for_case(
        self, case_id: str, kind: str, *, status: str = "succeeded", limit: int = 3
    ) -> list[dict]:
        """Case 内指定 kind 运行的富结果 output（新→旧；报告证据包引用挑战/比较产物）。"""
        rows = self._conn.execute(
            "SELECT output_json FROM analysis_runs"
            " WHERE case_id = ? AND kind = ? AND status = ? AND output_json != ''"
            " ORDER BY started_at DESC LIMIT ?",
            (case_id, kind, status, limit),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            data = _loads(r["output_json"], None)
            if isinstance(data, dict):
                out.append(data)
        return out

    def decisions_for_case(self, case_id: str) -> list[dict]:
        """A4：MonitorUpdate 的 HITL 决策（已关联本 case 的审计记录）。"""
        rows = self._conn.execute(
            "SELECT update_id, monitor_id, summary, decision, decision_case_id, created_at"
            " FROM monitor_updates WHERE decision_case_id = ? AND decision != ''"
            " ORDER BY created_at",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- artifacts & commit ----------

    def create_artifact(self, artifact: Artifact) -> None:
        self._conn.execute(
            "INSERT INTO artifacts"
            " (artifact_id, case_id, klass, title, report_type, created_at, current_revision_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                artifact.artifact_id,
                artifact.case_id,
                artifact.klass,
                artifact.title,
                artifact.report_type,
                artifact.created_at,
                artifact.current_revision_id,
            ),
        )
        self._conn.commit()

    def add_artifact_revision(self, revision: ArtifactRevision) -> None:
        self._conn.execute(
            "INSERT INTO artifact_revisions"
            " (revision_id, artifact_id, run_id, content, status, legacy, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                revision.revision_id,
                revision.artifact_id,
                revision.run_id,
                _dumps(revision.content),
                revision.status,
                int(revision.legacy),
                revision.created_at,
            ),
        )
        self._conn.commit()

    def commit_revision(self, revision_id: str, commit: UserCommit) -> dict[str, str]:
        """HITL 确认落档：事务内置换 current 指针并写 UserCommit。

        返回 {"artifact_id", "superseded_revision_id"}；revision 不存在抛 KeyError。
        """
        row = self._conn.execute(
            "SELECT artifact_id, status FROM artifact_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()
        if not row:
            raise KeyError(revision_id)
        artifact_id = row["artifact_id"]
        cur = self._conn.execute(
            "SELECT current_revision_id FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        superseded = cur["current_revision_id"] if cur else None
        with self._conn:
            if superseded:
                self._conn.execute(
                    "UPDATE artifact_revisions SET status = 'superseded' WHERE revision_id = ?",
                    (superseded,),
                )
            self._conn.execute(
                "UPDATE artifact_revisions SET status = 'committed' WHERE revision_id = ?",
                (revision_id,),
            )
            self._conn.execute(
                "UPDATE artifacts SET current_revision_id = ? WHERE artifact_id = ?",
                (revision_id, artifact_id),
            )
            self._conn.execute(
                "INSERT INTO user_commits"
                " (commit_id, revision_id, user_note, committed_at, created_by)"
                " VALUES (?,?,?,?,?)",
                (
                    commit.commit_id,
                    commit.revision_id,
                    commit.user_note,
                    commit.committed_at,
                    commit.created_by,
                ),
            )
        return {"artifact_id": artifact_id, "superseded_revision_id": superseded or ""}

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return Artifact(**dict(row)) if row else None

    def get_artifact_by_revision(self, revision_id: str) -> Artifact | None:
        """revision 反查所属 Artifact（commit 门校验用）。"""
        row = self._conn.execute(
            "SELECT a.* FROM artifacts a"
            " JOIN artifact_revisions r ON r.artifact_id = a.artifact_id"
            " WHERE r.revision_id = ?",
            (revision_id,),
        ).fetchone()
        return Artifact(**dict(row)) if row else None

    def get_artifact_revision(self, revision_id: str) -> dict | None:
        """按 revision_id 取版本行（含 run_id，归档门校验报告源运行状态用）。"""
        row = self._conn.execute(
            "SELECT * FROM artifact_revisions WHERE revision_id = ?", (revision_id,)
        ).fetchone()
        if not row:
            return None
        return {**dict(row), "content": _loads(row["content"], {}), "legacy": bool(row["legacy"])}

    def artifact_revisions(self, artifact_id: str) -> list[dict]:
        rows = self._conn.execute(
            # rowid 平局决胜：同 microsecond 创建的版本按插入序稳定排列（版本链语义）
            "SELECT * FROM artifact_revisions WHERE artifact_id = ? ORDER BY created_at, rowid",
            (artifact_id,),
        ).fetchall()
        return [
            {**dict(r), "content": _loads(r["content"], {}), "legacy": bool(r["legacy"])}
            for r in rows
        ]

    def archive_list(self, klass: str | None = None) -> list[dict]:
        """只返回有 UserCommit 的正式档案（draft/草稿永不出现在 Archive）。"""
        sql = (
            "SELECT a.*, r.revision_id AS current_revision_id,"
            " r.created_at AS revision_created_at,"
            " c.commit_id AS commit_id, c.user_note AS commit_note,"
            " c.committed_at AS committed_at, c.created_by AS confirmed_by,"
            " cs.created_by AS case_created_by"
            " FROM artifacts a JOIN artifact_revisions r"
            " ON a.current_revision_id = r.revision_id"
            " JOIN user_commits c ON c.revision_id = r.revision_id"
            " LEFT JOIN cases cs ON cs.case_id = a.case_id"
            " WHERE r.status = 'committed'"
        )
        params: tuple = ()
        if klass:
            sql += " AND a.klass = ?"
            params = (klass,)
        sql += " ORDER BY c.committed_at DESC"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def monitor_runs_for(self, monitor_id: str, limit: int = 50) -> list[dict]:
        """监测器运行时间线（新→旧）；output_json 解析为 output（空则 None）。"""
        rows = self._conn.execute(
            "SELECT run_id, monitor_id, status, started_at, finished_at, error, output_json"
            " FROM monitor_runs WHERE monitor_id = ?"
            " ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (monitor_id, limit),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["output"] = _loads(d.pop("output_json", "") or "", None)
            out.append(d)
        return out

    def artifacts_for_case(self, case_id: str) -> list[dict]:
        """某 Case 的产物列表（chat case_context 卡等只读汇总用；不含正文）。"""
        rows = self._conn.execute(
            "SELECT artifact_id, case_id, klass, title, report_type, created_at,"
            " current_revision_id FROM artifacts WHERE case_id = ?"
            " ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def case_counts(self) -> dict[str, dict[str, int]]:
        """每 Case 的文档数/分析运行数聚合（列表卡片计数）。"""
        docs = dict(
            self._conn.execute(
                "SELECT case_id, COUNT(*) FROM case_documents GROUP BY case_id"
            ).fetchall()
        )
        runs = dict(
            self._conn.execute(
                "SELECT case_id, COUNT(*) FROM analysis_runs WHERE case_id != '' GROUP BY case_id"
            ).fetchall()
        )
        return {
            cid: {"n_documents": docs.get(cid, 0), "n_runs": runs.get(cid, 0)}
            for cid in set(docs) | set(runs)
        }

    # ---------- monitors ----------

    def create_monitor(self, monitor: Monitor) -> None:
        self._conn.execute(
            "INSERT INTO monitors"
            " (monitor_id, target_type, target_ref, question, trigger_conditions,"
            "  window, schedule, status, notification, last_confirmed_snapshot_at,"
            "  case_id, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                monitor.monitor_id,
                monitor.target_type,
                monitor.target_ref,
                monitor.question,
                _dumps(monitor.trigger_conditions),
                monitor.window,
                monitor.schedule,
                monitor.status,
                monitor.notification,
                monitor.last_confirmed_snapshot_at,
                monitor.case_id,
                monitor.created_by,
                monitor.created_at,
            ),
        )
        self._conn.commit()

    def list_monitors(self, status: str | None = None) -> list[Monitor]:
        sql = "SELECT * FROM monitors"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        rows = self._conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
        return [
            Monitor(**{**dict(r), "trigger_conditions": _loads(r["trigger_conditions"], [])})
            for r in rows
        ]

    def set_monitor_status(self, monitor_id: str, status: str) -> bool:
        cur = self._conn.execute(
            "UPDATE monitors SET status = ? WHERE monitor_id = ?",
            (status, monitor_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_monitor(
        self,
        monitor_id: str,
        *,
        question: str | None = None,
        trigger_conditions: list[str] | None = None,
        window: str | None = None,
        schedule: str | None = None,
        status: str | None = None,
    ) -> bool:
        """HITL 编辑监测器（仅更新给定字段，None 不动）。"""
        sets: list[str] = []
        params: list[str | list[str]] = []
        if question is not None:
            sets.append("question = ?")
            params.append(question)
        if trigger_conditions is not None:
            sets.append("trigger_conditions = ?")
            params.append(_dumps(trigger_conditions))
        if window is not None:
            sets.append("window = ?")
            params.append(window)
        if schedule is not None:
            sets.append("schedule = ?")
            params.append(schedule)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if not sets:
            return True
        params.append(monitor_id)
        cur = self._conn.execute(
            "UPDATE monitors SET " + ", ".join(sets) + " WHERE monitor_id = ?",  # noqa: S608
            params,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_monitor(self, monitor_id: str) -> bool:
        """删除监测器及其全部 runs/updates（连带清空，外部确认后调用）。"""
        cur = self._conn.execute("DELETE FROM monitors WHERE monitor_id = ?", (monitor_id,))
        self._conn.execute("DELETE FROM monitor_runs WHERE monitor_id = ?", (monitor_id,))
        self._conn.execute("DELETE FROM monitor_updates WHERE monitor_id = ?", (monitor_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def confirm_monitor_snapshot(self, monitor_id: str, confirmed_at: str) -> bool:
        cur = self._conn.execute(
            "UPDATE monitors SET last_confirmed_snapshot_at = ? WHERE monitor_id = ?",
            (confirmed_at, monitor_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def add_monitor_run(self, run: MonitorRun) -> None:
        self._conn.execute(
            "INSERT INTO monitor_runs (run_id, monitor_id, status, started_at, finished_at, error)"
            " VALUES (?,?,?,?,?,?)",
            (run.run_id, run.monitor_id, run.status, run.started_at, run.finished_at, run.error),
        )
        self._conn.commit()

    def finish_monitor_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: str = "",
        error: str = "",
        output_json: str = "",
    ) -> bool:
        """回写 MonitorRun 状态：status 必写；其余字段非空才写（running 过渡不擦历史值）。"""
        sets = ["status = ?"]
        params: list[str] = [status]
        fields = (("finished_at", finished_at), ("error", error), ("output_json", output_json))
        for col, val in fields:
            if val:
                sets.append(f"{col} = ?")  # noqa: S608
                params.append(val)
        params.append(run_id)
        cur = self._conn.execute(
            "UPDATE monitor_runs SET " + ", ".join(sets) + " WHERE run_id = ?",  # noqa: S608
            params,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def active_monitor_run(self, monitor_id: str) -> dict | None:
        """该 monitor 是否已有 queued/running run（幂等复用判定）。"""
        row = self._conn.execute(
            "SELECT run_id, status FROM monitor_runs"
            " WHERE monitor_id = ? AND status IN ('queued','running')"
            " ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (monitor_id,),
        ).fetchone()
        return dict(row) if row else None

    def add_monitor_update(self, update: MonitorUpdate) -> None:
        self._conn.execute(
            "INSERT INTO monitor_updates"
            " (update_id, run_id, monitor_id, summary, delta, evidence_refs,"
            "  suggested_case_action, reviewed, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                update.update_id,
                update.run_id,
                update.monitor_id,
                update.summary,
                _dumps(update.delta),
                _dumps(update.evidence_refs),
                update.suggested_case_action,
                int(update.reviewed),
                update.created_at,
            ),
        )
        self._conn.commit()

    def monitor_exists(self, monitor_id: str) -> bool:
        """monitor_id 是否已存在（迁移幂等检查用）。"""
        row = self._conn.execute(
            "SELECT 1 FROM monitors WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()
        return row is not None

    def monitor_run_exists(self, run_id: str) -> bool:
        """run_id 是否已存在（迁移幂等检查用）。"""
        row = self._conn.execute(
            "SELECT 1 FROM monitor_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row is not None

    def monitor_update_exists(self, update_id: str) -> bool:
        """update_id 是否已存在（迁移幂等检查用）。"""
        row = self._conn.execute(
            "SELECT 1 FROM monitor_updates WHERE update_id = ?", (update_id,)
        ).fetchone()
        return row is not None

    def _update_from_row(self, row: sqlite3.Row) -> MonitorUpdate:
        data = {k: v for k, v in dict(row).items() if k not in _MONITOR_UPDATE_EXTRA_COLS}
        return MonitorUpdate(
            **{
                **data,
                "delta": _loads(row["delta"], {}),
                "evidence_refs": _loads(row["evidence_refs"], []),
                "reviewed": bool(row["reviewed"]),
            }
        )

    def pending_updates(self, monitor_id: str | None = None) -> list[MonitorUpdate]:
        sql = "SELECT * FROM monitor_updates WHERE reviewed = 0"
        params: tuple = ()
        if monitor_id:
            sql += " AND monitor_id = ?"
            params = (monitor_id,)
        rows = self._conn.execute(sql + " ORDER BY created_at DESC", params).fetchall()
        return [self._update_from_row(r) for r in rows]

    def get_update(self, update_id: str) -> MonitorUpdate | None:
        """按 id 取 MonitorUpdate（review 决策前解析引用用）。"""
        row = self._conn.execute(
            "SELECT * FROM monitor_updates WHERE update_id = ?", (update_id,)
        ).fetchone()
        return self._update_from_row(row) if row else None

    def get_monitor(self, monitor_id: str) -> Monitor | None:
        row = self._conn.execute(
            "SELECT * FROM monitors WHERE monitor_id = ?", (monitor_id,)
        ).fetchone()
        if row is None:
            return None
        return Monitor(**{**dict(row), "trigger_conditions": _loads(row["trigger_conditions"], [])})

    def mark_update_reviewed(
        self,
        update_id: str,
        *,
        decision: str = "",
        decision_case_id: str = "",
    ) -> bool:
        """HITL 决策留痕：reviewed=1 并记录 decision / decision_case_id 审计列。"""
        cur = self._conn.execute(
            "UPDATE monitor_updates SET reviewed = 1, decision = ?, decision_case_id = ?"
            " WHERE update_id = ?",
            (decision, decision_case_id, update_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ---------- collection ----------

    def create_collection_plan(self, plan: CollectionPlan) -> None:
        self._conn.execute(
            "INSERT INTO collection_plans"
            " (plan_id, source_ids, mode, schedule, time_range, enabled, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                plan.plan_id,
                _dumps(plan.source_ids),
                plan.mode,
                plan.schedule,
                plan.time_range,
                int(plan.enabled),
                plan.created_by,
                plan.created_at,
            ),
        )
        self._conn.commit()

    def set_plan_enabled(self, plan_id: str, enabled: bool) -> bool:
        cur = self._conn.execute(
            "UPDATE collection_plans SET enabled = ? WHERE plan_id = ?",
            (int(enabled), plan_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def add_collection_run(self, run: CollectionRun) -> None:
        self._conn.execute(
            "INSERT INTO collection_runs"
            " (run_id, plan_id, status, progress, items_collected, last_error,"
            "  started_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                run.plan_id,
                run.status,
                run.progress,
                run.items_collected,
                run.last_error,
                run.started_at,
                run.finished_at,
            ),
        )
        self._conn.commit()

    def list_plans(self) -> list[CollectionPlan]:
        rows = self._conn.execute(
            "SELECT plan_id, source_ids, mode, schedule, time_range, enabled,"
            " created_by, created_at FROM collection_plans ORDER BY created_at DESC"
        ).fetchall()
        return [self._plan_from_row(r) for r in rows]

    def list_runs(self, plan_id: str | None = None, limit: int = 50) -> list[CollectionRun]:
        sql = (
            "SELECT run_id, plan_id, status, progress, items_collected, last_error,"
            " started_at, finished_at FROM collection_runs"
        )
        params: list[object] = []
        if plan_id:
            sql += " WHERE plan_id = ?"
            params.append(plan_id)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._run_from_row(r) for r in rows]

    def _plan_from_row(self, r: Any) -> CollectionPlan:
        return CollectionPlan(
            **{
                **dict(r),
                "source_ids": _loads(str(r["source_ids"]), []),
                "enabled": bool(r["enabled"]),
            }
        )

    def _run_from_row(self, r: Any) -> CollectionRun:
        return CollectionRun(**{**dict(r), "progress": float(r["progress"])})

    def finish_collection_run(
        self,
        run_id: str,
        *,
        status: str,
        progress: float,
        items_collected: int,
        error: str = "",
        finished_at: str = "",
    ) -> None:
        self._conn.execute(
            "UPDATE collection_runs SET status = ?, progress = ?, items_collected = ?,"
            " last_error = ?, finished_at = ? WHERE run_id = ?",
            (status, progress, items_collected, error, finished_at, run_id),
        )
        self._conn.commit()

    # ---------- agent runtime ----------

    def list_threads(self, limit: int = 20) -> list[AgentThread]:
        """线程列表（Agent 面板会话管理用）。"""
        rows = self._conn.execute(
            "SELECT * FROM agent_threads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [AgentThread(**dict(r)) for r in rows]

    def list_agent_runs(self, thread_id: str | None = None, limit: int = 20) -> list[AgentRun]:
        rows = self._conn.execute(
            "SELECT * FROM agent_runs"
            + (" WHERE thread_id = ?" if thread_id else "")
            + " ORDER BY started_at DESC LIMIT ?",
            (thread_id, limit) if thread_id else (limit,),
        ).fetchall()
        out: list[AgentRun] = []
        for r in rows:
            # workflow='plan' 等非 11 值闭集的运行不属于 AgentRun 契约（plan_runs 专查）
            if r["workflow"] not in WORKFLOWS:
                continue
            out.append(
                AgentRun(
                    **{
                        **dict(r),
                        "context": _loads(r["context"], None),
                        "tool_call_ids": _loads(r["tool_call_ids"], []),
                        "hitl_ids": _loads(r["hitl_ids"], []),
                    }
                )
            )
        return out

    def tool_calls_for_run(self, run_id: str) -> list[ToolCall]:
        rows = self._conn.execute(
            "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [ToolCall(**{**dict(r), "ok": bool(r["ok"])}) for r in rows]

    def create_thread(self, thread: AgentThread) -> None:
        self._conn.execute(
            "INSERT INTO agent_threads (thread_id, case_id, title, created_at) VALUES (?,?,?,?)",
            (thread.thread_id, thread.case_id, thread.title, thread.created_at),
        )
        self._conn.commit()

    def add_plan_run(
        self,
        run_id: str,
        *,
        case_id: str,
        question: str,
        steps: list[dict[str, Any]],
        model: str,
        created_at: str,
        status: str,
        error: str = "",
    ) -> None:
        """Parent 研究计划落库（agent_runs，workflow 列以 'plan' 标记类型）。

        agent_runs DDL 无独立 kind 列，plan 的明细节（kind/case_id/question/
        steps/model/created_at）整体存 context JSON；thread 侧幂等建
        'plan-{case_id}' 会话以满足 FK。status 为 'succeeded' 或 'failed'。
        """
        thread_id = f"plan-{case_id}"
        self._conn.execute(
            "INSERT OR IGNORE INTO agent_threads (thread_id, case_id, title, created_at)"
            " VALUES (?,?,?,?)",
            (thread_id, case_id, f"研究计划 · {case_id}", created_at),
        )
        context = _dumps(
            {
                "kind": "plan",
                "case_id": case_id,
                "question": question,
                "steps": steps,
                "model": model,
                "created_at": created_at,
            }
        )
        self._conn.execute(
            "INSERT INTO agent_runs"
            " (run_id, thread_id, workflow, status, context, model, prompt_version,"
            "  tool_call_ids, hitl_ids, checkpoint_ref, error, started_at, finished_at)"
            " VALUES (?,?,'plan',?,?,?, '', '[]', '[]', '', ?, ?, ?)",
            (run_id, thread_id, status, context, model, error, created_at, created_at),
        )
        self._conn.commit()

    def plan_runs(self, case_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        """kind=plan 的 agent_runs（新→旧），context JSON 解析为明细节。"""
        rows = self._conn.execute(
            "SELECT run_id, status, context, error, started_at FROM agent_runs"
            " WHERE workflow = 'plan' ORDER BY started_at DESC LIMIT 200"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            ctx = _loads(r["context"], {})
            if case_id and ctx.get("case_id") != case_id:
                continue
            out.append(
                {
                    "run_id": str(r["run_id"]),
                    "status": str(r["status"]),
                    "created_at": str(ctx.get("created_at") or r["started_at"]),
                    "case_id": str(ctx.get("case_id") or ""),
                    "question": str(ctx.get("question") or ""),
                    "steps": list(ctx.get("steps") or []),
                    "model": str(ctx.get("model") or ""),
                    "error": str(r["error"] or ""),
                }
            )
            if len(out) >= limit:
                break
        return out

    def case_run_kinds(self, case_id: str) -> list[str]:
        """Case 内跑过的 analysis_runs kind 去重清单（Parent 规划上下文）。"""
        rows = self._conn.execute(
            "SELECT DISTINCT kind FROM analysis_runs WHERE case_id = ?", (case_id,)
        ).fetchall()
        return [str(r["kind"]) for r in rows]

    def add_agent_run(self, run: AgentRun) -> None:
        self._conn.execute(
            "INSERT INTO agent_runs"
            " (run_id, thread_id, workflow, status, context, model, prompt_version,"
            "  tool_call_ids, hitl_ids, checkpoint_ref, error, started_at, finished_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.run_id,
                run.thread_id,
                run.workflow,
                run.status,
                _dumps(run.context.model_dump()) if run.context else "{}",
                run.model,
                run.prompt_version,
                _dumps(run.tool_call_ids),
                _dumps(run.hitl_ids),
                run.checkpoint_ref,
                run.error,
                run.started_at,
                run.finished_at,
            ),
        )
        self._conn.commit()

    def finish_agent_run(
        self,
        run_id: str,
        *,
        status: str,
        error: str = "",
        checkpoint_ref: str = "",
        finished_at: str = "",
    ) -> None:
        self._conn.execute(
            "UPDATE agent_runs SET status = ?, error = ?, checkpoint_ref = ?,"
            " finished_at = ? WHERE run_id = ?",
            (status, error, checkpoint_ref, finished_at, run_id),
        )
        self._conn.commit()

    def add_tool_call(self, call: ToolCall) -> None:
        self._conn.execute(
            "INSERT INTO tool_calls (call_id, run_id, tool, ok, latency_ms, error)"
            " VALUES (?,?,?,?,?,?)",
            (call.call_id, call.run_id, call.tool, int(call.ok), call.latency_ms, call.error),
        )
        self._conn.commit()

    def create_hitl(self, req: HITLRequest) -> None:
        self._conn.execute(
            "INSERT INTO hitl_requests (hitl_id, run_id, action, payload, status,"
            " decided_by, decided_at, note)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                req.hitl_id,
                req.run_id,
                req.action,
                _dumps(req.payload),
                req.status,
                req.decided_by,
                req.decided_at,
                req.note,
            ),
        )
        self._conn.commit()

    def decide_hitl(
        self, hitl_id: str, *, status: str, decided_by: str, decided_at: str, note: str = ""
    ) -> bool:
        cur = self._conn.execute(
            "UPDATE hitl_requests SET status = ?, decided_by = ?, decided_at = ?, note = ?"
            " WHERE hitl_id = ? AND status = 'awaiting_user'",
            (status, decided_by, decided_at, note, hitl_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def pending_hitl(self) -> list[HITLRequest]:
        rows = self._conn.execute(
            "SELECT * FROM hitl_requests WHERE status = 'awaiting_user' ORDER BY hitl_id"
        ).fetchall()
        return [HITLRequest(**{**dict(r), "payload": _loads(r["payload"], {})}) for r in rows]

    def add_model_usage(self, usage: ModelUsage) -> None:
        self._conn.execute(
            "INSERT INTO model_usage"
            " (usage_id, run_id, provider, model, token_in, token_out, cost_usd, error, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                usage.usage_id,
                usage.run_id,
                usage.provider,
                usage.model,
                usage.token_in,
                usage.token_out,
                usage.cost_usd,
                usage.error,
                usage.ts,
            ),
        )
        self._conn.commit()

    def usage_summary(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(token_in),0) AS token_in,"
            " COALESCE(SUM(token_out),0) AS token_out,"
            " COALESCE(SUM(cost_usd),0) AS cost_usd FROM model_usage"
        ).fetchone()
        return dict(row)

    # ---------- counts（测试与健康检查用） ----------

    def counts(self) -> dict[str, int]:
        tables = (
            "cases",
            "claims",
            "evidence_spans",
            "extractions",
            "analysis_runs",
            "artifacts",
            "artifact_revisions",
            "user_commits",
            "monitors",
            "monitor_updates",
            "agent_runs",
            "hitl_requests",
        )
        return {t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
