#!/bin/sh
set -eu

project_dir="${HVAC_REPORT_PROJECT_DIR:-/home/pi/evap_cooler_duplex_control}"
log_dir="${HVAC_REPORT_LOG_DIR:-/home/pi/state}"
output_dir="${HVAC_REPORT_OUTPUT_DIR:-$project_dir/reports}"
python="${HVAC_REPORT_PYTHON:-python3}"
format="${HVAC_REPORT_FORMAT:-bundle}"
dry_run=0

if [ "${1:-}" = "--dry-run" ]; then
  dry_run=1
fi

schedule=$(
  TZ=America/Denver "$python" - <<'PY'
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

today = datetime.now(ZoneInfo("America/Denver")).date()
anchor = today - timedelta(days=1)
kinds = ["daily"]
if today.weekday() == 0:
    kinds.append("weekly")
if (today.month, today.day) in {(3, 20), (6, 20), (9, 22), (12, 21)}:
    kinds.append("season")
if (today.month, today.day) == (3, 20):
    kinds.append("annual")
print(anchor.isoformat(), *kinds)
PY
)

set -- $schedule
anchor=$1
shift

cd "$project_dir"
for kind in "$@"; do
  if [ "$dry_run" -eq 1 ]; then
    printf '%s\n' "$python -m hvac_reports $kind --date $anchor --log-dir $log_dir --output $output_dir --format $format"
  else
    "$python" -m hvac_reports "$kind" \
      --date "$anchor" \
      --log-dir "$log_dir" \
      --output "$output_dir" \
      --format "$format"
  fi
done
