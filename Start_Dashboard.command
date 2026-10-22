#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import openpyxl, pyxlsb' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi
if [[ ! -f data/needsfood.sqlite ]]; then
  .venv/bin/python src/pipeline.py
fi
if ! .venv/bin/python -c 'import sys; sys.path.insert(0,"src"); import eda; eda.load_report()' >/dev/null 2>&1; then
  .venv/bin/python src/eda.py
fi
if .venv/bin/python - <<'PY'
import json,urllib.request
try:
    data=json.load(urllib.request.urlopen('http://127.0.0.1:8770/healthz',timeout=2))
    raise SystemExit(0 if data.get('app')=='needsfood-data-dashboard' else 1)
except Exception:raise SystemExit(1)
PY
then
  print '니즈푸드 대시보드가 이미 실행 중입니다: http://127.0.0.1:8770'
  exit 0
fi
print '브라우저에서 http://127.0.0.1:8770 을 여세요. 종료: Control+C'
exec .venv/bin/python src/server.py --port 8770
