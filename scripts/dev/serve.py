"""本地启动入口：uvicorn 起 oh-api（API + dashboard 单页）。

用法：uv run python scripts/dev/serve.py [--port 8787] [--reload]
浏览器打开 http://127.0.0.1:8787/ 即 dashboard。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def _load_dotenv() -> None:
    """加载项目根 .env（KEY=VALUE 行，# 注释）；不覆盖已有环境变量。

    密钥类配置（如 ZHIPU_API_KEY）经此注入，避免写入 git 追踪的 models.yaml。
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> None:
    parser = argparse.ArgumentParser(description="OH!News 本地服务")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    _load_dotenv()

    # factory 模式：uvicorn 无参调用 create_app()，AppPaths 默认值即生产布局
    # （root=data/, sources_yaml=config/sources.yaml）；数据目录经环境变量
    # OHNEWS_DATA_ROOT 覆盖由 AppPaths 读取（Phase 5b）。
    uvicorn.run(
        "oh_api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
