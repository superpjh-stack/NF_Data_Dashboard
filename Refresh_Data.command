#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import openpyxl, pyxlsb' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python src/pipeline.py "$@"
.venv/bin/python src/eda.py
print '분석이 완료되었습니다. 대시보드에서 브라우저 새로고침을 실행하세요.'
