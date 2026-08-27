"""三级模型路由（裁决 E：fallback 契约 = 输出 schema 而非策略）。

不变量：
- Router 按 tier 顺序尝试每个 (provider, model)，每次传入同一 Pydantic model；
- 策略统一 function_calling（native 兼容性最参差，默认不用）；
- 输出必须经 schema.model_validate 后校验——校验失败等同候选失败，触发下一候选；
- 密钥缺失 / 构造失败 = 候选不可用（跳过不报错，全部失败才 raise）。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from oh_contracts.enums import Tier
from pydantic import BaseModel

from oh_llm.config import LLMConfig, ModelRef

T = TypeVar("T", bound=BaseModel)


class CandidateUnavailable(RuntimeError):
    """候选模型不可用（密钥缺失/构造失败），跳过并尝试下一候选。"""


class ModelRouter:
    """结构化输出路由器：tier → 候选链 → 后校验对象。"""

    def __init__(
        self,
        config: LLMConfig,
        *,
        model_factory: Callable[[ModelRef], object] | None = None,
    ) -> None:
        self._config = config
        self._factory = model_factory or self._default_factory
        self._models: dict[ModelRef, object] = {}
        self._unavailable: set[ModelRef] = set()

    def _default_factory(self, ref: ModelRef) -> ChatOpenAI:
        """OpenAI 兼容协议构造（覆盖 deepseek/zhipu/openrouter/ollama/custom）。"""
        spec = self._config.provider_of(ref)
        api_key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
        return ChatOpenAI(
            model=ref.model_id,
            base_url=spec.base_url,
            api_key=api_key,
            temperature=0,
            timeout=60,
            max_retries=1,
        )

    def _ensure(self, ref: ModelRef):
        if ref in self._unavailable:
            raise CandidateUnavailable(f"{ref.provider}/{ref.model_id} 已标记不可用")
        if ref not in self._models:
            spec = self._config.provider_of(ref)
            api_key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
            if spec.api_key_env and not api_key:
                self._unavailable.add(ref)
                raise CandidateUnavailable(
                    f"环境变量 {spec.api_key_env} 未设置（provider={ref.provider}）"
                )
            self._models[ref] = self._factory(ref)
        return self._models[ref]

    async def _invoke_candidate(
        self,
        ref: ModelRef,
        schema: type[T],
        system: str,
        user: str,
    ) -> T:
        """单候选调用（langchain 结构化输出）。测试可 override。"""
        llm = self._ensure(ref)
        bound = llm.with_structured_output(schema, method=self._config.strategy)  # type: ignore[attr-defined]
        raw = await bound.ainvoke([SystemMessage(system), HumanMessage(user)])
        return schema.model_validate(raw)

    async def invoke(
        self,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
    ) -> tuple[T, ModelRef]:
        """按 tier 候选链调用，返回（校验后的对象，实际使用的候选）。

        失败语义：候选不可用 / 超时 / 限流 / 解析或校验失败 → 下一候选；
        全部失败 → RuntimeError（根因链）。
        """
        errors: list[str] = []
        for ref in self._config.chain(tier):
            try:
                result = await self._invoke_candidate(ref, schema, system, user)
            except Exception as exc:  # noqa: BLE001 —— 任何失败都降级下一候选
                errors.append(f"{ref.provider}/{ref.model_id}: {exc}")
                continue
            return result, ref
        chain_desc = " -> ".join(f"{r.provider}/{r.model_id}" for r in self._config.chain(tier))
        raise RuntimeError(f"tier={tier} 全部候选失败 [{chain_desc}]；根因: {errors}")

    def chain(self, tier: Tier) -> Sequence[ModelRef]:
        return self._config.chain(tier)
