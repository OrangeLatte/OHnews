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
import time
import weakref
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from oh_contracts.enums import Tier
from pydantic import BaseModel

from oh_llm.config import LLMConfig, ModelRef, Usage

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
        # 并发上限按 event loop 隔离：asyncio.Semaphore 跨循环共享会因 waiters 的
        # Future 绑死创建时循环而永久挂起（后台线程 asyncio.run 各建新循环）。
        # WeakKeyDictionary 以 loop 对象为键，循环销毁后条目自动回收，无 id 复用风险。
        self._max_concurrency = max(1, config.max_concurrency)
        self._sem_loops: weakref.WeakKeyDictionary[Any, asyncio.Semaphore] = (
            weakref.WeakKeyDictionary()
        )
        # 最近一次成功调用的用量（invoke 返回值之外的可观察性旁路）
        self._last_usage: Usage | None = None

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
    ) -> tuple[T, Usage | None]:
        """单候选调用（策略分派：function_calling / json_mode；测试可 override）。"""
        t0 = time.monotonic()
        provider_strategy = self._config.provider_of(ref).strategy or self._config.strategy
        if provider_strategy == "json_mode":
            raw, parsed = await self._invoke_json_mode(ref, schema, system, user)
        else:
            llm = self._ensure(ref)
            bound = llm.with_structured_output(schema, method=self._config.strategy)  # type: ignore[attr-defined]
            raw = await bound.ainvoke([SystemMessage(system), HumanMessage(user)])
            if raw is None:
                # 模型未触发 tool call（短 schema 常见）→ 明确根因，走退避重试/下一候选
                raise RuntimeError(
                    f"{ref.provider}/{ref.model_id}: structured output 为 None（模型未调用工具）"
                )
            parsed = schema.model_validate(raw)
        return parsed, self._extract_usage(raw, ref, t0)

    def _extract_usage(self, raw: Any, ref: ModelRef, t0: float) -> Usage | None:
        """从 langchain AIMessage 提取 token 用量（usage_metadata 优先，兼容 token_usage）。"""
        meta = getattr(raw, "usage_metadata", None) or {}
        prompt_t = meta.get("input_tokens")
        completion_t = meta.get("output_tokens")
        total_t = meta.get("total_tokens")
        if prompt_t is None:
            tu = (getattr(raw, "response_metadata", None) or {}).get("token_usage") or {}
            prompt_t = tu.get("prompt_tokens")
            completion_t = tu.get("completion_tokens")
            total_t = tu.get("total_tokens")
        if prompt_t is None and total_t is None:
            return None
        return Usage(
            model=ref.model_id,
            provider=ref.provider,
            prompt_tokens=int(prompt_t or 0),
            completion_tokens=int(completion_t or 0),
            total_tokens=int(total_t or 0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def _invoke_json_mode(
        self,
        ref: ModelRef,
        schema: type[T],
        system: str,
        user: str,
    ) -> tuple[Any, T]:
        """json_mode：schema 注入 prompt + 纯文本输出后校验。

        实测弃用两条路径：function_calling 在 zhipu glm-5.3-flash 上
        长输出会挂起（>300s 无响应）；langchain bind(response_format)
        对 zhipu 会触发服务端连接重置（Connection error，裸调用同 payload
        正常）。prompt-only JSON + 围栏剥离实测 35s 稳定可靠。
        返回 (raw_message, parsed) 以便上层提取 usage。
        """
        import json

        llm = self._ensure(ref)
        schema_desc = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        sys2 = (
            f"{system}\n\n输出要求：仅输出一个 JSON 对象（无代码围栏/无解释文字），"
            f"必须符合以下 JSON Schema：\n{schema_desc}"
        )
        raw = await llm.ainvoke([SystemMessage(sys2), HumanMessage(user)])
        content = raw.content
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        return raw, schema.model_validate_json(text)

    def _loop_sem(self) -> asyncio.Semaphore:
        """取当前 event loop 的并发信号量（无则建，弱引用持）。"""
        loop = asyncio.get_running_loop()
        sem = self._sem_loops.get(loop)
        if sem is None:
            sem = asyncio.Semaphore(self._max_concurrency)
            self._sem_loops[loop] = sem
        return sem

    async def _invoke_with_limit(
        self,
        ref: ModelRef,
        schema: type[T],
        system: str,
        user: str,
    ) -> tuple[T, Usage | None]:
        """限流护栏：per-loop asyncio.Semaphore 控制在途调用峰值。

        必须按 event loop 隔离而非跨循环共享：本 Router 实例在 serve 中
        长驻，而调用方（异步协议后台线程）各自 asyncio.run 新建事件循环，
        共享 asyncio.Semaphore 的 waiters Future 绑定创建时循环，跨循环
        release 无法唤醒 → acquire 永久挂起（TimeoutError 根因）。同步
        threading 锁则会在协程持锁 await 让出时阻塞整个循环（死锁）。
        """
        async with self._loop_sem():
            return await self._invoke_candidate(ref, schema, system, user)

    async def invoke(
        self,
        tier: Tier,
        system: str,
        user: str,
        schema: type[T],
    ) -> tuple[T, ModelRef, Usage | None]:
        """按 tier 候选链调用，返回（校验后的对象，实际使用的候选，用量记录）。

        失败语义：候选不可用 / 超时 / 限流 / 解析或校验失败 → 退避重试
        retry_attempts 次（仅最后一次记入根因），仍失败 → 下一候选；
        全部候选失败 → RuntimeError（根因链）。
        """
        errors: list[str] = []
        for ref in self._config.chain(tier):
            last: Exception | None = None
            for attempt in range(1 + self._config.retry_attempts):
                try:
                    result, usage = await self._invoke_with_limit(ref, schema, system, user)
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
                self._last_usage = usage
                return result, ref, usage
            if last is not None:
                errors.append(f"{ref.provider}/{ref.model_id}: {last}")
        chain_desc = " -> ".join(f"{r.provider}/{r.model_id}" for r in self._config.chain(tier))
        raise RuntimeError(f"tier={tier} 全部候选失败 [{chain_desc}]；根因: {errors}")

    def chain(self, tier: Tier) -> Sequence[ModelRef]:
        return self._config.chain(tier)

    async def raw_complete(self, tier: Tier, system: str, user: str) -> tuple[str, ModelRef]:
        """裸文本调用（健康检查等轻量场景），不走结构化输出/工具。

        取链上第一个可用候选，单次调用不重试；候选不可用则顺延，
        全部不可用抛 RuntimeError。
        """
        last: Exception | None = None
        for ref in self._config.chain(tier):
            try:
                llm = self._ensure(ref)
            except CandidateUnavailable as exc:
                last = exc
                continue
            try:
                raw = await llm.ainvoke([SystemMessage(system), HumanMessage(user)])
            except Exception as exc:  # noqa: BLE001 —— 顺延下一候选
                last = exc
                continue
            content = raw.content
            text = content if isinstance(content, str) else str(content)
            return text.strip(), ref
        chain_desc = " -> ".join(f"{r.provider}/{r.model_id}" for r in self._config.chain(tier))
        raise RuntimeError(f"tier={tier} 裸调用全部候选失败 [{chain_desc}]；根因: {last}")
