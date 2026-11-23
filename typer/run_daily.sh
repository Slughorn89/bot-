#!/usr/bin/env bash
# Caly cykl dnia na zywo: rozliczenie wczoraj, dane, xG, kursy, typy, raport na Telegram.
# DRY=1 ./run_daily.sh: bez wysylki raportu (test).
# Blad dowolnego kroku = alert na Telegram z nazwa kroku (i dalsze kroki, ktore maja sens).
cd "$(dirname "$0")"
set -a; [ -f .env ] && . ./.env; set +a
PY=.venv/bin/python
LOG=live/daily_$(date -u +%F).log
mkdir -p live
fail() {
  echo "BLAD: $1" >> "$LOG"
  [ -n "$TELEGRAM_BOT_TOKEN" ] && curl -sS -o /dev/null "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
    --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" --data-urlencode "text=TYPER alarm: krok '$1' nie powiodl sie ($(date -u +%F\ %H:%M) UTC). Log: $LOG"
}
step() { echo "== $1 $(date -u +%T)" >> "$LOG"; shift; "$@" >> "$LOG" 2>&1; }
step settle   $PY cli.py settle   || fail settle
step fetch    $PY cli.py fetch    || { fail fetch; exit 1; }
step snapshot $PY cli.py snapshot || fail snapshot
step predict  $PY cli.py predict  || { fail predict; exit 1; }
if [ -n "$DRY" ]; then step report $PY cli.py report || fail report; else step report $PY cli.py report --send || fail report; fi
echo "== koniec $(date -u +%T)" >> "$LOG"
