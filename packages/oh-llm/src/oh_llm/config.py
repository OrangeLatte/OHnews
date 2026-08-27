"""Provider 配置加载（裁决 E：自研元数据+路由，OpenRouter 降级为普通 OpenAI 兼容端点）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from oh_contracts.enums import Tier


@dataclass(frozen=True)
class ModelRef:
    """provider/model_id 复合引用（models.yaml routing 的 primary/fallback 项）。"""

    provider: str
    model_id: str

    @classmethod
    def parse(cls, s: str) -> ModelRef:
        provider, _, model_id = s.partition("/")
        if not provider or not model_id:
            raise ValueError(f"模型引用必须为 provider/model_id 形式，得到: {s!r}")
        return cls(provider, model_id)


@dataclass(frozen=True)
class ProviderSpec:
    """供应商：OpenAI 兼容 base_url + 密钥环境变量 + 模型清单 + extra_body。"""

    name: str
    base_url: str | None
    api_key_env: str | None
    models: tuple[str, ...]
    # 透传 ChatOpenAI extra_body（如 DeepSeek V4 需 {"thinking": {"type": "disabled"}}
    # 关闭思考模式，否则不支持强制 tool_choice 的 function_calling）
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMConfig:
    """全局模型配置：供应商注册表 + 三级路由链（顺序即优先级）+ 运行时护栏。

    并发安全（Send 并行多事件同时打同一 provider 的教训）：
    - max_concurrency：Router 全局信号量，限制同时在途的 LLM 调用数；
    - timeout_s / max_retries：透传 ChatOpenAI（连接级）；
    - retry_attempts / retry_delay_s：应用级重试（限流/超时退避），
      每候选最多尝试 1 + retry_attempts 次，全部失败才降级下一候选。
    """

    providers: dict[str, ProviderSpec]
    routing: dict[Tier, list[ModelRef]]
    strategy: str = "function_calling"
    timeout_s: int = 60
    max_retries: int = 1
    max_concurrency: int = 4
    retry_attempts: int = 2
    retry_delay_s: float = 1.0

    def chain(self, tier: Tier) -> list[ModelRef]:
        return self.routing.get(tier, [])

    def provider_of(self, ref: ModelRef) -> ProviderSpec:
        return self.providers[ref.provider]


def load_llm_config(path: str | Path) -> LLMConfig:
    """解析 config/models.yaml（结构见该文件头注释）。"""
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    providers = {
        name: ProviderSpec(
            name=name,
            base_url=spec.get("base_url"),
            api_key_env=spec.get("api_key_env"),
            models=tuple(spec.get("models", {})),
            extra_body=spec.get("extra_body"),
        )
        for name, spec in raw.get("providers", {}).items()
    }
    routing: dict[Tier, list[ModelRef]] = {}
    for tier_name, route in raw.get("routing", {}).items():
        refs = [ModelRef.parse(route["primary"])]
        refs += [ModelRef.parse(f) for f in route.get("fallback", [])]
        routing[Tier(tier_name)] = refs
    unknown = {r.provider for refs in routing.values() for r in refs} - set(providers)
    if unknown:
        raise ValueError(f"routing 引用了未定义的 provider: {sorted(unknown)}")
    defaults = raw.get("defaults", {})
    return LLMConfig(
        providers=providers,
        routing=routing,
        strategy=defaults.get("strategy", "function_calling"),
        timeout_s=int(defaults.get("timeout_s", 60)),
        max_retries=int(defaults.get("max_retries", 1)),
        max_concurrency=int(defaults.get("max_concurrency", 4)),
        retry_attempts=int(defaults.get("retry_attempts", 2)),
        retry_delay_s=float(defaults.get("retry_delay_s", 1.0)),
    )
