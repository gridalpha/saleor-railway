#!/usr/bin/env bash
# Pre-deploy step, run by Railway before the new container's entrypoint.
#
# Migrations belong here rather than in the entrypoint: they run outside the health
# check window, so a first boot that spends minutes building Saleor's schema cannot fail
# the deployment, and their output lands in the deploy log where it can be read.
#
# It runs for every service built from this repo, so it returns immediately for the
# roles that must not touch the schema. Only the API migrates; the worker and beat wait.
set -euo pipefail

log() { printf '[railway] pre-deploy: %s\n' "$*"; }

: "${SALEOR_ROLE:=api}"

if [ "$SALEOR_ROLE" != "api" ]; then
  log "role is ${SALEOR_ROLE}; the API owns the schema, nothing to do"
  exit 0
fi

# shellcheck source=/dev/null
. /app/railway/rsa_key.sh

log "applying migrations"
migrated=0
for attempt in $(seq 1 30); do
  if python3 manage.py migrate --no-input; then
    migrated=1
    break
  fi
  log "migrate failed (attempt ${attempt}/30); the database may still be starting"
  sleep 10
done

if [ "$migrated" != 1 ]; then
  log "migrations never succeeded"
  exit 1
fi

log "ensuring the first staff account exists"
python3 /app/railway/create_admin.py

log "done"
