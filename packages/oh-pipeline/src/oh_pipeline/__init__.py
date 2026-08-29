"""oh-pipeline：处理+统计层（蓝图 §5 图2 的 tagger_node + divergence_engine）。"""

from __future__ import annotations

from oh_pipeline.detect import (
    detect_attention_spikes,
    detect_expectation_gaps,
    detect_narrative_shifts,
    detect_ndi_alerts,
    detect_signals,
)
from oh_pipeline.divergence import (
    dirichlet_smooth,
    js_divergence,
    l1_gap,
    ndi_for_event,
    temperature_gap,
)
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry, EntitySpec
from oh_pipeline.rules import FRAME_KEYWORDS
from oh_pipeline.run import EventNDI, PipelineReport, run_pipeline
from oh_pipeline.spectra import sentence_spectrum, split_sentences
from oh_pipeline.tagger import RuleTagger
from oh_pipeline.validation import (
    ValidityResult,
    load_gold_ndi,
    measurement_validity,
    spearman_rho,
)

__all__ = [
    "DEFAULT_ENTITIES",
    "EventNDI",
    "FRAME_KEYWORDS",
    "EntityRegistry",
    "EntitySpec",
    "PipelineReport",
    "detect_attention_spikes",
    "detect_expectation_gaps",
    "detect_narrative_shifts",
    "detect_ndi_alerts",
    "detect_signals",
    "RuleTagger",
    "ValidityResult",
    "dirichlet_smooth",
    "js_divergence",
    "l1_gap",
    "load_gold_ndi",
    "measurement_validity",
    "ndi_for_event",
    "run_pipeline",
    "sentence_spectrum",
    "spearman_rho",
    "split_sentences",
    "temperature_gap",
]
