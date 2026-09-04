"""21 语言字典翻译管线（M5 需求①收尾）：EN 全量键 → LLM 批量翻译 → 19 语言 JSON。

流程：
1. 从 web/lib/i18n/dictionaries.ts 提取 EN 字典（正则解析 TS 对象字面量）。
2. 逐语言分批调用 zhipu（glm-5.3-flash）翻译，强制 JSON 输出。
3. 校验：键集合一致 + 插值占位符（{n} 等）集合一致；失败指数退避重试 ≤3。
4. 写 web/lib/i18n/dicts/{locale}.json（ensure_ascii=False，dictionaries.ts 合并）。

幂等：输出文件键全则跳过（--force 强制重跑）。
安全：API key 只从 .env / 环境变量读取，绝不写入任何被追踪文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DICTS_TS = PROJECT_ROOT / "web/lib/i18n/dictionaries.ts"
OUT_DIR = PROJECT_ROOT / "web/lib/i18n/dicts"

SKELETON_CODES = [
    "fr",
    "es",
    "ar",
    "ru",
    "de",
    "ja",
    "pt",
    "hi",
    "ko",
    "it",
    "tr",
    "nl",
    "pl",
    "sv",
    "fa",
    "id",
    "vi",
    "bn",
    "yue",
]

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-5.3-flash"

_KV_RE = re.compile(r'"(?P<k>[A-Za-z][\w.]*)"\s*:\s*(?P<v>"(?:[^"\\]|\\.)*")')
_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")


def load_api_key() -> str:
    """.env 优先级低于真实环境变量；key 只在内存使用。"""
    key = os.environ.get("ZHIPU_API_KEY", "")
    if key:
        return key.strip()
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ZHIPU_API_KEY="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("ZHIPU_API_KEY 未配置（.env 或环境变量）")


def extract_en() -> dict[str, str]:
    """解析 dictionaries.ts 中 EN 块的键值对（TS 相邻字符串拼接已折叠为单值）。"""
    text = DICTS_TS.read_text(encoding="utf-8")
    match = re.search(r"const EN: Dict = \{(?P<body>.*?)\n\};", text, re.DOTALL)
    if not match:
        raise SystemExit("未找到 EN 字典块")
    body = match.group("body")
    # TS 对象字面量中相邻字符串字面量会拼接：先把 "a" "b" 折叠为 "ab"
    folded = re.sub(r'("(?:[^"\\]|\\.)*")\s*\n\s*(?=")', r"\1", body)
    result: dict[str, str] = {}
    for m in _KV_RE.finditer(folded):
        result[m.group("k")] = json.loads(m.group("v"))
    if not result:
        raise SystemExit("EN 字典解析为空")
    return result


def _unwrap(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    return text.strip()


def translate_batch(
    key: str, locale: str, locale_name: str, items: dict[str, str]
) -> dict[str, str]:
    """单批翻译；返回 {key: translation}。键/占位符不一致时抛 ValueError。"""
    payload = json.dumps(items, ensure_ascii=False, indent=0)
    system = (
        f"You are a senior localizer for a news-analysis research product. "
        f"Translate UI strings from English into {locale_name} (locale code: {locale}). "
        f"Rules: keep {PLACEHOLDER_DOC} placeholders like {{n}} unchanged; "
        "keep the tone short, professional and neutral; do not translate proper nouns like "
        "OH!News, NDI or artifact class names; return ONLY a JSON object mapping the same "
        "keys to the translated strings."
    )
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": payload},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=300,
        # 绕过 macOS 系统代理（进程可能已死导致 ProxyError），直连 API。
        proxies={"http": None, "https": None},
    )
    resp.raise_for_status()
    data = json.loads(_unwrap(resp.json()["choices"][0]["message"]["content"]))
    if not isinstance(data, dict):
        raise ValueError("LLM 输出不是 JSON 对象")
    missing = set(items) - set(data)
    if missing:
        raise ValueError(f"缺 {len(missing)} 键: {sorted(missing)[:3]}")
    for k, src in items.items():
        if set(_PLACEHOLDER_RE.findall(src)) != set(_PLACEHOLDER_RE.findall(data[k])):
            raise ValueError(f"占位符不一致: {k}")
    return data


PLACEHOLDER_DOC = "interpolation"


def translate_locale(key: str, code: str, en: dict[str, str], batch_size: int, force: bool) -> bool:
    """翻译单语言并写 JSON；返回是否实际执行了翻译。"""
    out = OUT_DIR / f"{code}.json"
    if not force and out.exists():
        have = json.loads(out.read_text(encoding="utf-8"))
        if set(have) == set(en):
            print(f"[{code}] 已完成，跳过（--force 重跑）")
            return False
    keys = list(en)
    batches = [
        {k: en[k] for k in keys[i : i + batch_size]} for i in range(0, len(keys), batch_size)
    ]
    merged: dict[str, str] = {}
    for idx, batch in enumerate(batches):
        for attempt in range(1, 4):
            try:
                merged.update(translate_batch(key, code, code.upper(), batch))
                break
            except Exception as exc:  # noqa: BLE001
                wait = 2**attempt * 5
                reason = str(exc)[:80]
                print(
                    f"[{code}] 批 {idx + 1}/{len(batches)}"
                    f" 第 {attempt} 次失败: {reason}，{wait}s 重试"
                )
                time.sleep(wait)
        else:
            raise SystemExit(f"[{code}] 批 {idx + 1} 三次失败，终止")
        print(f"[{code}] 批 {idx + 1}/{len(batches)} ok ({len(merged)} keys)")
    if len(merged) != len(en):
        raise SystemExit(f"[{code}] 键数不符 {len(merged)}/{len(en)}，拒绝写入")
    out.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[{code}] 写入 {out.name}: {len(merged)} keys")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locales", default=",".join(SKELETON_CODES))
    parser.add_argument("--batch-size", type=int, default=60)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    en = extract_en()
    print(f"EN 字典 {len(en)} 键；语言: {args.locales}")
    key = load_api_key()
    codes = [c.strip() for c in args.locales.split(",") if c.strip()]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(translate_locale, key, c, en, args.batch_size, args.force) for c in codes
        ]
        done = [f.result() for f in futures]
    print(f"完成：{sum(done)}/{len(codes)} 语言实际翻译")


if __name__ == "__main__":
    sys.exit(main())
