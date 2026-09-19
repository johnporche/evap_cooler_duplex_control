# evap_cooler_duplex_control
ECDC: Python script running on a Revolution PI industrial controller to share a Breezeair evap cooler between two sections of a duplex divided house.

## Project organization

- `hvac_control.py` is the real-time Revolution Pi controller.
- `hvac_reports/` is an offline, read-only reporting package. It never imports
  `revpimodio2` and cannot change controller outputs.
- `tests/` contains standard-library unit tests.
- `report_config.example.json` documents public-safe reporting configuration.
- `log/` and `reports/` are intentionally excluded from Git because they may
  reveal household occupancy and operating patterns.

## Performance reports

Reports are centered on solar time and are available in four periods:

- `daily`: 12 hours before to 12 hours after the anchor date's solar noon.
- `weekly`: Monday through Sunday, using seven solar-day windows.
- `season`: four reports per year: March equinox to June solstice, June
  solstice to September equinox, September equinox to December solstice, and
  December solstice to the following March equinox.
- `annual`: March equinox through the following March equinox.

The default source bundle contains all three report forms: a UTF-8 text report
with block and box-drawing graphics; a LaTeX source file with standalone
text-friendly SVG charts and PGFPlots fragments; and a static HTML report
library. The RevPi does not need a TeX
installation. A client machine can compile the copied bundle into a PDF.
Reports show
their exact start/end timestamps and flag coverage below 98 percent as
incomplete.

Install the local command:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
```

Generate a daily report from the controller log:

```sh
.venv/bin/hvac-report daily \
  --date 2026-08-04 \
  --log log/hvac_state_log.csv \
  --output reports
```

Generate only the terminal-friendly text report:

```sh
.venv/bin/hvac-report daily --date 2026-08-04 \
  --log log/hvac_state_log.csv --format text
```

Add `--ascii` for systems that cannot display UTF-8 block graphics.

Generate the normal portable bundle without rendering a PDF on the RevPi:

```sh
.venv/bin/hvac-report daily --date 2026-08-04 \
  --log log/hvac_state_log.csv --format bundle
```

The output directory contains:

```text
report.txt
report.tex
charts/fan.svg
charts/fan.tex
charts/heat.svg
charts/heat.tex
charts/temperatures.svg
charts/temperatures.tex
charts/main_zone_delivery.svg
charts/main_zone_delivery.tex
charts/apartment_zone_delivery.svg
charts/apartment_zone_delivery.tex
html/index.html
html/style.css
html/daily/index.html
html/daily/2026-08-04/index.html
```

After copying that entire directory to a client with LaTeX installed:

```sh
latexmk -pdf report.tex
```

Open `reports/html/index.html` to browse daily, weekly, seasonal, and annual
reports. The site uses only portable HTML, CSS, and SVG: no JavaScript, web
server, database, fonts, or external network resources are required.

Use `--format text`, `--format source`, or `--format html` for only one output.
Use `--format pdf` to compile on the generating machine, or `--format all` for
text, sources, HTML, and PDF.

The main-floor and apartment zone-delivery charts are separate. White means the
damper was commanded closed, gray means it was commanded open without that zone
requesting airflow, and zone-colored shading means it was commanded open with
that zone requesting airflow. The fan chart uses three aligned panels for the
main-floor thermostat demand, apartment thermostat demand, and actual fan
speed. The controller log contains open/close commands, not physical
blade-position feedback; a position sensor would be required to plot actual
intermediate damper position. Daily and weekly charts also mark sunrise, solar
noon, and sunset using the timestamps recorded in the controller log. Markers
are omitted from seasonal and annual charts to avoid unreadable line density.
The heating chart aligns each zone's heat request with its boiler output and
the auxiliary-thermostat enable signal, making WWSD rejection and main-floor
HEAT-mode transitions visible.

For rotated logs, repeat `--log` for each file. To generate LaTeX and SVG
without compiling the PDF, add `--no-pdf`.

On the Revolution Pi, install a TeX distribution only if PDFs must be built on
the controller. A lighter and safer arrangement is to generate or copy reports
on another machine while the RevPi only records CSV data.

### Automatic report copy to macOS

`scripts/sync_reports_from_revpi.sh` pulls the RevPi `reports/` tree into the
local repository. The included LaunchAgent starts at login and at 03:00 each
day, then `wait_until_sunrise.py` waits for sunrise at the configured Denver
site before syncing. If the Mac is asleep, macOS starts the job after wake and
the already-passed sunrise causes the copy to proceed immediately:

```bash
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" \
  "$HOME/Library/Application Support/HVACController"
install -m 0755 scripts/sync_reports_from_revpi.sh \
  "$HOME/Library/Application Support/HVACController/"
install -m 0755 scripts/wait_until_sunrise.py \
  "$HOME/Library/Application Support/HVACController/"
cp launchd/com.johnporche.hvac-report-sync.plist "$HOME/Library/LaunchAgents/"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.johnporche.hvac-report-sync.plist"
```

The sync deliberately omits `--delete`, so a report removed from the RevPi is
not automatically removed from the Mac archive. SSH key authentication must be
configured because the background job cannot answer a password prompt.

### Scheduled reports on the RevPi

`scripts/generate_scheduled_reports.sh` uses the `America/Denver` calendar even
when the RevPi system clock is configured for UTC. Run it daily after the prior
solar day closes. It creates a daily report each run, a completed weekly report
on Monday, completed seasonal reports on March 20, June 20, September 22, and
December 21, and the completed annual report on March 20.

The installed crontab runs at 10:00 UTC (03:00 MST or 04:00 MDT). `flock`
prevents a second reporting process from starting while an earlier one is still
running:

```cron
0 10 * * * /usr/bin/flock -n /tmp/hvac-reports.lock /usr/bin/nice -n 15 /home/pi/evap_cooler_duplex_control/scripts/generate_scheduled_reports.sh >> /home/pi/evap_cooler_duplex_control/log/reports-cron.log 2>&1
```

At 11:00 UTC, a second job compresses and verifies completed state and event
archives and creates compact state summaries. It uses the same lock, so it
cannot overlap report generation. The command deliberately omits `--prune`;
active logs and historical compressed archives are retained:

```cron
0 11 * * * /usr/bin/flock -n /tmp/hvac-reports.lock /usr/bin/nice -n 15 /home/pi/evap_cooler_duplex_control/scripts/maintain_report_archives.sh >> /home/pi/evap_cooler_duplex_control/log/maintenance-cron.log 2>&1
```

## Adaptive prewet

Prewet selection is isolated in `hvac_prewet.py` and covered by unit tests. The
controller uses these restart windows:

```text
First start or pads dry at least 60 minutes     90 seconds
Restart within 5 minutes                         5 seconds
Restart after 5 through 30 minutes              15 seconds
Restart after 30 but less than 60 minutes       60 seconds
```

When outdoor temperature is at least 85 F, a 5-to-30-minute restart is
promoted from 15 to 60 seconds, not all the way to the dry-pad 90-second
duration. Damper preparation remains independent; the fan starts only when
both prewet and any required damper-settle interval are complete.

## Ventilation, post-cooling fan operation, and zone priority

The controller honors a standalone thermostat fan-stage request as `VENT` and
also recognizes post-cooling fan operation when `COOL` changes from on to off
while a fan-stage input remains on. In either case, the cooler system and fan
run with the pump off, and ventilation is limited to fan speed 2 and the
15-minute ventilation safety limit.

Heating always cancels post-cooling state. Fan-stage inputs that accompany a
`HEAT` call are ignored by the evaporative-cooler airflow logic because the
cooler fan is not available for heating. If the fan signal remains on when
`HEAT` ends, that zone reports `POST_HEAT_FAN_SUPPRESSED` and ignores the fan
until all fan stages turn off. A later, fresh fan-only call is accepted as
intentional `VENT`.

Wet cooling has priority over ventilation when the zones differ:

- If one zone is cooling and the other is in `VENT`, the
  cooling zone's damper opens and the venting zone's damper closes.
- If both zones are cooling, both dampers open.
- If neither zone is cooling and both are in `VENT`, both
  dampers open.
- If only one zone is in `VENT`, its damper opens and the
  inactive zone's damper closes.

When cooling takes over from `VENT` and requires a damper to close, the fan is
held off during `PREPARE` until prewet and damper-settle requirements are both
satisfied. The pure transition and allocation rules are isolated in
`hvac_airflow.py` and covered by unit tests.

## Cooler availability and MS1 fault reporting

The controller samples the Seeley MS1 `PWR / ERROR CODE` signal through the
existing RevPi `ERROR_IN` analog channel every 0.1 second. A sustained high
signal means the cooler is powered and ready, groups of low pulses are decoded
as fault codes, and a low signal lasting 20 seconds means that the cooler is
offline. Known MS1 codes are FC01 communication failure, FC02 failure to detect
water at the probes, FC04 failure to clear the probes during drain, and FC07
motor fault. Unknown pulse counts are still reported and inhibit operation.

Any MS1 fault or offline state forces the cooler system, pump, and fan command
off while leaving both zone dampers open. Faults are reported but are not
automatically reset. The pulse timing constants are configurable near the top
of `hvac_control.py`; validate them against a captured real fault waveform for
the installed cooler model.

Zone diagnostics distinguish the thermostat request from the mode the
controller can actually provide. Event messages report changes in the form
`COOL->COOL_BLOCKED reason=MS1_STARTUP_UNKNOWN`. The state CSV retains the
legacy `frst_mode` and `apt_mode` fields and also records
`*_requested_mode`, `*_effective_mode`, and `*_mode_reason`. Stable reasons
include MS1 startup, offline, and fault conditions; warm-weather heat
shutdown; low-OAT free cooling; rejected standalone fan calls; and conflicting
heat/cool inputs.

Boiler availability is independent and follows the existing 70 F on / 65 F
reset warm-weather shutdown. On controller startup, WWSD initializes from the
70 F trip threshold so a restart in the 65-70 F hysteresis band does not
spuriously block heat. Evaporative pump operation has separate low-OAT
hysteresis: it disables at 45 F and re-enables at 50 F. A cooling call during
that lockout becomes fan-only free cooling when the MS1 is ready. An unknown
OAT fails pump-safe. The old remembered per-floor OAT mode no longer gates
thermostat calls, preventing cool morning calls from becoming stuck in IDLE.

`T_RevPiLED_WWSD` also drives the boiler-panel thermostat interlock despite its
PiCtory LED name. A value of 1 blocks the auxiliary thermostats. The interlock
starts blocked, is enabled when a main-floor heat call establishes the latched
HEAT mode, and is blocked again by a later main-floor cooling call or by WWSD.
Ending an individual heat call does not clear the latched HEAT mode.

## Log rotation and retention

The controller writes only active files and performs fast atomic rotation:

```text
log/
├── state/current.csv
├── state/archive/YYYY/MM/hvac-state-YYYY-MM-DD.csv
├── events/current.log
├── events/archive/YYYY/MM/hvac-events-YYYY-MM-DD.log
└── summaries/YYYY/MM/summary-hvac-state-YYYY-MM-DD.json
```

Files rotate at local midnight or when the state log reaches 50 MiB (events:
25 MiB). Override the limits with `HVAC_LOG_MAX_BYTES` and
`HVAC_EVENT_LOG_MAX_BYTES`. Rotation uses an atomic rename and performs no
compression in the controller process.

Set `HVAC_LOG_DIR` to the desired log root when launching the controller. For
the repository-local layout shown above:

```sh
export HVAC_LOG_DIR=/home/pi/projects/evap_cooler_duplex_control/log
python3 hvac_control.py
```

If `HVAC_LOG_DIR` is not set, the existing `/home/pi` default remains in use.
Legacy `hvac_state_log*.csv` files remain discoverable by `--log-dir` during
the transition; they are not moved or deleted automatically.

## Boot service

The production controller runs under systemd rather than an attached terminal.
Install the tracked unit and synchronous fail-safe output helper on the RevPi:

```sh
sudo install -o root -g root -m 0755 \
  systemd/hvac-safe-outputs.py /usr/local/sbin/hvac-safe-outputs
sudo install -o root -g root -m 0644 \
  systemd/hvac-control.service /etc/systemd/system/hvac-control.service
sudo systemctl daemon-reload
sudo systemctl enable --now hvac-control.service
```

Only one controller process may access the HVAC outputs. Stop any manual
screen or tmux instance before starting the service. View controller output
with `journalctl -u hvac-control.service -f`. On every service stop or failure,
`ExecStopPost` synchronously commands the fan, pump, cooler system, boilers,
and damper-close outputs off, leaving both dampers open.

Run maintenance from cron or a systemd timer, not from `hvac_control.py`:

```sh
hvac-log-maintain --log-root log
```

This compresses closed CSV and event archives, verifies each gzip stream,
writes a checksum-backed daily JSON summary, and checks disk usage. It does not
delete anything unless `--prune` is supplied:

```sh
hvac-log-maintain --log-root log --retention-days 400 --event-retention-days 90 --prune
```

The 400-day state default keeps enough compressed raw data to regenerate a
complete spring-to-spring annual report on the device. Use a shorter period
only when raw archives are copied off-device. Pruning refuses to remove state
archives whose summary contains an MS1 fault, an MS1-offline sample, or a bad
static-pressure input. The active log is never a
pruning target. Event archives containing `SAFETY`, `ERROR`, `FAULT`, or
timeout messages are preserved beyond normal event retention.

A simple nightly cron entry is sufficient:

```cron
15 2 * * * cd /home/pi/projects/evap_cooler_duplex_control && .venv/bin/hvac-log-maintain --log-root log
```

Run pruning separately (for example, weekly) so deletion is explicit:

```cron
35 2 * * 0 cd /home/pi/projects/evap_cooler_duplex_control && .venv/bin/hvac-log-maintain --log-root log --retention-days 400 --event-retention-days 90 --prune
```

Reports can automatically discover current, archived, and gzip-compressed
state logs:

```sh
hvac-report daily --date 2026-08-04 --log-dir log --format bundle
```
