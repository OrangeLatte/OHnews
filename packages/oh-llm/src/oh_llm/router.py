"""三级模型路由（裁决 E：fallback 契约 = 输出 schema 而非策略）。

不变量：
- Router 按 tier 顺序尝试每个 (provider, model)，每次传入同一 Pydantic model；
- 策略统一 function_calling（native 兼容性最参差，默认不用）；
- 输出必须经 schema.model_validate 后校验——校验失败等同候选失败，触发下一候选；
- 密钥缺失 / 构造失败 = 候选不可用（跳过不报错，全部失败才 raise）。
"""

from __future__ import annotations

import asyncio
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
    """结构化输出路由器：tier → 候选链 → 后校验对象。

    并发护栏：全局 Semaphore 限制在途调用（Send 并行多事件共用同一
    Router 实例时不打爆 provider）；候选级应用重试（限流/超时退避）。
    """

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
        self._sem = asyncio.Semaphore(max(1, config.max_concurrency))

    def _default_factory(self, ref: ModelRef) -> ChatOpenAI:
        """OpenAI 兼容协议构造（覆盖 deepseek/zhipu/openrouter/ollama/custom）。"""
        spec = self._config.provider_of(ref)
        api_key = os.environ.get(spec.api_key_env) if spec.api_key_env else None
        return ChatOpenAI(
            model=ref.model_id,
            base_url=spec.base_url,
            api_key=api_key,
            temperature=0,
            timeout=self._config.timeout_s,
            max_retries=self._config.max_retries,
            extra_body=spec.extra_body,
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
        """单候选调用（策略分派：function_calling / json_mode；测试可 override）。"""
        provider_strategy = self._config.provider_of(ref).strategy or self._config.strategy
        if provider_strategy == "json_mode":
            return await self._invoke_json_mode(ref, schema, system, user)
        llm = self._ensure(ref)
        bound = llm.with_structured_output(schema, method=self._config.strategy)  # type: ignore[attr-defined]
        raw = await bound.ainvoke([SystemMessage(system), HumanMessage(user)])
        return schema.model_validate(raw)

    async def _invoke_json_mode(
        self,
        ref: ModelRef,
        schema: type[T],
        system: str,
        user: str,
    ) -> T:
        """json_mode：response_format=json_object + schema 注入 prompt，文本输出后校验。

        无工具调用协议 → 不存在"模型把 schema 当真工具乱起 name"的混淆
        （DeepSeek V4 function_calling 实测 OutputParserException 根因）。
        """
        import json

        llm = self._ensure(ref)
        schema_desc = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys2 = (
            f"{system}\n\n输出要求：仅输出一个 JSON 对象（无代码围栏/无解释文字），"
            f"必须符合以下 JSON Schema：\n{schema_desc}"
        )
        bound = llm.bind(response_format={"type": "json_object"})
        raw = await bound.ainvoke([SystemMessage(sys2), HumanMessage(user)])
        content = raw.content
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        return schema.model_validate_json(text)

    async def _invoke_with_limit(
        self,
        ref: ModelRef,
        schema: type[T],
        system: str,
        user: str,
    ) -> T:
        """限流包装：全局 Semaphore 控制在途调用峰值。"""
        async with self._sem:
            return await self._invoke_candidate(ref, schema, system, user)

    async def invoke(
        self,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
    ) -> tuple[T, ModelRef]:
        """按 tier 候选链调用，返回（校验后的对象，实际使用的候选）。

        失败语义：候选不可用 / 超时 / 限流 / 解析或校验失败 → 退避重试
        retry_attempts 次（仅最后一次记入根因），仍失败 → 下一候选；
        全部候选失败 → RuntimeError（根因链）。
        """
        errors: list[str] = []
        for ref in self._config.chain(tier):
            last: Exception | None = None
            for attempt in range(1 + self._config.retry_attempts):
                try:
                    result = await self._invoke_with_limit(ref, schema, system, user)
                except CandidateUnavailable as exc:
                    # 不可用候选（密钥缺失/永久标记）不重试，直接下一候选
                    errors.append(f"{ref.provider}/{ref.model_id}: {exc}")
                    last = None
                    break
                except Exception as exc:  # noqa: BLE001 —— 任何失败都退避重试
                    last = exc
                    if attempt < self._config.retry_attempts:
                        await asyncio.sleep(self._config.retry_delay_s * (attempt + 1))
                    continue
                return result, ref
            if last is not None:
                errors.append(f"{ref.provider}/{ref.model_id}: {last}")
        chain_desc = " -> ".join(f"{r.provider}/{r.model_id}" for r in self._config.chain(tier))
        raise RuntimeError(f"tier={tier} 全部候选失败 [{chain_desc}]；根因: {errors}")

    def chain(self, tier: Tier) -> Sequence[ModelRef]:
        return self._config.chain(tier)
