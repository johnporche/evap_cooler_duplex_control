#!/bin/sh
set -eu

remote_host="${HVAC_REPORT_REMOTE_HOST:-pi@192.168.80.222}"
remote_dir="${HVAC_REPORT_REMOTE_DIR:-/home/pi/evap_cooler_duplex_control/reports/}"
local_dir="${HVAC_REPORT_LOCAL_DIR:-/Users/jporche/projects/evap_cooler_duplex_control/reports/}"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "${HVAC_REPORT_WAIT_FOR_SUNRISE:-1}" = "1" ]; then
  /usr/bin/python3 "$script_dir/wait_until_sunrise.py"
fi

/bin/mkdir -p "$local_dir"

exec /usr/bin/rsync \
  -az \
  --partial \
  -e "/usr/bin/ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=2" \
  "${remote_host}:${remote_dir}" \
  "$local_dir"
