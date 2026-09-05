"""21 语言 i18n 键集完整性审计（P1-8 多语言审计）：EN 基准 → 19 个 dicts/*.json 比对。

用法：
    uv run python scripts/dev/audit_i18n.py            # 只读审计，stdout 报告
    uv run python scripts/dev/audit_i18n.py --fix      # 缺键 <= max-missing 用 zhipu 直译补齐
    uv run python scripts/dev/audit_i18n.py --fix --max-missing 700 --locales ar,ja

基准键集来自 web/lib/i18n/dictionaries.ts 的 EN 块（复用 translate_dictionaries.extract_en
的正则解析，含 TS 相邻字符串折叠）。ZH 块为键定义处，理论上与 EN 同键集；一并列出偏差。
--fix 只补缺键（保留 JSON 中已有译文），逐批调用 zhipu（translate_batch 校验键集与
插值占位符），写回格式 ensure_ascii=False + sort_keys。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from translate_dictionaries import (  # noqa: E402
    DICTS_TS,
    OUT_DIR,
    SKELETON_CODES,
    extract_en,
    load_api_key,
    translate_batch,
)

_FIX_BATCH = 60
_LOCALE_NAMES = {
    "ar": "Arabic",
    "bn": "Bengali",
    "de": "German",
    "es": "Spanish",
    "fa": "Persian (Farsi)",
    "fr": "French",
    "hi": "Hindi",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "yue": "Cantonese",
}


def load_locale_json(code: str) -> dict[str, str]:
    path = OUT_DIR / f"{code}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def zh_block_keys() -> dict[str, str]:
    """解析 dictionaries.ts 的 ZH 块（与 extract_en 同构）。"""
    kv = re.compile(r'"(?P<k>[A-Za-z][\w.]*)"\s*:\s*(?P<v>"(?:[^"\\]|\\.)*")')
    text = DICTS_TS.read_text(encoding="utf-8")
    match = re.search(r"const ZH: Dict = \{(?P<body>.*?)\n\};", text, re.DOTALL)
    if not match:
        raise SystemExit("未找到 ZH 字典块")
    folded = re.sub(r'("(?:[^"\\]|\\.)*")\s*\n\s*(?=")', r"\1", match.group("body"))
    return {m.group("k"): json.loads(m.group("v")) for m in kv.finditer(folded)}


def fix_locale(key: str, code: str, en: dict[str, str], missing: list[str]) -> None:
    """缺键分批 zhipu 直译（指数退避重试 ≤3）后合并写回。"""
    data = load_locale_json(code)
    done: dict[str, str] = {}
    batches = [missing[i : i + _FIX_BATCH] for i in range(0, len(missing), _FIX_BATCH)]
    for idx, batch_keys in enumerate(batches):
        payload = {k: en[k] for k in batch_keys}
        for attempt in range(1, 4):
            try:
                done.update(translate_batch(key, code, _LOCALE_NAMES.get(code, code), payload))
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    raise
                wait = 2**attempt * 5
                print(
                    f"[{code}] 批 {idx + 1}/{len(batches)} 第 {attempt} 次失败"
                    f": {str(exc)[:80]}，{wait}s 重试"
                )
                time.sleep(wait)
        print(f"[{code}] 批 {idx + 1}/{len(batches)} ok（{len(done)} keys）")
    data.update(done)
    (OUT_DIR / f"{code}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true", help="缺键 <= max-missing 的 locale 用 zhipu 补齐"
    )
    parser.add_argument("--max-missing", type=int, default=15, help="--fix 时允许补齐的最大缺键数")
    parser.add_argument(
        "--locales", default=",".join(SKELETON_CODES), help="逗号分隔的 locale 子集"
    )
    args = parser.parse_args()

    en = extract_en()
    zh = zh_block_keys()
    zh_missing = sorted(set(en) - set(zh))
    zh_extra = sorted(set(zh) - set(en))
    print(f"EN 基准 {len(en)} 键；ZH {len(zh)} 键（zh 缺 {len(zh_missing)} / 多 {len(zh_extra)}）")
    for label, keys in (("缺", zh_missing), ("多", zh_extra)):
        if keys:
            print(f"  ZH {label}键: {keys[:10]}")

    codes = [c.strip() for c in args.locales.split(",") if c.strip()]
    report: list[tuple[str, int, list[str]]] = []
    for code in codes:
        data = load_locale_json(code)
        missing = sorted(set(en) - set(data))
        extra = sorted(set(data) - set(en))
        report.append((code, len(missing), missing))
        print(f"[{code}] 缺 {len(missing)}" + (f" / 多 {len(extra)}" if extra else " / OK"))
        if missing:
            print(f"    {missing[:10]}")
    total = sum(n for _, n, _ in report)
    print(f"\n汇总：{len(codes)} locale，共缺 {total} 键" + ("，全部完整" if total == 0 else ""))

    if not args.fix:
        return
    key = load_api_key()
    todo = [(c, n, m) for c, n, m in report if 0 < n <= args.max_missing]
    skipped = [(c, n) for c, n, _ in report if n > args.max_missing]
    for code, n in skipped:
        print(f"[{code}] 缺 {n} 键 > {args.max_missing}，跳过")
    fixed = 0
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_fix_one, key, code, en, missing) for code, _, missing in todo]
        for (code, _n, _m), fut in zip(todo, futures, strict=True):
            try:
                if fut.result():
                    fixed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[{code}] 三次失败，放弃: {str(exc)[:120]}")
    print(f"补齐完成：{fixed}/{len(todo)} locale 写回")
    remain = {c: len(audit_missing(c, en)) for c, n, _ in report if 0 < n <= args.max_missing}
    if remain:
        print(f"复核未清零: {remain}")
    else:
        print("复核：全部补齐 locale 缺键清零 ✓")


def _fix_one(key: str, code: str, en: dict[str, str], missing: list[str]) -> bool:
    fix_locale(key, code, en, missing)
    print(f"[{code}] 补齐 {len(missing)} 键 ✓")
    return True


def audit_missing(code: str, en: dict[str, str]) -> list[str]:
    return sorted(set(en) - set(load_locale_json(code)))


if __name__ == "__main__":
    sys.exit(main())
