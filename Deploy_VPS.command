#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python src/deploy_vps.py
