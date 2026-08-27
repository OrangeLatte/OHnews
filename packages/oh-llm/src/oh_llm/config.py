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
    """全局模型配置：供应商注册表 + 三级路由链（顺序即优先级）。"""

    providers: dict[str, ProviderSpec]
    routing: dict[Tier, list[ModelRef]]
    strategy: str = "function_calling"

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
    return LLMConfig(
        providers=providers,
        routing=routing,
        strategy=raw.get("defaults", {}).get("strategy", "function_calling"),
    )
