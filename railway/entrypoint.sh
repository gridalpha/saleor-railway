#!/usr/bin/env bash
# One image, three roles. SALEOR_ROLE picks which process this container runs, so the
# API, the Celery worker and the Celery beat scheduler share a build, a Dockerfile and a
# single railway.json — and a template carries the choice as an ordinary variable.
set -euo pipefail

log() { printf '[railway] %s\n' "$*"; }

: "${SALEOR_ROLE:=api}"

# shellcheck source=/dev/null
. /app/railway/rsa_key.sh

# The worker and beat must not start against a schema the API has not built yet. There
# is no service dependency ordering on Railway, so wait — but bounded, so a genuine
# failure still surfaces in the logs instead of hanging forever.
wait_for_schema() {
  for attempt in $(seq 1 60); do
    if python3 manage.py migrate --check >/dev/null 2>&1; then
      log "schema is up to date"
      return 0
    fi
    log "waiting for the API to finish migrations (attempt ${attempt}/60)"
    sleep 10
  done
  log "schema still not ready; starting anyway so the failure is visible"
}

# Celery serves no HTTP, so healthd answers Railway's probe beside it. Both processes
# run in the background and the first one to exit takes the container down with it —
# without that, a Celery process that dies at boot leaves a green deployment behind.
supervise() {
  local role_pid=$1 health_pid=$2 stopping=0
  # shellcheck disable=SC2064 — the PIDs must expand now, not when the trap fires
  trap "stopping=1; kill -TERM $role_pid $health_pid 2>/dev/null || true" TERM INT
  wait -n || true
  kill -TERM "$role_pid" "$health_pid" 2>/dev/null || true
  wait || true
  if [ "$stopping" = 1 ]; then
    log "shutting down"
    exit 0
  fi
  log "a supervised process exited on its own; failing the container so it restarts"
  exit 1
}

case "$SALEOR_ROLE" in
  api)
    : "${PORT:=8000}"
    log "starting the GraphQL API on port ${PORT}"
    # The image's own CMD, with the port and worker count made configurable.
    exec uvicorn saleor.asgi:application \
      --host=0.0.0.0 \
      --port="$PORT" \
      --workers="${UVICORN_WORKERS:-2}" \
      --lifespan=auto \
      --ws=none \
      --no-server-header \
      --no-access-log \
      --timeout-keep-alive=35 \
      --timeout-graceful-shutdown=30 \
      --limit-max-requests=10000
    ;;

  worker)
    : "${PORT:=8080}"
    wait_for_schema
    # Celery's default concurrency is the *host's* core count, which on Railway is 48 —
    # 48 prefork children of a Django app is an instant OOM. Pin it and expose the knob.
    node="${CELERY_NODE_NAME:-saleor-worker@$HOSTNAME}"
    export HEALTHD_MODE=worker
    export HEALTHD_CELERY_NODE="$node"
    log "starting the Celery worker as ${node}"
    celery --app saleor.celeryconf:app worker \
      --loglevel="${CELERY_LOGLEVEL:-info}" \
      --concurrency="${CELERY_CONCURRENCY:-4}" \
      -n "$node" &
    role_pid=$!
    python3 /app/railway/healthd.py &
    supervise "$role_pid" "$!"
    ;;

  beat)
    : "${PORT:=8080}"
    wait_for_schema
    export HEALTHD_MODE=beat
    log "starting the Celery beat scheduler"
    # DatabaseScheduler keeps the schedule in Postgres, so beat needs no local state and
    # a redeploy never loses it.
    celery --app saleor.celeryconf:app beat \
      --loglevel="${CELERY_LOGLEVEL:-info}" \
      --scheduler saleor.schedulers.schedulers.DatabaseScheduler &
    role_pid=$!
    python3 /app/railway/healthd.py &
    supervise "$role_pid" "$!"
    ;;

  *)
    log "unknown SALEOR_ROLE '${SALEOR_ROLE}'; expected api, worker or beat"
    exit 2
    ;;
esac
