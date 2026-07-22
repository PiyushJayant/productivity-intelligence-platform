#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "create_alloydb.sh is retained as a compatibility wrapper."
exec "${SCRIPT_DIR}/provision.sh"
