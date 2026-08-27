"""本地启动入口：uvicorn 起 oh-api（API + dashboard 单页）。

用法：uv run python scripts/dev/serve.py [--port 8787] [--reload]
浏览器打开 http://127.0.0.1:8787/ 即 dashboard。
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="OH!News 本地服务")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

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
