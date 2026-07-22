#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SEED_DEMO="${SEED_DEMO:-false}"
exec "${SCRIPT_DIR}/deploy.sh" migrate
