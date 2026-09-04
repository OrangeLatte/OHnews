"""专项 Agent 注册表（阶段 2 Agent OS：Parent + 9 专项）。

纪律：如实映射现有能力——endpoint 只指向已存在的 REST 端点，
workflow 只取 oh_contracts.agent_runtime.WORKFLOWS 闭集或 None（无直接
workflow），status 区分已有实现（active）与留待后续（planned）。
专项 Agent 不维护孤立聊天上下文，统一读写 ResearchState（research.sqlite）。
"""

from __future__ import annotations

from typing import Any

SPECIALISTS: tuple[dict[str, Any], ...] = (
    {
        "id": "observe_analyst",
        "title": "观察分析员 / Observe Analyst",
        "description": "解读 OBSERVE 变化信号、解释证据与缺口，并引导创建或进入 Case。",
        "workflow": None,
        "endpoint": "/api/changes/{change_id}",
        "status": "active",
    },
    {
        "id": "dissection",
        "title": "拆解专员 / Dissection Agent",
        "description": "对文档执行 18 元素拆解，产出可回溯原文位置的元素提取。",
        "workflow": "DissectDocument",
        "endpoint": "/api/cases/{case_id}/dissect",
        "status": "active",
    },
    {
        "id": "translation_alignment",
        "title": "翻译对齐专员 / Translation & Alignment Agent",
        "description": "生成英文对齐副本并维护术语映射，供跨语言比较使用。",
        "workflow": "NormalizeLanguage",
        "endpoint": "/api/cases/{case_id}/translate",
        "status": "active",
    },
    {
        "id": "cross_source_analyst",
        "title": "跨信源分析员 / Cross-source Analyst",
        "description": "对多版本执行六节交叉比较，识别事实共识、冲突与口径差异。",
        "workflow": "CompareSources",
        "endpoint": "/api/cases/{case_id}/compare",
        "status": "active",
    },
    {
        "id": "report",
        "title": "报告专员 / Report Agent",
        "description": "基于 Case 证据生成七类专业报告草稿，提交前须经 Challenge 与用户确认。",
        "workflow": "BuildReport",
        "endpoint": "/api/cases/{case_id}/report",
        "status": "active",
    },
    {
        "id": "challenge",
        "title": "反证专员 / Challenge Agent",
        "description": "对主张做主动反证质询，核对独立信源与反驳向证据。",
        "workflow": "ChallengeClaim",
        "endpoint": "/api/cases/{case_id}/challenge",
        "status": "active",
    },
    {
        "id": "source_expansion",
        "title": "信源扩展专员 / Source Expansion Agent",
        "description": "AI 扩展与评估新信源并起草采集计划；现有手动计划管理，AI 扩展待实现。",
        "workflow": None,
        "endpoint": "/api/collection/plans",
        "status": "planned",
    },
    {
        "id": "monitor",
        "title": "监测专员 / Monitor Agent",
        "description": "创建实体/主题/立场/情绪/动作监测器并管理增量更新复核。",
        "workflow": "CreateMonitor",
        "endpoint": "/api/monitors",
        "status": "active",
    },
    {
        "id": "archive_editor",
        "title": "档案编者 / Archive Editor",
        "description": "管理已确认产物入档与 Press Edition 编排，发布为不可变版本。",
        "workflow": "ComposePressEdition",
        "endpoint": "/api/press-editions",
        "status": "active",
    },
)

SPECIALIST_STATUSES: tuple[str, ...] = ("active", "planned")


def specialist_ids() -> tuple[str, ...]:
    """按注册顺序返回全部专项 Agent id。"""
    return tuple(str(s["id"]) for s in SPECIALISTS)


__all__ = ["SPECIALISTS", "SPECIALIST_STATUSES", "specialist_ids"]
