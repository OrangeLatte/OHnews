"""Parent Research Agent（阶段 2 Agent OS）：Case 现状 → 研究计划。

规划是同步快操作（区别于 case_workflows 的后台线程协议）：读 Case 上下文
（文档/claims/已跑工作流）→ ModelRouter 结构化输出 PlanOut → 落库
agent_runs（workflow 列 'plan'，明细节存 context JSON，见
ResearchStore.add_plan_run）。诚实降级语义与 case_workflows 一致：
router 缺失或全部候选失败 → status=failed 落库并返回根因，永不虚构计划；
模型返回空 steps 视为诚实弃权（status=succeeded 且 steps=[]）。
"""

from __future__ import annotations

import uuid
from typing import Any

from oh_contracts.agent_runtime import WORKFLOWS, PlanOut
from oh_contracts.enums import Tier

PLAN_SYSTEM = f"""\
你是 OH!News 的 Parent Research Agent（研究操作系统总控）。
基于 Case 现状规划下一步研究步骤，规则：
- 输出 3-6 步，按执行顺序排列；每步的 kind 只能取以下闭集：
  {", ".join(WORKFLOWS)}。
- title 一句话说明做什么；rationale 说明为什么现在做、依据 Case 现状的
  哪一点（文档数/claims/已跑工作流的缺口）。
- 优先补齐证据链缺口：先拆解（DissectDocument）→ 语言对齐
  （NormalizeLanguage）→ 跨源比较（CompareSources）→ 报告（BuildReport）
  → 反证（ChallengeClaim）→ 提交（CommitArtifact）。
- 不把相关性当因果；无法确认的步骤不编造依据。
- 若 Case 不具备研究条件（无文档且无明确研究问题），返回空 steps
  （诚实弃权），绝不虚构可行步骤。
"""


def _default_now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat()


async def build_research_plan(
    case_id: str,
    *,
    research: Any,
    router: Any | None,
    question: str = "",
    now_fn: Any = None,
) -> dict[str, Any]:
    """生成并持久化一次研究计划；返回 {run_id, status, steps, error}。

    research 为 ResearchStore（读 Case 上下文 + 落 agent_runs）；
    router 为 ModelRouter 或 None（未配置模型）。case 不存在抛 KeyError
    （API 层转 404）。
    """
    case = research.get_case(case_id)
    if case is None:
        raise KeyError(f"case not found: {case_id}")
    now = str(now_fn()) if now_fn else _default_now()
    run_id = f"plan-{uuid.uuid4().hex[:12]}"
    eff_question = (question or "").strip() or case.question

    def _persist(status: str, *, steps: list[dict[str, Any]], model: str, error: str) -> None:
        research.add_plan_run(
            run_id,
            case_id=case_id,
            question=eff_question,
            steps=steps,
            model=model,
            created_at=now,
            status=status,
            error=error,
        )

    if router is None:
        error = "router not configured: 模型未配置，无法生成研究计划（诚实降级）"
        _persist("failed", steps=[], model="", error=error)
        return {"run_id": run_id, "status": "failed", "steps": [], "error": error}

    docs = research.case_documents(case_id)
    claims = research.claims_for_case(case_id)
    run_kinds = research.case_run_kinds(case_id)
    sources = sorted({str(d.get("source_id") or "") for d in docs} - {""})
    user = (
        "Case 现状：\n"
        f"- case_id: {case_id}\n"
        f"- 研究问题: {eff_question or '（未设置）'}\n"
        f"- 已挂载文档数: {len(docs)}（来源: {sources or '无'}）\n"
        f"- 已有 claims 数: {len(claims)}\n"
        f"- 已运行过的工作流 kind: {run_kinds or '无'}\n"
        f"- 用户补充问题: {(question or '').strip() or '（无）'}\n\n"
        "请输出研究计划（3-6 步；不具备研究条件时输出空 steps）。"
    )
    try:
        out, ref, _usage = await router.invoke(Tier.EXECUTE, PLAN_SYSTEM, user, PlanOut)
    except Exception as exc:  # noqa: BLE001 —— 根因落库，诚实降级不反噬端点
        error = f"plan llm failed: {exc}"
        _persist("failed", steps=[], model="", error=error)
        return {"run_id": run_id, "status": "failed", "steps": [], "error": error}
    model = f"{ref.provider}/{ref.model_id}" if ref is not None else ""
    steps = [s.model_dump(mode="json") for s in out.steps]
    _persist("succeeded", steps=steps, model=model, error="")
    return {"run_id": run_id, "status": "succeeded", "steps": steps, "error": ""}


__all__ = ["PLAN_SYSTEM", "build_research_plan"]
