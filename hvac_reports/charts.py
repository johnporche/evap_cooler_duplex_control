from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape


COLORS = {"navy": "#17324D", "blue": "#3478B9", "teal": "#1B998B", "orange": "#F28E2B", "red": "#D1495B", "gray": "#6B7C8F"}
SOLAR_COLORS = {"Sunrise": "#D97706", "Solar noon": "#8A6D1D", "Sunset": "#6C63A8"}


def _sample(rows, maximum=900):
    if len(rows) <= maximum:
        return rows
    step = max(1, len(rows) // maximum)
    sampled = rows[::step]
    if sampled[-1] is not rows[-1]:
        sampled.append(rows[-1])
    return sampled


def _series(rows, period, field):
    points = []
    for row in _sample(rows):
        value = row.get(field)
        if value is not None:
            hour = (row["timestamp"] - period.start).total_seconds() / 3600.0
            points.append((hour, float(value)))
    return points


def _damper_open_series(rows, period, close_field, closed_level, open_level):
    points = []
    for row in _sample(rows):
        hour = (row["timestamp"] - period.start).total_seconds() / 3600.0
        points.append((hour, closed_level if row.get(close_field) else open_level))
    return points


def _demand_series(rows, period, field):
    levels = {"OFF": 0.0, "LOW": 1.0, "MED": 2.0, "HIGH": 3.0}
    points = []
    for row in _sample(rows):
        hour = (row["timestamp"] - period.start).total_seconds() / 3600.0
        points.append((hour, levels.get(row.get(field), 0.0)))
    return points


def _intervals_when(rows, period, predicate, maximum_gap_seconds=60.0):
    intervals = []
    start = None
    previous = None
    for row in rows:
        timestamp = row["timestamp"]
        hour = (timestamp - period.start).total_seconds() / 3600.0
        if previous is not None and (timestamp - previous).total_seconds() > maximum_gap_seconds:
            if start is not None:
                intervals.append((start, (previous - period.start).total_seconds() / 3600.0))
                start = None
        selected = predicate(row)
        if selected and start is None:
            start = hour
        elif not selected and start is not None:
            intervals.append((start, hour))
            start = None
        previous = timestamp
    if start is not None and previous is not None:
        intervals.append((start, (previous - period.start).total_seconds() / 3600.0))
    return [(max(0.0, a), min(period.hours, b)) for a, b in intervals if b > a]


def _open_intervals(rows, period, close_field, maximum_gap_seconds=60.0):
    return _intervals_when(
        rows,
        period,
        lambda row: not row.get(close_field),
        maximum_gap_seconds,
    )


def _damper_state_intervals(rows, period, close_field, air_allowed_field):
    open_inactive = _intervals_when(
        rows,
        period,
        lambda row: not row.get(close_field) and not row.get(air_allowed_field),
    )
    open_active = _intervals_when(
        rows,
        period,
        lambda row: not row.get(close_field) and row.get(air_allowed_field),
    )
    return open_inactive, open_active


def _solar_markers(rows, period, maximum_markers=24):
    """Return log-derived sunrise, solar-noon, and sunset chart markers."""
    days = {}
    for row in rows:
        sunrise_text = row.get("sunrise_local")
        sunset_text = row.get("sunset_local")
        if not sunrise_text or not sunset_text:
            continue
        try:
            sunrise = datetime.fromisoformat(sunrise_text)
            sunset = datetime.fromisoformat(sunset_text)
        except (TypeError, ValueError):
            continue
        days[(sunrise.date(), sunrise.utcoffset())] = (sunrise, sunset)

    markers = []
    for sunrise, sunset in sorted(days.values()):
        solar_noon = sunrise + (sunset - sunrise) / 2
        for label, timestamp in (
            ("Sunrise", sunrise),
            ("Solar noon", solar_noon),
            ("Sunset", sunset),
        ):
            if period.start <= timestamp < period.end:
                hour = (timestamp - period.start).total_seconds() / 3600.0
                markers.append((label, hour, timestamp.strftime("%H:%M"), SOLAR_COLORS[label]))

    # Daily and weekly charts remain legible. Seasonal and annual reports would
    # otherwise contain hundreds of nearly overlapping vertical lines.
    return markers if len(markers) <= maximum_markers else []


def _path(points, x0, y0, width, height, xmin, xmax, ymin, ymax):
    if not points or xmax == xmin or ymax == ymin:
        return ""
    coords = []
    for x, y in points:
        px = x0 + (x - xmin) / (xmax - xmin) * width
        py = y0 + height - (y - ymin) / (ymax - ymin) * height
        coords.append((px, py))
    return " ".join(("M" if i == 0 else "L") + f" {x:.2f} {y:.2f}" for i, (x, y) in enumerate(coords))


def svg_line_chart(path, title, series, x_range, y_range, y_label, bands=None, band_color="#1B998B", band_label=None, band_layers=None, markers=None):
    width, height = 1100, 400
    x0, y0, plot_w, plot_h = 75, 55, 985, 285
    xmin, xmax = x_range; ymin, ymax = y_range
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<text x="{x0}" y="28" font-family="sans-serif" font-size="20" font-weight="700" fill="{COLORS["navy"]}">{escape(title)}</text>']
    layers = band_layers or [(bands or [], band_color, 0.12, band_label)]
    for intervals, layer_color, opacity, _ in layers:
        for start, end in intervals:
            left = x0 + (start - xmin) / (xmax - xmin) * plot_w
            band_width = (end - start) / (xmax - xmin) * plot_w
            elements.append(f'<rect x="{left:.2f}" y="{y0}" width="{band_width:.2f}" height="{plot_h}" fill="{layer_color}" fill-opacity="{opacity:.2f}"/>')
    for i in range(6):
        y = y0 + plot_h * i / 5
        value = ymax - (ymax - ymin) * i / 5
        elements += [f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+plot_w}" y2="{y:.1f}" stroke="#D8E1E8"/>',
                     f'<text x="{x0-10}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="{COLORS["gray"]}">{value:.0f}</text>']
    for i in range(7):
        x = x0 + plot_w * i / 6
        value = xmin + (xmax - xmin) * i / 6
        elements.append(f'<text x="{x:.1f}" y="365" text-anchor="middle" font-family="sans-serif" font-size="11" fill="{COLORS["gray"]}">{value:.0f}h</text>')
    for label, hour, clock, marker_color in markers or []:
        x = x0 + (hour - xmin) / (xmax - xmin) * plot_w
        elements += [
            f'<line x1="{x:.2f}" y1="{y0}" x2="{x:.2f}" y2="{y0+plot_h}" stroke="{marker_color}" stroke-width="1.5" stroke-dasharray="5 4"/>',
            f'<text x="{x+4:.2f}" y="{y0+6}" transform="rotate(90 {x+4:.2f} {y0+6})" font-family="sans-serif" font-size="11" fill="{marker_color}">{escape(label)} {clock}</text>',
        ]
    for name, points, color in series:
        d = _path(points, x0, y0, plot_w, plot_h, xmin, xmax, ymin, ymax)
        elements.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
    elements.append(f'<text x="18" y="{y0+plot_h/2}" transform="rotate(-90 18 {y0+plot_h/2})" text-anchor="middle" font-family="sans-serif" font-size="12">{escape(y_label)}</text>')
    lx = x0
    for name, _, color in series:
        elements += [f'<line x1="{lx}" y1="388" x2="{lx+22}" y2="388" stroke="{color}" stroke-width="3"/>',
                     f'<text x="{lx+28}" y="392" font-family="sans-serif" font-size="12">{escape(name)}</text>']
        lx += 180
    for _, layer_color, opacity, layer_label in layers:
        if layer_label:
            elements += [f'<rect x="{lx}" y="379" width="22" height="12" fill="{layer_color}" fill-opacity="{max(opacity, 0.18):.2f}"/>',
                         f'<text x="{lx+28}" y="392" font-family="sans-serif" font-size="12">{escape(layer_label)}</text>']
            lx += 230
    elements.append('</svg>')
    Path(path).write_text("\n".join(elements), encoding="utf-8")


def pgf_line_chart(path, title, series, x_range, y_range, y_label, height="0.30", bands=None, band_color="ReportTeal", band_layers=None, markers=None):
    xmin, xmax = x_range; ymin, ymax = y_range
    lines = [r"\begin{tikzpicture}",
             rf"\begin{{axis}}[width=\textwidth,height={height}\textheight,grid=major,",
             f"title={{{title}}},xlabel={{Hours from report start}},ylabel={{{y_label}}},",
             f"xmin={xmin:.3f},xmax={xmax:.3f},ymin={ymin:.3f},ymax={ymax:.3f},",
             r"legend style={at={(0.5,-0.22)},anchor=north,legend columns=-1},tick label style={font=\small}]" ]
    layers = band_layers or [(bands or [], band_color, 0.12)]
    for intervals, layer_color, opacity in layers:
        for start, end in intervals:
            lines.append(f"\\path[fill={layer_color},fill opacity={opacity:.2f},draw=none] (axis cs:{start:.4f},{ymin:.4f}) rectangle (axis cs:{end:.4f},{ymax:.4f});")
    for label, hour, clock, _ in markers or []:
        lines.append(
            f"\\draw[ReportSolar,dashed,thin] (axis cs:{hour:.4f},{ymin:.4f}) -- "
            f"node[pos=0.98,rotate=-90,anchor=north east,font=\\scriptsize] {{{label} {clock}}} "
            f"(axis cs:{hour:.4f},{ymax:.4f});"
        )
    latex_colors = ["ReportBlue", "ReportOrange", "ReportTeal", "ReportRed"]
    for index, (name, points, _) in enumerate(series):
        coords = " ".join(f"({x:.4f},{y:.4f})" for x, y in points)
        lines += [f"\\addplot+[no marks,thick,color={latex_colors[index % len(latex_colors)]}] coordinates {{{coords}}};",
                  f"\\addlegendentry{{{name}}}"]
    lines += [r"\end{axis}", r"\end{tikzpicture}"]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def svg_stacked_chart(path, title, panels, x_range, markers=None):
    width, height = 1100, 610
    x0, plot_w, panel_h, gap = 85, 970, 125, 32
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<text x="{x0}" y="28" font-family="sans-serif" font-size="20" font-weight="700" fill="{COLORS["navy"]}">{escape(title)}</text>']
    xmin, xmax = x_range
    plot_top = 55
    plot_bottom = 55 + 3 * (panel_h + gap) - gap
    for label, hour, clock, marker_color in markers or []:
        x = x0 + (hour - xmin) / (xmax - xmin) * plot_w
        elements += [
            f'<line x1="{x:.2f}" y1="{plot_top}" x2="{x:.2f}" y2="{plot_bottom}" stroke="{marker_color}" stroke-width="1.5" stroke-dasharray="5 4"/>',
            f'<text x="{x+4:.2f}" y="{plot_top+6}" transform="rotate(90 {x+4:.2f} {plot_top+6})" font-family="sans-serif" font-size="11" fill="{marker_color}">{escape(label)} {clock}</text>',
        ]
    for panel_index, (label, points, y_range, color) in enumerate(panels):
        y0 = 55 + panel_index * (panel_h + gap)
        ymin, ymax = y_range
        for i in range(4):
            y = y0 + panel_h * i / 3
            value = ymax - (ymax - ymin) * i / 3
            elements += [f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+plot_w}" y2="{y:.1f}" stroke="#D8E1E8"/>',
                         f'<text x="{x0-8}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="11" fill="{COLORS["gray"]}">{value:.0f}</text>']
        d = _path(points, x0, y0, plot_w, panel_h, xmin, xmax, ymin, ymax)
        elements += [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>',
                     f'<text x="12" y="{y0+panel_h/2}" transform="rotate(-90 12 {y0+panel_h/2})" text-anchor="middle" font-family="sans-serif" font-size="12">{escape(label)}</text>']
    axis_y = 55 + 3 * (panel_h + gap) - gap
    for i in range(7):
        x = x0 + plot_w * i / 6
        value = xmin + (xmax - xmin) * i / 6
        elements.append(f'<text x="{x:.1f}" y="{axis_y+28}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="{COLORS["gray"]}">{value:.0f}h</text>')
    elements += [f'<text x="{x0+plot_w/2}" y="{axis_y+50}" text-anchor="middle" font-family="sans-serif" font-size="12">Hours from report start</text>',
                 f'<text x="{x0}" y="{height-12}" font-family="sans-serif" font-size="11" fill="{COLORS["gray"]}">Demand scale: 0=OFF, 1=LOW, 2=MED, 3=HIGH</text>', '</svg>']
    Path(path).write_text("\n".join(elements), encoding="utf-8")


def pgf_stacked_chart(path, title, panels, x_range, markers=None):
    xmin, xmax = x_range
    lines = [f"\\begin{{center}}\\textbf{{{title}}}\\end{{center}}"]
    for index, (label, points, y_range, color) in enumerate(panels):
        ymin, ymax = y_range
        xlabel = "xlabel={Hours from report start}," if index == len(panels) - 1 else "xticklabels={},"
        coords = " ".join(f"({x:.4f},{y:.4f})" for x, y in points)
        latex_color = ["ReportBlue", "ReportOrange", "ReportTeal"][index % 3]
        lines += [r"\begin{tikzpicture}",
                  rf"\begin{{axis}}[width=\textwidth,height=0.145\textheight,grid=major,ylabel={{{label}}},{xlabel}xmin={xmin:.3f},xmax={xmax:.3f},ymin={ymin:.3f},ymax={ymax:.3f},tick label style={{font=\small}}]",
                  f"\\addplot+[no marks,thick,color={latex_color}] coordinates {{{coords}}};"]
        for marker_label, hour, clock, _ in markers or []:
            marker_node = (
                f" node[pos=0.98,rotate=-90,anchor=north east,font=\\scriptsize] "
                f"{{{marker_label} {clock}}}"
                if index == 0 else ""
            )
            lines.append(
                f"\\draw[ReportSolar,dashed,thin] (axis cs:{hour:.4f},{ymin:.4f}) --"
                f"{marker_node} (axis cs:{hour:.4f},{ymax:.4f});"
            )
        lines += [r"\end{axis}", r"\end{tikzpicture}\par"]
    lines.append(r"\small Demand scale: 0=OFF, 1=LOW, 2=MED, 3=HIGH.")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def generate_charts(rows, period, output_dir, include_pgf=True):
    chart_dir = Path(output_dir) / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    hours = period.hours
    solar_markers = _solar_markers(rows, period)
    fan_panels = [
        ("Main thermostat demand", _demand_series(rows, period, "frst_demand_level"), (0, 3), COLORS["blue"]),
        ("Apartment thermostat demand", _demand_series(rows, period, "apt_demand_level"), (0, 3), COLORS["orange"]),
        ("Actual fan speed", _series(rows, period, "fan_actual_speed"), (0, 10), COLORS["teal"]),
    ]
    temp_series = [
        ("Outdoor", _series(rows, period, "oat_calibrated_boiler_f"), COLORS["blue"]),
        ("Common supply", _series(rows, period, "therm_supply_f"), COLORS["orange"]),
    ]
    temp_values = [y for _, points, _ in temp_series for _, y in points]
    temp_min = min(temp_values, default=0.0); temp_max = max(temp_values, default=100.0)
    temp_min = min(-10.0, temp_min - 3); temp_max = max(80.0, temp_max + 3)
    delta_values = [
        value for field in ("therm_1st_delta_from_supply_f", "therm_apt_delta_from_supply_f")
        for _, value in _series(rows, period, field)
    ]
    delta_min = min(-6.0, min(delta_values, default=-6.0) - 1.0)
    delta_max = max(6.0, max(delta_values, default=6.0) + 1.0)
    main_zone_series = [
        ("Main supply delta", _series(rows, period, "therm_1st_delta_from_supply_f"), COLORS["blue"]),
    ]
    apartment_zone_series = [
        ("Apartment supply delta", _series(rows, period, "therm_apt_delta_from_supply_f"), COLORS["orange"]),
    ]
    main_idle_open, main_active_open = _damper_state_intervals(
        rows, period, "FRST_DMP_CLOSE", "frst_air_allowed"
    )
    apartment_idle_open, apartment_active_open = _damper_state_intervals(
        rows, period, "APT_DMP_CLOSE", "apt_air_allowed"
    )
    for obsolete in ("zone_delivery.svg", "zone_delivery.tex"):
        obsolete_path = chart_dir / obsolete
        if obsolete_path.exists():
            obsolete_path.unlink()
    svg_stacked_chart(chart_dir / "fan.svg", "Thermostat demands and actual fan response", fan_panels, (0, hours), markers=solar_markers)
    svg_line_chart(chart_dir / "temperatures.svg", "Outdoor and supply temperatures", temp_series, (0, hours), (temp_min, temp_max), "Degrees F", markers=solar_markers)
    svg_line_chart(chart_dir / "main_zone_delivery.svg", "Main-floor supply delta and damper state", main_zone_series, (0, hours), (delta_min, delta_max), "Delta F", band_layers=[
        (main_idle_open, COLORS["gray"], 0.10, "Open, no zone request"),
        (main_active_open, COLORS["teal"], 0.18, "Open with main airflow request"),
    ], markers=solar_markers)
    svg_line_chart(chart_dir / "apartment_zone_delivery.svg", "Apartment supply delta and damper state", apartment_zone_series, (0, hours), (delta_min, delta_max), "Delta F", band_layers=[
        (apartment_idle_open, COLORS["gray"], 0.10, "Open, no zone request"),
        (apartment_active_open, COLORS["red"], 0.18, "Open with apartment airflow request"),
    ], markers=solar_markers)
    if include_pgf:
        pgf_stacked_chart(chart_dir / "fan.tex", "Thermostat demands and actual fan response", fan_panels, (0, hours), markers=solar_markers)
        pgf_line_chart(chart_dir / "temperatures.tex", "Outdoor and supply temperatures", temp_series, (0, hours), (temp_min, temp_max), "Degrees F", markers=solar_markers)
        pgf_line_chart(chart_dir / "main_zone_delivery.tex", "Main-floor supply delta and damper state", main_zone_series, (0, hours), (delta_min, delta_max), "Delta F", "0.22", band_layers=[
            (main_idle_open, "ReportGray", 0.10),
            (main_active_open, "ReportTeal", 0.18),
        ], markers=solar_markers)
        pgf_line_chart(chart_dir / "apartment_zone_delivery.tex", "Apartment supply delta and damper state", apartment_zone_series, (0, hours), (delta_min, delta_max), "Delta F", "0.22", band_layers=[
            (apartment_idle_open, "ReportGray", 0.10),
            (apartment_active_open, "ReportRed", 0.18),
        ], markers=solar_markers)
