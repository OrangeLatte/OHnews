"""全局枚举（StrEnum：序列化为字符串，与 sqlite/parquet/yaml 存储值一致）。"""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    """模型调度三级（裁决 E：任意供应商模型可换入任意层级，此为默认路由）。"""

    IO = "io"
    EXECUTE = "execute"
    STRATEGIC = "strategic"


class SOStrategy(StrEnum):
    """结构化输出策略（native→function_calling→json_mode 逐级降级）。"""

    NATIVE = "native"
    FUNCTION_CALLING = "function_calling"
    JSON_MODE = "json_mode"


class SourceTier(StrEnum):
    """信源层级（L1 官方 / L2 通讯社 / L3 财经媒体 / L4 社媒）。"""

    OFFICIAL = "L1"
    WIRE = "L2"
    FINANCIAL_PRESS = "L3"
    SOCIAL = "L4"


class ArticleType(StrEnum):
    """文章类型（裁决 H：TypeFactor 快讯 1.0 / 分析稿 0.7 / 评论 0.4）。"""

    WIRE = "wire"
    ANALYSIS = "analysis"
    OPINION = "opinion"


class ClaimKind(StrEnum):
    """claim 类型（裁决 H：仅事实性 claim 计算真实性 T；观点性产 FramingScore）。"""

    FACTUAL = "factual"
    OPINION = "opinion"


class FrameLabel(StrEnum):
    """五框架 + other（裁决 B：需 codebook+gold set α>0.7 通过后数字方可对外）。"""

    LOSS = "loss"
    GAIN = "gain"
    RESPONSIBILITY = "responsibility"
    CONFLICT = "conflict"
    HUMAN_INTEREST = "human_interest"
    OTHER = "other"


class StanceLabel(StrEnum):
    """立场标签（含弃权语义：低价值+低置信 → ABSTAIN，不进分布计算）。"""

    SUPPORTIVE = "supportive"
    NEUTRAL = "neutral"
    CRITICAL = "critical"
    ABSTAIN = "abstain"


class ExtractionEngine(StrEnum):
    """分层路由引擎（规则 85% → 小模型 10% → LLM 5%；calibrated confidence 双轴）。"""

    RULE = "rule"
    SMALL_MODEL = "small_model"
    LLM = "llm"


class EpistemicStatus(StrEnum):
    """认知状态标注（narrative_card 必带，诚实披露推断性质）。"""

    MEASURED = "measured"
    INFERRED = "inferred"
    SPECULATIVE = "speculative"


class SSEEvent(StrEnum):
    """SSE 事件类型（SSEMessage.event 合法取值，Last-Event-ID 重连语义）。"""

    NODE_UPDATE = "node_update"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    INTERRUPT = "interrupt"
    ERROR = "error"
    DONE = "done"
