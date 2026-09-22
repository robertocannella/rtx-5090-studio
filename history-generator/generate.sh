#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

docker compose build --quiet
exec docker compose run --rm history-generator "$@"
