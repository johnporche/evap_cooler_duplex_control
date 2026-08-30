#!/bin/sh
set -eu

project_dir="${HVAC_REPORT_PROJECT_DIR:-/home/pi/evap_cooler_duplex_control}"
log_root="${HVAC_REPORT_LOG_ROOT:-/home/pi}"
python="${HVAC_REPORT_PYTHON:-python3}"

cd "$project_dir"
exec "$python" -m hvac_reports.maintenance --log-root "$log_root"
