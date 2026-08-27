"""oh-llm：Provider 层 + 三级模型路由 + 标注委员会（裁决 B/E）。"""

from __future__ import annotations

from oh_llm.committee import (
    CODEBOOK_PROMPT,
    AnnotationCommittee,
    AnnotationResult,
    FrameDist,
    jsd_dist,
    krippendorff_alpha_nominal,
    normalize_dist,
)
from oh_llm.config import LLMConfig, ModelRef, ProviderSpec, load_llm_config
from oh_llm.router import CandidateUnavailable, ModelRouter

__all__ = [
    "CODEBOOK_PROMPT",
    "AnnotationCommittee",
    "AnnotationResult",
    "CandidateUnavailable",
    "FrameDist",
    "LLMConfig",
    "ModelRef",
    "ModelRouter",
    "ProviderSpec",
    "jsd_dist",
    "krippendorff_alpha_nominal",
    "load_llm_config",
    "normalize_dist",
]
