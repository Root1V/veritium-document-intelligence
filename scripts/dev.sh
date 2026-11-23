#!/usr/bin/env bash
# Veritium's whole development stack in one command: its containers
# (postgres, minio, redpanda), its aeon instance (scripts/aeon_dev.sh), the
# API, the worker and the frontend. Other teams' stacks (prometheus, argus…)
# are theirs to start and stop.
#
#   scripts/dev.sh up       # start everything (logs and pids in ~/.veritium/dev/)
#   scripts/dev.sh down     # stop everything; data volumes are kept
#   scripts/dev.sh status
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$HOME/.veritium/dev"
mkdir -p "$RUN"
cd "$ROOT"

# name, port (empty if none), command
start() {
  local name=$1 port=$2; shift 2
  if [ -s "$RUN/$name.pid" ] && kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null; then echo "  $name: ya estaba arriba"; return; fi
  nohup "$@" > "$RUN/$name.log" 2>&1 &
  echo $! > "$RUN/$name.pid"
  if [ -n "$port" ]; then
    for _ in $(seq 60); do lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 1; done
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || { echo "  $name: no levantó, mira $RUN/$name.log"; exit 1; }
  else  # no port to wait for: it must still be alive once started (e.g. the worker with no models in prometheus)
    sleep 15
    kill -0 "$(cat "$RUN/$name.pid")" 2>/dev/null || { echo "  $name: se cayó al arrancar, mira $RUN/$name.log"; exit 1; }
  fi
  echo "  $name: arriba (log en $RUN/$name.log)"
}

# Also stops one started by hand or by another session, found by its port or command.
stop() {
  local name=$1 port=$2 pattern=$3 pids
  pids="$(cat "$RUN/$name.pid" 2>/dev/null || true) $(pgrep -f "$pattern" || true)"
  [ -n "$port" ] && pids="$pids $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  rm -f "$RUN/$name.pid"
  echo "  $name: abajo"
}

case "${1:-}" in
  up)
    echo "contenedores"; docker compose up -d --wait
    echo "aeon"; scripts/aeon_dev.sh start
    echo "base de datos"; uv run --no-sync alembic upgrade head
    start api 8010 .venv/bin/uvicorn idp.api.app:app --port 8010
    start worker "" .venv/bin/python -m idp.worker
    start frontend 5180 npm --prefix frontend run dev
    echo "listo: http://localhost:5180"
    ;;
  down)
    stop frontend 5180 "$ROOT/frontend/node_modules/.bin/vite"
    stop worker "" "python -m idp.worker"
    stop api 8010 "uvicorn idp.api.app:app"
    echo "aeon"; scripts/aeon_dev.sh down
    echo "contenedores"; docker compose down
    ;;
  status)
    docker compose ps --format '  {{.Service}}: {{.Status}}'
    docker ps --filter label=com.docker.compose.project=veritium-aeon --format '  aeon {{.Label "com.docker.compose.service"}}: {{.Status}}'
    for p in api:8010 frontend:5180; do
      lsof -nP -iTCP:"${p#*:}" -sTCP:LISTEN >/dev/null 2>&1 && echo "  ${p%:*}: arriba" || echo "  ${p%:*}: abajo"
    done
    pgrep -f "python -m idp.worker" >/dev/null && echo "  worker: arriba" || echo "  worker: abajo"
    ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
