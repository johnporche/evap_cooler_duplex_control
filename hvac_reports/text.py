from pathlib import Path


UNICODE_LEVELS = "▁▂▃▄▅▆▇█"
ASCII_LEVELS = ".:-=+*#@"


def _value(value, digits=1, suffix=""):
    return "--" if value is None else f"{value:.{digits}f}{suffix}"


def _downsample(values, width):
    if len(values) <= width:
        return values
    result = []
    for column in range(width):
        start = int(column * len(values) / width)
        end = max(start + 1, int((column + 1) * len(values) / width))
        bucket = [value for value in values[start:end] if value is not None]
        result.append(sum(bucket) / len(bucket) if bucket else None)
    return result


def sparkline(values, width=72, minimum=None, maximum=None, ascii_only=False):
    levels = ASCII_LEVELS if ascii_only else UNICODE_LEVELS
    values = _downsample(values, width)
    finite = [value for value in values if value is not None]
    if not finite:
        return "(no data)"
    low = min(finite) if minimum is None else minimum
    high = max(finite) if maximum is None else maximum
    span = high - low or 1.0
    output = []
    for value in values:
        if value is None:
            output.append(" ")
        else:
            index = round((len(levels) - 1) * max(0.0, min(1.0, (value - low) / span)))
            output.append(levels[index])
    return "".join(output)


def bar(value, maximum, width=28, ascii_only=False):
    fraction = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    count = round(width * fraction)
    full = "#" if ascii_only else "█"
    empty = "." if ascii_only else "░"
    return full * count + empty * (width - count)


def _table(headers, rows, ascii_only=False):
    data = [list(map(str, headers))] + [list(map(str, row)) for row in rows]
    widths = [max(len(row[i]) for row in data) for i in range(len(headers))]
    if ascii_only:
        top = "+" + "+".join("-" * (width + 2) for width in widths) + "+"
        middle = top
        bottom = top
        vertical = "|"
    else:
        top = "┌" + "┬".join("─" * (width + 2) for width in widths) + "┐"
        middle = "├" + "┼".join("─" * (width + 2) for width in widths) + "┤"
        bottom = "└" + "┴".join("─" * (width + 2) for width in widths) + "┘"
        vertical = "│"
    lines = [top]
    for index, row in enumerate(data):
        lines.append(vertical + vertical.join(f" {cell:<{widths[i]}} " for i, cell in enumerate(row)) + vertical)
        if index == 0:
            lines.append(middle)
    lines.append(bottom)
    return "\n".join(lines)


def write_text_report(path, config, period, metrics, rows, ascii_only=False):
    v = metrics.values
    rule = "=" * 78
    status = "COMPLETE" if v["coverage"] >= 0.98 else "INCOMPLETE DATA"
    state_max = max(metrics.state_hours.values(), default=1.0)
    state_lines = [
        f"  {state:<10} {bar(hours, state_max, ascii_only=ascii_only)} {hours:7.2f} h"
        for state, hours in metrics.state_hours.items()
    ] or ["  (no observed state data)"]
    fan_target = [row.get("fan_target_speed") for row in rows]
    fan_actual = [row.get("fan_actual_speed") for row in rows]
    outdoor = [row.get("oat_calibrated_boiler_f") for row in rows]
    supply = [row.get("therm_supply_f") for row in rows]
    main_delta = [row.get("therm_1st_delta_from_supply_f") for row in rows]
    apartment_delta = [row.get("therm_apt_delta_from_supply_f") for row in rows]
    main_damper = [0 if row.get("FRST_DMP_CLOSE") else 1 for row in rows]
    apartment_damper = [0 if row.get("APT_DMP_CLOSE") else 1 for row in rows]
    daily = [[item["date"], f"{item['observed_hours']:.2f}", f"{item['cooling_hours']:.2f}", f"{item['vent_hours']:.2f}"] for item in metrics.daily_rows]
    text = f"""{rule}
{config.site_name}
HVAC SYSTEM PERFORMANCE REPORT - {period.kind.upper()}
{period.label}
{rule}
Window    {period.start.strftime('%Y-%m-%d %H:%M %Z')} to {period.end.strftime('%Y-%m-%d %H:%M %Z')}
Coverage  {v['observed_hours']:.2f} / {v['period_hours']:.2f} hours ({v['coverage']:.1%})  [{status}]
Samples   {v['rows']:,}

CALLS AND AIRFLOW
  Cooling starts       {v['cooling_starts']:>7}
  Vent cycles          {v['vent_cycles']:>7}
  Main-floor calls     {v['main_calls']:>7}   median {_value(v['main_median_call_minutes'])} min
  Apartment calls      {v['apartment_calls']:>7}   median {_value(v['apartment_median_call_minutes'])} min
TEMPERATURES
  Mean outdoor         {_value(v['mean_oat_f'])} F
  Maximum outdoor      {_value(v['max_oat_f'])} F
  Active supply mean   {_value(v['mean_active_supply_f'])} F

OPERATING-STATE HOURS
{chr(10).join(state_lines)}

TIME-SERIES OVERVIEW (left = report start, right = report end)
  Fan target  {sparkline(fan_target, minimum=0, maximum=10, ascii_only=ascii_only)}
  Fan actual  {sparkline(fan_actual, minimum=0, maximum=10, ascii_only=ascii_only)}
  Outdoor F   {sparkline(outdoor, ascii_only=ascii_only)}
  Supply F    {sparkline(supply, ascii_only=ascii_only)}
  Main delta  {sparkline(main_delta, ascii_only=ascii_only)}
  Apt delta   {sparkline(apartment_delta, ascii_only=ascii_only)}
  Main damper {sparkline(main_damper, minimum=0, maximum=1, ascii_only=ascii_only)}  (high=open)
  Apt damper  {sparkline(apartment_damper, minimum=0, maximum=1, ascii_only=ascii_only)}  (high=open)

DAILY AGGREGATION
{_table(['Date', 'Observed h', 'Cooling h', 'Vent h'], daily or [['--','0','0','0']], ascii_only)}

DIAGNOSTICS
  Static-pressure input OK   {v['static_pressure_ok_percent']:.1%} of samples
  ERROR_IN active            {v['error_input_samples']} samples

Notes:
  * Durations omit gaps longer than the configured maximum sample gap.
  * No Ecobee, room-temperature, occupancy, or setpoint data is used.
  * Damper traces are commanded states, not measured blade position.
  * Reports below 98% coverage are marked incomplete.
"""
    Path(path).write_text(text, encoding="ascii" if ascii_only else "utf-8")
