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

For rotated logs, repeat `--log` for each file. To generate LaTeX and SVG
without compiling the PDF, add `--no-pdf`.

On the Revolution Pi, install a TeX distribution only if PDFs must be built on
the controller. A lighter and safer arrangement is to generate or copy reports
on another machine while the RevPi only records CSV data.

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
only when raw archives are copied off-device. Pruning refuses to remove state archives whose summary contains an active
`ERROR_IN` sample or a bad static-pressure input. The active log is never a
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
