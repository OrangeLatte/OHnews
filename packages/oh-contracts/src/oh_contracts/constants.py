"""全局常量（与 docs/BLUEPRINT.md §8 统计层公式 / §6 裁决 H 数值一一对应）。"""

from __future__ import annotations

# --- 统计层（§8） -----------------------------------------------------------
#: 最小样本门：任一信源簇样本数低于此值 → NDI 输出弃权（NA），不放噪声
N_MIN_SAMPLES: int = 10
#: Dirichlet/Jeffreys 先验平滑系数 α
JEFFREYS_ALPHA: float = 0.5
#: percentile bootstrap 重采样次数（NDI 置信区间）
BOOTSTRAP_RESAMPLES: int = 1000
#: PSI 漂移告警阈值（>0.1 告警）
PSI_ALERT_THRESHOLD: float = 0.1

# --- PIT 纪律（§1/§5） ------------------------------------------------------
#: 一切指标只使用 t-1 及更早信息
PIT_LOOKBACK_DAYS: int = 1

# --- 可信度两级模型（裁决 H） ----------------------------------------------
#: TypeFactor：快讯 1.0 / 分析稿 0.7 / 评论专栏 0.4（键 = ArticleType.value）
TYPE_FACTOR: dict[str, float] = {"wire": 1.0, "analysis": 0.7, "opinion": 0.4}
#: Verify 修正：多源交叉一致 +0.2
VERIFY_BONUS_CORROBORATED: float = 0.2
#: Verify 修正：单一信源 -0.3
VERIFY_PENALTY_SINGLE: float = -0.3
#: Verify 修正：无独立佐证 -0.5
VERIFY_PENALTY_UNVERIFIED: float = -0.5

# --- 分层路由（§5 裁决 E + 数据科学家提案） ---------------------------------
#: calibrated confidence >= 0.9 → 规则层直接采信
CONF_TAU_RULE: float = 0.9
#: calibrated confidence >= 0.5 → 小模型；低于 0.5 且高价值 → LLM，否则弃权
CONF_TAU_SMALL: float = 0.5
