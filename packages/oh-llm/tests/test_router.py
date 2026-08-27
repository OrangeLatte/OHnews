"""ModelRouter：候选链顺序 / fallback 触发 / 校验失败降级 / yaml 解析。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from oh_contracts.enums import Tier
from oh_llm.config import LLMConfig, ModelRef, ProviderSpec, load_llm_config
from oh_llm.router import CandidateUnavailable, ModelRouter
from pydantic import BaseModel

ROOT = Path(__file__).parents[3]


class Out(BaseModel):
    value: int


def _cfg() -> LLMConfig:
    return LLMConfig(
        providers={
            "deepseek": ProviderSpec("deepseek", None, "DEEPSEEK_API_KEY", ("m1",)),
            "zhipu": ProviderSpec("zhipu", None, "ZHIPU_API_KEY", ("m2", "m3")),
        },
        routing={
            Tier.IO: [ModelRef("deepseek", "m1"), ModelRef("zhipu", "m2")],
            Tier.EXECUTE: [ModelRef("zhipu", "m2")],
        },
    )


class RecordingRouter(ModelRouter):
    """override _invoke_candidate：按脚本表返回/抛错，记录调用顺序。"""

    def __init__(self, config, script: dict[str, list]):
        super().__init__(config)
        self.script = script
        self.calls: list[str] = []

    async def _invoke_candidate(self, ref, schema, system, user):
        key = f"{ref.provider}/{ref.model_id}"
        self.calls.append(key)
        action = self.script[key].pop(0)
        if isinstance(action, Exception):
            raise action
        if isinstance(action, dict):
            return schema.model_validate(action)
        return action


def test_validation_failure_falls_back() -> None:
    async def case():
        router = RecordingRouter(
            _cfg(),
            script={
                "deepseek/m1": [{"wrong_field": 1}],  # 校验失败 → 下一候选
                "zhipu/m2": [{"value": 2}],
            },
        )
        result, ref = await router.invoke(Tier.IO, "s", "u", Out)
        assert result.value == 2
        assert ref.model_id == "m2"
        assert router.calls == ["deepseek/m1", "zhipu/m2"]

    asyncio.run(case())


def test_unavailable_candidate_skipped() -> None:
    async def case():
        router = RecordingRouter(
            _cfg(),
            script={
                "deepseek/m1": [CandidateUnavailable("no key")],
                "zhipu/m2": [{"value": 3}, {"value": 3}],
            },
        )
        result, ref = await router.invoke(Tier.IO, "s", "u", Out)
        assert result.value == 3
        assert router.calls == ["deepseek/m1", "zhipu/m2"]
        # 第二次调用：m1 动作耗尽抛错被吞（FakeRouter 不走 _ensure 标记），
        # fallback 继续命中 m2
        await router.invoke(Tier.IO, "s", "u", Out)
        assert router.calls == [
            "deepseek/m1",
            "zhipu/m2",
            "deepseek/m1",
            "zhipu/m2",
        ]

    asyncio.run(case())


def test_ensure_marks_unavailable(monkeypatch) -> None:
    """_ensure 语义：密钥缺失 → CandidateUnavailable 且候选被永久标记。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    router = ModelRouter(_cfg())
    ref = ModelRef("deepseek", "m1")
    with pytest.raises(CandidateUnavailable):
        router._ensure(ref)
    with pytest.raises(CandidateUnavailable, match="已标记"):
        router._ensure(ref)


def test_all_candidates_fail_raises_with_causes() -> None:
    async def case():
        router = RecordingRouter(
            _cfg(),
            script={
                "deepseek/m1": [CandidateUnavailable("no key")],
                "zhipu/m2": [TimeoutError("t/o")],
            },
        )
        with pytest.raises(RuntimeError, match="全部候选失败") as excinfo:
            await router.invoke(Tier.IO, "s", "u", Out)
        assert "no key" in str(excinfo.value) and "t/o" in str(excinfo.value)

    asyncio.run(case())


def test_no_fallback_chain_exhausts_single() -> None:
    async def case():
        router = RecordingRouter(_cfg(), script={"zhipu/m2": [ValueError("bad")]})
        with pytest.raises(RuntimeError):
            await router.invoke(Tier.EXECUTE, "s", "u", Out)

    asyncio.run(case())


def test_load_models_yaml_from_repo() -> None:
    cfg = load_llm_config(ROOT / "config" / "models.yaml")
    assert cfg.strategy == "function_calling"
    assert [r.model_id for r in cfg.chain(Tier.IO)] == ["deepseek-v4-flash", "glm-5.3-flash"]
    assert cfg.chain(Tier.STRATEGIC)[0] == ModelRef("zhipu", "glm-5.3")


def test_load_yaml_rejects_unknown_provider(tmp_path: Path) -> None:
    bad = tmp_path / "m.yaml"
    bad.write_text(
        "providers:\n  a: {api_key_env: K}\nrouting:\n  io: {primary: ghost/x}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ghost"):
        load_llm_config(bad)


def test_model_ref_parse() -> None:
    assert ModelRef.parse("zhipu/glm-5.3") == ModelRef("zhipu", "glm-5.3")
    with pytest.raises(ValueError):
        ModelRef.parse("no-slash")
