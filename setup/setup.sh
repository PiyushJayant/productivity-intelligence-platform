#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ACTION="${1:-all}"

write_env() {
  if [[ -f "${REPO_ROOT}/.env" ]]; then
    echo "Existing .env preserved. Update it from .env.example if required."
    return
  fi
  cp "${REPO_ROOT}/.env.example" "${REPO_ROOT}/.env"
  echo "Created ${REPO_ROOT}/.env without credentials."
}

case "${ACTION}" in
  env) write_env ;;
  iam|provision) "${SCRIPT_DIR}/provision.sh" ;;
  all) write_env; "${SCRIPT_DIR}/provision.sh" ;;
  *) echo "Usage: $0 [env|provision|all]" >&2; exit 1 ;;
esac
