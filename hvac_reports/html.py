from html import escape
from pathlib import Path
import shutil


PERIODS = ("daily", "weekly", "season", "annual")


STYLE = """/* Portable report library: HTML + CSS + SVG only. */
:root { --navy:#17324d; --blue:#3478b9; --teal:#1b998b; --orange:#f28e2b;
  --red:#d1495b; --ink:#243746; --muted:#6b7c8f; --pale:#eaf1f7; --paper:#fff; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:#f4f7f9; font:16px/1.45 system-ui,sans-serif; }
header { background:var(--navy); color:white; padding:1.25rem max(1rem,calc((100% - 1100px)/2)); }
header a { color:white; }
main { max-width:1100px; margin:auto; padding:1.5rem 1rem 3rem; }
h1,h2,h3 { line-height:1.15; color:var(--navy); }
.crumbs { color:var(--muted); margin-bottom:1rem; }
.crumbs a { color:var(--blue); }
.status { display:inline-block; padding:.25rem .6rem; border-radius:.25rem; font-weight:700; }
.complete { background:#dff5ef; color:#126a5d; } .incomplete { background:#fde8e8; color:#9d2537; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); gap:.75rem; }
.card,.panel,.period { background:var(--paper); border:1px solid #d8e1e8; border-radius:.4rem; padding:1rem; }
.card strong { display:block; color:var(--muted); font-size:.8rem; text-transform:uppercase; }
.card span { font-size:1.5rem; color:var(--navy); }
.charts { display:grid; gap:1rem; margin-top:1rem; }
.charts img { display:block; width:100%; height:auto; background:white; }
.periods { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:1rem; }
.period { text-decoration:none; color:var(--ink); } .period:hover { border-color:var(--blue); }
.bar { display:grid; grid-template-columns:7rem 1fr 5rem; gap:.6rem; align-items:center; margin:.35rem 0; }
.track { height:.8rem; background:#e3e9ee; border-radius:1rem; overflow:hidden; }
.fill { height:100%; background:var(--blue); }
table { width:100%; border-collapse:collapse; background:white; }
th,td { text-align:left; padding:.5rem .65rem; border-bottom:1px solid #d8e1e8; }
th { background:var(--pale); color:var(--navy); }
code { background:#edf2f5; padding:.1rem .3rem; }
footer { max-width:1100px; margin:auto; padding:1rem; color:var(--muted); font-size:.85rem; }
@media print { body{background:white} header{padding-left:0;background:white;color:var(--navy)} header a{color:var(--navy)} .panel,.card{break-inside:avoid} }
"""


def report_directory(html_root, period):
    return Path(html_root) / period.kind / period.start.strftime("%Y-%m-%d")


def _fmt(value, digits=1, suffix=""):
    return "--" if value is None else f"{value:.{digits}f}{suffix}"


def _write_indexes(html_root):
    root = Path(html_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "style.css").write_text(STYLE, encoding="utf-8")
    cards = []
    for kind in PERIODS:
        kind_dir = root / kind
        reports = sorted(path for path in kind_dir.iterdir() if path.is_dir()) if kind_dir.exists() else []
        latest = reports[-1].name if reports else "No reports yet"
        cards.append(f'<a class="period" href="{kind}/index.html"><h2>{kind.title()}</h2><p>{len(reports)} report(s)</p><p>Latest: {escape(latest)}</p></a>')
        kind_dir.mkdir(parents=True, exist_ok=True)
        links = "\n".join(f'<li><a href="{item.name}/index.html">{escape(item.name)}</a></li>' for item in reversed(reports)) or "<li>No reports yet</li>"
        page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="../style.css"><title>{kind.title()} HVAC reports</title></head><body><header><a href="../index.html">HVAC report library</a></header><main><p class="crumbs"><a href="../index.html">All periods</a> / {kind.title()}</p><h1>{kind.title()} reports</h1><ol>{links}</ol></main><footer>Static HTML, CSS, and SVG. No JavaScript or external resources.</footer></body></html>'''
        (kind_dir / "index.html").write_text(page, encoding="utf-8")
    index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="style.css"><title>HVAC report library</title></head><body><header><strong>HVAC report library</strong></header><main><h1>System performance reports</h1><p>Select a reporting period.</p><div class="periods">{"".join(cards)}</div></main><footer>Portable static report library - HTML, CSS, text, and SVG only.</footer></body></html>'''
    (root / "index.html").write_text(index, encoding="utf-8")


def write_html_report(html_root, config, period, metrics, chart_source_dir):
    destination = report_directory(html_root, period)
    chart_dir = destination / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    source = Path(chart_source_dir)
    for name in ("fan.svg", "temperatures.svg", "main_zone_delivery.svg", "apartment_zone_delivery.svg"):
        source_file = source / name
        destination_file = chart_dir / name
        if source_file.resolve() != destination_file.resolve():
            shutil.copy2(source_file, destination_file)
    v = metrics.values
    status_class = "complete" if v["coverage"] >= 0.98 else "incomplete"
    status_text = "Complete" if v["coverage"] >= 0.98 else "Incomplete data"
    state_max = max(metrics.state_hours.values(), default=1.0)
    state_bars = "".join(
        f'<div class="bar"><span>{escape(state)}</span><div class="track"><div class="fill" style="width:{100*hours/state_max:.1f}%"></div></div><span>{hours:.2f} h</span></div>'
        for state, hours in metrics.state_hours.items()
    ) or "<p>No observed state data.</p>"
    daily_rows = "".join(
        f"<tr><td>{item['date']}</td><td>{item['observed_hours']:.2f}</td><td>{item['cooling_hours']:.2f}</td><td>{item['vent_hours']:.2f}</td></tr>"
        for item in metrics.daily_rows
    ) or '<tr><td colspan="4">No observed days</td></tr>'
    cards = [
        ("Coverage", f"{v['coverage']:.1%}"), ("Cooling starts", str(v["cooling_starts"])),
        ("Vent cycles", str(v["vent_cycles"])), ("Main calls", str(v["main_calls"])),
        ("Apartment calls", str(v["apartment_calls"])), ("Max outdoor", _fmt(v["max_oat_f"], 1, " F")),
        ("Active supply", _fmt(v["mean_active_supply_f"], 1, " F")),
    ]
    card_html = "".join(f'<div class="card"><strong>{escape(label)}</strong><span>{escape(value)}</span></div>' for label, value in cards)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="../../style.css"><title>{escape(period.label)} - HVAC report</title></head><body>
<header><a href="../../index.html">HVAC report library</a></header><main>
<p class="crumbs"><a href="../../index.html">All periods</a> / <a href="../index.html">{period.kind.title()}</a> / {escape(period.label)}</p>
<h1>{escape(config.site_name)}</h1><h2>{escape(period.label)}</h2>
<p><span class="status {status_class}">{status_text}</span> &nbsp; {period.start.strftime('%Y-%m-%d %H:%M %Z')} to {period.end.strftime('%Y-%m-%d %H:%M %Z')}</p>
<div class="cards">{card_html}</div>
<section class="charts"><div class="panel"><img src="charts/fan.svg" alt="Main and apartment thermostat demand aligned with actual fan speed"></div><div class="panel"><img src="charts/temperatures.svg" alt="Outdoor and common supply temperature chart"></div><div class="panel"><img src="charts/main_zone_delivery.svg" alt="Main-floor supply delta with damper and airflow-request state"></div><div class="panel"><img src="charts/apartment_zone_delivery.svg" alt="Apartment supply delta with damper and airflow-request state"><p><small>White means damper commanded closed; gray means commanded open without that zone requesting airflow; zone color means commanded open with that zone requesting airflow. Commands are not measured blade positions.</small></p></div></section>
<section class="panel"><h2>Operating-state hours</h2>{state_bars}</section>
<section class="panel"><h2>Daily aggregation</h2><table><thead><tr><th>Date</th><th>Observed h</th><th>Cooling h</th><th>Vent h</th></tr></thead><tbody>{daily_rows}</tbody></table></section>
<section class="panel"><h2>Diagnostics</h2><p>Static-pressure input OK: {v['static_pressure_ok_percent']:.1%} of samples<br>ERROR_IN active: {v['error_input_samples']} samples<br>Observed samples: {v['rows']:,}</p><p>No Ecobee, room-temperature, occupancy, or setpoint data is used.</p></section>
</main><footer>Portable static report - HTML, CSS, and SVG only.</footer></body></html>'''
    (destination / "index.html").write_text(page, encoding="utf-8")
    _write_indexes(html_root)
    return destination / "index.html"
