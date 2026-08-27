# OH!News API（单进程态，裁决 D：FastAPI + APScheduler + langgraph 同进程）
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# workspace editable 安装需要源码在场：先拷源码清单，再一次 sync
# （牺牲层缓存粒度换正确性；依赖变更频率低，可接受）
COPY pyproject.toml uv.lock ./
COPY packages ./packages
RUN uv sync --frozen --no-dev

EXPOSE 8787
# build 期 uv sync 已装好 .venv（editable 包含在内）；运行时直接用 venv 入口，
# 避免 uv run 每次容器启动重新解析/构建 workspace
CMD ["/app/.venv/bin/uvicorn", "oh_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787"]
