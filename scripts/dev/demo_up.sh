#!/usr/bin/env bash
# OH!News 一键演示：获取 demo 数据包 → 还原 → 启动 API + Web。
#
# 用法：
#   bash scripts/dev/demo_up.sh                 # 自动下载最新 demo 包并启动 (dev 模式)
#   bash scripts/dev/demo_up.sh path/to/ohnews-demo-data.zip
#   bash scripts/dev/demo_up.sh --skip-download # 使用已还原的 data/
#   bash scripts/dev/demo_up.sh --docker        # docker compose 路线 (web 在 :3100)
#
# dev 模式需要：uv (https://docs.astral.sh/uv/) + Node 20+
# 无需任何 LLM API key —— 未配置时系统以词典引擎端到端运行。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BUNDLE="dist/ohnews-demo-data.zip"
DOCKER=0
SKIP_DOWNLOAD=0
ZIP_ARG=""

for arg in "$@"; do
  case "$arg" in
    --docker) DOCKER=1 ;;
    --skip-download) SKIP_DOWNLOAD=1 ;;
    --*) echo "unknown option: $arg" >&2; exit 1 ;;
    *) ZIP_ARG="$arg" ;;
  esac
done

# --- 1. demo 数据包 ---
if [ "$SKIP_DOWNLOAD" -eq 0 ]; then
  if [ -n "$ZIP_ARG" ]; then
    BUNDLE="$ZIP_ARG"
  elif [ ! -f "$BUNDLE" ]; then
    mkdir -p dist
    echo ">> downloading demo bundle (~15 MB) ..."
    curl -L --fail --retry 3 -o "$BUNDLE" \
      "https://github.com/OrangeLatte/OHnews/releases/latest/download/ohnews-demo-data.zip"
  fi
  echo ">> restoring demo data ..."
  if command -v uv >/dev/null 2>&1; then
    uv run python scripts/dev/demo_restore.py "$BUNDLE" --force
  else
    python3 scripts/dev/demo_restore.py "$BUNDLE" --force
  fi
fi

# --- 2. 启动 ---
if [ "$DOCKER" -eq 1 ]; then
  echo ">> docker compose: api :8787, web :3100"
  docker compose -f docker/docker-compose.yml up -d --build
  echo ""
  echo "   OH!News is starting:  http://localhost:3100"
  echo "   logs: docker compose -f docker/docker-compose.yml logs -f"
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. install: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

echo ">> starting api on :8787 ..."
nohup uv run python scripts/dev/serve.py --port 8787 > /tmp/ohnews-api.log 2>&1 &
API_PID=$!
echo "$API_PID" > /tmp/ohnews-api.pid

for _ in $(seq 1 60); do
  if curl -sf -o /dev/null http://127.0.0.1:8787/; then
    break
  fi
  sleep 1
done

echo ">> starting web on :3001 ..."
(
  cd web
  [ -d node_modules ] || npm install
  npx next dev -p 3001 > /tmp/ohnews-web.log 2>&1 &
  echo $! > /tmp/ohnews-web.pid
)

echo ""
echo "   OH!News demo is running:"
echo "     Web  http://localhost:3001   (first build may take ~1 min)"
echo "     API  http://127.0.0.1:8787"
echo "   logs: /tmp/ohnews-api.log /tmp/ohnews-web.log"
echo "   stop: kill \$(cat /tmp/ohnews-api.pid) \$(cat /tmp/ohnews-web.pid)"
