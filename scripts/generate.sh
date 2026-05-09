#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$PROJECT_DIR/../lunar_birthday_calendar/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_DIR/../lunar_birthday_calendar/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cd "$PROJECT_DIR"
"$PYTHON_BIN" solar_birthday.py generate \
  --db private_data/birthdays.db \
  --out private_data/birthdays.ics \
  --start-year "$(date '+%Y')" \
  --end-year 2099 \
  --calendar-name "家庭公历生日" \
  --alarm-days 7
