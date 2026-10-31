#!/usr/bin/env bash
# Opakowanie zadan crona: log startu, konca i bledu; blad = wpis w live/alerts.json.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs live
ts() { date -u +"%Y-%m-%d %H:%M:%S UTC"; }
echo "$(ts) START $*" >> logs/cron.log
if .venv/bin/python cli.py "$@" >> logs/cron.log 2>&1; then
  echo "$(ts) OK $*" >> logs/cron.log
else
  code=$?
  echo "$(ts) BLAD($code) $*" >> logs/cron.log
  # kod 1/2 z backtestu/learn to werdykt, nie awaria
  if [[ "$1" != "backtest" && "$1" != "learn" ]] || [[ $code -gt 2 ]]; then
    .venv/bin/python -c "from typer.pipeline.daily import alert; alert('zadanie cron $* zakonczone kodem $code')"
  fi
  exit $code
fi
