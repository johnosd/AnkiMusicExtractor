#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

APP_URL="${APP_URL:-http://localhost:8000}"
HEALTH_URL="${HEALTH_URL:-${APP_URL}/health}"
WAIT_SECONDS="${WAIT_SECONDS:-120}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker não encontrado no PATH."
  exit 1
fi

if [[ "${1:-}" == "down" ]]; then
  docker compose down
  exit 0
fi

docker compose up --build -d

if ! command -v curl >/dev/null 2>&1; then
  echo "Containers iniciados. Teste em: ${APP_URL}"
  exit 0
fi

end_time=$((SECONDS + WAIT_SECONDS))
until curl -fsS "$HEALTH_URL" >/dev/null 2>&1; do
  if (( SECONDS >= end_time )); then
    echo "A API não ficou pronta em ${WAIT_SECONDS}s."
    echo "Verifique logs com: docker compose logs -f api"
    exit 1
  fi
  sleep 2
done

echo "API no ar: ${APP_URL}"
echo "Healthcheck OK: ${HEALTH_URL}"
echo "Para ver logs: docker compose logs -f api"
echo "Para parar: ./start.sh down"
