#!/usr/bin/env bash
# Local development stack: MetaTables local runtime, the loopback Markets API, the loopback Hunch
# API, the local Tau runtime of the Hunch Agent, and the Command Center site.
#
#   scripts/dev_stack.sh [all|markets|api|tau|site]     (default: all)
#
# - MetaTables: uses the laptop's running local API, otherwise starts it with `metatables serve
#   --local`. Every checkout shares that one API.
# - Markets API: the sibling ms-markets checkout's `api.main:app` on 127.0.0.1:8603, run with that
#   checkout's interpreter by scripts/local_markets_api.py; reused when already running. Hunch
#   reaches every Markets registry through it (`MARKETS_API_URL`, ADR 0006).
# - API: `api.app.local:app` on 127.0.0.1:8601, connected to the local MetaTables runtime. It
#   presents this process's SDK sign-in on every loopback request (api/app/local.py). Builds run
#   inline with heuristic research (HUNCH_RESEARCH_MODE); recorded inference needs a model provider
#   with a recorded-inference adapter and credit in the Environment named by
#   HUNCH_INFERENCE_ENVIRONMENT_UID, so set HUNCH_RESEARCH_MODE=inference in .env to use it.
# - Tau: `api.agent.main:app` on 127.0.0.1:8602 in local mode with the provider below; the
#   `.tau/extensions/hunch.py` bridge forwards the `hunch__*` tools to the local API's /mcp.
# - Site: the sibling Vite application on 127.0.0.1:5601 proxying /api to the API and /tau to Tau.
#
# Ctrl-C (or stopping the preview) stops every process this script started; a MetaTables API that
# was already running is left alone. Used by .claude/launch.json.
set -euo pipefail

MODE="${1:-all}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${HUNCH_SITE_DIR:-$ROOT/../hunch-52848869-59a2-4291-bb0b-33b01760a400}"
API_PORT="${HUNCH_LOCAL_API_PORT:-8601}"
TAU_PORT="${HUNCH_LOCAL_TAU_PORT:-8602}"
SITE_PORT="${HUNCH_LOCAL_SITE_PORT:-5601}"
MARKETS_PORT="${HUNCH_LOCAL_MARKETS_PORT:-8603}"
MARKETS_DIR="${HUNCH_MARKETS_DIR:-$(ls -d "$ROOT"/../mainsequencemarkets-* 2>/dev/null | head -n 1)}"
TAU_PROVIDER="${HUNCH_LOCAL_TAU_PROVIDER:-meta}"
TAU_MODEL="${HUNCH_LOCAL_TAU_MODEL:-muse-spark-1.3}"
TAU_THINKING="${HUNCH_LOCAL_TAU_THINKING:-medium}"
RESEARCH_MODE="${HUNCH_RESEARCH_MODE:-heuristic}"
CONNECTOR_MODE="${HUNCH_CONNECTOR_MODE:-simulated}"
PY="$ROOT/.venv/bin/python"
METATABLES="$ROOT/.venv/bin/metatables"

case "$MODE" in
  all | markets | api | tau | site) ;;
  *)
    echo "usage: scripts/dev_stack.sh [all|markets|api|tau|site]" >&2
    exit 2
    ;;
esac

cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
export MAINSEQUENCE_AUTH_MODE=jwt
unset APP_NAME FASTAPI_PUBLIC_BASE_URL MAINSEQUENCE_CALLER_AUTH_MODE

PIDS=()

log() { echo "[dev-stack] $*"; }
die() {
  echo "[dev-stack] $*" >&2
  exit 1
}
prefix() { awk -v tag="[$1] " '{ print tag $0; fflush() }'; }
port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR == 2 { print $1 " (pid " $2 ")" }'; }

cleanup() {
  trap - EXIT INT TERM
  local pid
  for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

require_free_port() {
  port_in_use "$1" || return 0
  die "$2 port $1 is already in use by $(port_owner "$1"). Stop it first; the ports are fixed."
}

wait_for_url() {
  local name="$1" url="$2" attempt
  for attempt in $(seq 1 90); do
    if curl -sf -m 3 "$url" >/dev/null 2>&1; then
      log "$name: ready at $url"
      return 0
    fi
    sleep 1
  done
  die "$name did not become ready at $url."
}

# Prints the running local MetaTables API's port; fails when no local API is running.
metatables_connection_port() {
  "$PY" - <<'PY' 2>/dev/null
import socket
import sys
from urllib.parse import urlsplit

from metatables import configure_local_client

try:
    target = urlsplit(configure_local_client())
    with socket.create_connection((target.hostname, target.port), timeout=1):
        pass
except Exception:
    sys.exit(1)
print(target.port)
PY
}

ensure_metatables() {
  local port
  if ! port="$(metatables_connection_port)"; then
    log "MetaTables: starting the local API"
    "$METATABLES" serve --local --no-open-browser > >(prefix metatables) 2>&1 &
    local launcher="$!" attempt
    for attempt in $(seq 1 60); do
      port="$(metatables_connection_port)" && break
      kill -0 "$launcher" 2>/dev/null || die "MetaTables exited before it was ready."
      sleep 1
    done
    [[ -n "$port" ]] || die "The local MetaTables API did not become ready."
    PIDS+=("$launcher")
  fi
  log "MetaTables: local API on 127.0.0.1:$port"
  report_local_schema
}

# Warns (never migrates) when the runtime or this project's schema needs a manual step.
report_local_schema() {
  "$PY" - <<'PY' 2>&1 | prefix metatables || true
from metatables import configure_local_client, get_runtime_status

configure_local_client()
state = get_runtime_status()
bootstrap = state.get("bootstrap") or {}
if state.get("local_mode") is not True:
    print("WARNING: the API is not in Local mode; restart it with metatables serve --local.")
elif bootstrap.get("status") != "ready" or not bootstrap.get("active", True):
    print("WARNING: the local runtime is not initialized: metatables --local runtime initialize")
else:
    from hunch.migrations.schema_gate import schema_state

    for provider in schema_state().providers:
        if provider.behind:
            print(
                f"WARNING: {provider.provider} is behind ({', '.join(provider.applied) or 'none'}"
                f" -> {provider.code_head}): metatables --local migrations upgrade "
                f"--provider {provider.provider} head"
            )
    print(f"local runtime ready: {(state.get('data_source') or {}).get('uid')}")
PY
}

# True when an HTTP server answers at the URL, whatever the status: every Markets API route,
# /openapi.json included, requires a caller and answers 401 without one.
http_answers() {
  local code
  code="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null)"
  [[ -n "$code" && "$code" != "000" ]]
}

# The loopback Markets API: reused when it already answers, otherwise started from the checkout.
ensure_markets() {
  local url="http://127.0.0.1:$MARKETS_PORT" attempt
  if port_in_use "$MARKETS_PORT"; then
    http_answers "$url/openapi.json" \
      || die "Port $MARKETS_PORT is in use by $(port_owner "$MARKETS_PORT"), which does not answer HTTP."
    log "Markets API: reusing $url"
    return 0
  fi
  [[ -n "$MARKETS_DIR" && -x "$MARKETS_DIR/.venv/bin/python" ]] \
    || die "No ms-markets checkout with a .venv next to this one; set HUNCH_MARKETS_DIR."
  log "Markets API: $url (from $MARKETS_DIR)"
  (cd "$MARKETS_DIR" && exec "$MARKETS_DIR/.venv/bin/python" "$ROOT/scripts/local_markets_api.py" \
    --port "$MARKETS_PORT") > >(prefix markets) 2>&1 &
  local launcher="$!"
  PIDS+=("$launcher")
  # Startup attaches every Markets table; allow a few minutes.
  for attempt in $(seq 1 300); do
    if http_answers "$url/openapi.json"; then
      log "Markets API: ready at $url"
      return 0
    fi
    kill -0 "$launcher" 2>/dev/null || die "The Markets API exited before it was ready."
    sleep 1
  done
  die "The Markets API did not become ready at $url."
}

start_api() {
  require_free_port "$API_PORT" "API"
  log "API: http://127.0.0.1:$API_PORT (research: $RESEARCH_MODE, connectors: $CONNECTOR_MODE, builds inline)"
  PYTHONPATH="$ROOT" \
    MARKETS_API_URL="http://127.0.0.1:$MARKETS_PORT" \
    HUNCH_LOCAL_TAU_ORIGIN="http://127.0.0.1:$TAU_PORT" \
    HUNCH_RESEARCH_MODE="$RESEARCH_MODE" \
    HUNCH_CONNECTOR_MODE="$CONNECTOR_MODE" \
    HUNCH_BUILD_EXECUTION="${HUNCH_BUILD_EXECUTION:-inline}" \
    "$PY" -c '
import sys

from metatables import configure_local_client

configure_local_client()
from uvicorn.main import main

main(sys.argv[1:], prog_name="uvicorn")
' api.app.local:app --host 127.0.0.1 --port "$API_PORT" > >(prefix api) 2>&1 &
  PIDS+=("$!")
  wait_for_url "API" "http://127.0.0.1:$API_PORT/healthz"
}

start_tau() {
  require_free_port "$TAU_PORT" "Tau"
  log "Tau: http://127.0.0.1:$TAU_PORT ($TAU_PROVIDER / $TAU_MODEL)"
  PYTHONPATH="$ROOT" \
    TAU_LOCAL_MODE=true \
    TAU_LOCAL_PROVIDER="$TAU_PROVIDER" \
    TAU_LOCAL_MODEL="$TAU_MODEL" \
    TAU_LOCAL_THINKING="$TAU_THINKING" \
    TAU_EXCLUDE_BASE_TOOLS=true \
    TAU_EXCLUDE_MAINSEQUENCE_MCP=true \
    MAINSEQUENCE_TAU_PORT="$TAU_PORT" \
    HUNCH_LOCAL_API_ORIGIN="http://127.0.0.1:$API_PORT" \
    "$PY" -m uvicorn api.agent.main:app --host 127.0.0.1 --port "$TAU_PORT" > >(prefix tau) 2>&1 &
  PIDS+=("$!")
  wait_for_url "Tau" "http://127.0.0.1:$TAU_PORT/health"
  wait_for_url "Tau provider and authentication" "http://127.0.0.1:$TAU_PORT/ready"
}

start_site() {
  local vite="$SITE_DIR/node_modules/vite/bin/vite.js"
  [[ -f "$vite" ]] || die "Vite is missing; run 'npm ci' in $SITE_DIR."
  command -v node >/dev/null || die "node is not on PATH."
  require_free_port "$SITE_PORT" "Site"
  log "Site: http://127.0.0.1:$SITE_PORT"
  (cd "$SITE_DIR" && \
    HUNCH_LOCAL_API_ORIGIN="http://127.0.0.1:$API_PORT" \
    HUNCH_LOCAL_TAU_ORIGIN="http://127.0.0.1:$TAU_PORT" \
    MAINSEQUENCE_CLI="${MAINSEQUENCE_CLI:-$ROOT/.venv/bin/mainsequence}" \
    exec node "$vite" --host 127.0.0.1 --port "$SITE_PORT" --strictPort) > >(prefix site) 2>&1 &
  PIDS+=("$!")
}

case "$MODE" in
  all)
    ensure_metatables
    ensure_markets
    start_api
    start_tau
    start_site
    ;;
  markets)
    ensure_metatables
    ensure_markets
    ;;
  api)
    ensure_metatables
    ensure_markets
    start_api
    ;;
  tau)
    start_tau
    ;;
  site) start_site ;;
esac

# Stop everything as soon as any started process exits.
while true; do
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || die "A process exited (pid $pid); stopping the stack."
  done
  sleep 2
done
