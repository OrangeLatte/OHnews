"""POST /api/agent/plan + GET /api/agent/plans（Parent 规划）测试。

覆盖：404 / 无模型诚实降级（failed 落库 + 根因）/ FakeRouter 成功路径
（202 + steps 闭集校验 + 落库可查）/ LLM 全候选失败降级。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app
from oh_contracts.agent_runtime import WORKFLOWS, PlanOut, PlanStep
from oh_llm.config import ModelRef
from oh_llm.router import ModelRouter


def make_now() -> datetime:
    return datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


MODELS_YAML = """\
defaults:
  strategy: json_mode
  max_retries: 0
  timeout_s: 10
  max_concurrency: 1
  retry_attempts: 0
  retry_delay_s: 0.1
providers:
  zhipu:
    base_url: https://example.invalid/v1
    api_key_env: ZHIPU_API_KEY
    strategy: json_mode
    models:
      glm-5.3-flash:
        context_window: 128000
routing:
  execute:
    primary: zhipu/glm-5.3-flash
    fallback: []
"""

CASE = {
    "case_id": "case-t1",
    "question": "美联储九月会暂停加息吗？",
    "origin": "observe",
    "created_at": "2026-09-04T12:00:00+00:00",
    "updated_at": "2026-09-04T12:00:00+00:00",
}


@pytest.fixture()
def app_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Path, pytest.MonkeyPatch]:
    """TestClient + 数据目录 + models.yaml 已就位（keys 环境变量由测试自控）。"""
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("version: 2\nsources: []\n", encoding="utf-8")
    models_yaml = tmp_path / "models.yaml"
    models_yaml.write_text(MODELS_YAML, encoding="utf-8")
    app = create_app(
        AppPaths(
            root=tmp_path,
            sources_yaml=sources_yaml,
            models_yaml=models_yaml,
            now_fn=make_now,
        )
    )
    return TestClient(app), tmp_path, monkeypatch


def _create_case(client: TestClient) -> None:
    r = client.post("/api/cases", json=CASE)
    assert r.status_code == 200


def test_plan_requires_existing_case(app_env: tuple[Any, ...]) -> None:
    client, _root, _mp = app_env
    r = client.post("/api/agent/plan", json={"case_id": "case-nope"})
    assert r.status_code == 404


def test_plan_honest_degradation_without_llm(app_env: tuple[Any, ...]) -> None:
    """无 keys → router None → status=failed 落库 + 根因非空（诚实降级）。"""
    client, _root, _mp = app_env
    _create_case(client)
    r = client.post("/api/agent/plan", json={"case_id": "case-t1"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "failed"
    assert body["steps"] == []
    assert body["error"]
    assert body["run_id"].startswith("plan-")

    plans = client.get("/api/agent/plans", params={"case_id": "case-t1"}).json()
    assert plans["n"] == 1
    row = plans["plans"][0]
    assert row["run_id"] == body["run_id"]
    assert row["status"] == "failed"
    assert row["case_id"] == "case-t1"
    assert row["question"] == CASE["question"]
    assert row["steps"] == []
    assert row["error"]


def test_plan_success_with_fake_router(app_env: tuple[Any, ...]) -> None:
    """FakeRouter 返回固定 PlanOut → succeeded + steps 落库可查。"""
    client, _root, mp = app_env
    mp.setenv("ZHIPU_API_KEY", "test-key")

    async def fake_invoke(self: Any, tier: Any, system: str, user: str, schema: type) -> tuple:
        assert schema is PlanOut
        assert "Parent Research Agent" in system
        assert "case-t1" in user
        out = PlanOut(
            steps=[
                PlanStep(
                    step_id="s1",
                    kind="DissectDocument",
                    title="拆解已挂载文档",
                    rationale="证据链起点：0 份元素提取",
                ),
                PlanStep(
                    step_id="s2",
                    kind="CompareSources",
                    title="跨源比较",
                    rationale="文档 ≥2 后核对口径差异",
                ),
            ]
        )
        return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None

    mp.setattr(ModelRouter, "invoke", fake_invoke)
    _create_case(client)
    r = client.post(
        "/api/agent/plan",
        json={"case_id": "case-t1", "question": "是否暂停加息？"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["error"] == ""
    assert [s["kind"] for s in body["steps"]] == ["DissectDocument", "CompareSources"]
    assert all(s["kind"] in WORKFLOWS for s in body["steps"])

    plans = client.get("/api/agent/plans", params={"case_id": "case-t1"}).json()
    assert plans["n"] == 1
    row = plans["plans"][0]
    assert row["run_id"] == body["run_id"]
    assert row["status"] == "succeeded"
    assert row["question"] == "是否暂停加息？"
    assert len(row["steps"]) == 2
    assert row["model"] == "zhipu/glm-5.3-flash"
    # workflow='plan' 行不得破坏 GET /api/agent/runs 的 AgentRun 契约转换
    assert client.get("/api/agent/runs").json() == []


def test_plan_llm_failure_lands_failed_run(app_env: tuple[Any, ...]) -> None:
    """LLM 全候选失败 → status=failed + 根因（诚实降级语义）。"""
    client, _root, mp = app_env
    mp.setenv("ZHIPU_API_KEY", "test-key")

    async def boom(self: Any, tier: Any, system: str, user: str, schema: type) -> tuple:
        raise RuntimeError("all candidates failed")

    mp.setattr(ModelRouter, "invoke", boom)
    _create_case(client)
    r = client.post("/api/agent/plan", json={"case_id": "case-t1"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "failed"
    assert "all candidates failed" in body["error"]
    plans = client.get("/api/agent/plans", params={"case_id": "case-t1"}).json()
    assert plans["n"] == 1 and plans["plans"][0]["status"] == "failed"


def test_plan_invalid_kind_rejected_by_schema(app_env: tuple[Any, ...]) -> None:
    """LLM 输出越界 kind → PlanOut 校验失败 → failed 落库（闭集纪律）。"""
    client, _root, mp = app_env
    mp.setenv("ZHIPU_API_KEY", "test-key")

    async def bad_invoke(self: Any, tier: Any, system: str, user: str, schema: type) -> tuple:
        raise RuntimeError("1 validation error for PlanOut\nkind: 必须属于 WORKFLOWS 闭集")

    mp.setattr(ModelRouter, "invoke", bad_invoke)
    _create_case(client)
    body = client.post("/api/agent/plan", json={"case_id": "case-t1"}).json()
    assert body["status"] == "failed" and "WORKFLOWS" in body["error"]
