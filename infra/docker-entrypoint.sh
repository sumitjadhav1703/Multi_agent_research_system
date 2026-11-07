#!/bin/sh
# One process, one Uvicorn worker, one lifespan queue consumer.
# Do not raise WEB_CONCURRENCY: each worker would start its own consumer.
set -eu

workers="${WEB_CONCURRENCY:-1}"
if [ "$workers" != "1" ]; then
  echo "Refusing to start: WEB_CONCURRENCY must be 1." >&2
  exit 1
fi

port="${PORT:-8000}"
case "$port" in
  ''|*[!0-9]*)
    echo "Refusing to start: PORT must be an integer." >&2
    exit 1
    ;;
esac

echo "ResearchMind API listening on 0.0.0.0:${port} with one Uvicorn worker."
exec uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "$port" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips='*'
