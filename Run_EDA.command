#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ ! -f data/needsfood.sqlite ]]; then
  print '분석 DB가 없습니다. 먼저 Refresh_Data.command를 실행하세요.'
  exit 1
fi
.venv/bin/python src/eda.py
print 'EDA · ML 검토 보고서를 갱신했습니다: http://127.0.0.1:8770/#eda'
