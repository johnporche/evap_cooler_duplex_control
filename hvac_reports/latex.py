from pathlib import Path
import shutil
import subprocess


def _escape(value):
    text = str(value)
    for source, replacement in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")]:
        text = text.replace(source, replacement)
    return text


def _value(value, digits=1):
    return "--" if value is None else f"{value:.{digits}f}"


def write_latex(path, config, period, metrics):
    v = metrics.values
    state_rows = "\n".join(f"{_escape(key)} & {hours:.2f} \\\\" for key, hours in metrics.state_hours.items()) or r"No observed state data & 0.00 \\"
    daily_rows = "\n".join(f"{row['date']} & {row['observed_hours']:.2f} & {row['cooling_hours']:.2f} & {row['vent_hours']:.2f} \\\\" for row in metrics.daily_rows) or r"No observed days & 0 & 0 & 0 \\"
    status = "COMPLETE" if v["coverage"] >= 0.98 else "INCOMPLETE DATA"
    color = "ReportTeal" if status == "COMPLETE" else "ReportRed"
    document = rf"""\documentclass[10pt]{{article}}
\usepackage[margin=0.65in]{{geometry}}
\usepackage{{booktabs,tabularx,xcolor,pgfplots,fancyhdr,lastpage}}
\pgfplotsset{{compat=1.18}}
\definecolor{{ReportNavy}}{{HTML}}{{17324D}}
\definecolor{{ReportBlue}}{{HTML}}{{3478B9}}
\definecolor{{ReportTeal}}{{HTML}}{{1B998B}}
\definecolor{{ReportOrange}}{{HTML}}{{F28E2B}}
\definecolor{{ReportRed}}{{HTML}}{{D1495B}}
\definecolor{{ReportGray}}{{HTML}}{{6B7C8F}}
\definecolor{{ReportSolar}}{{HTML}}{{8A6D1D}}
\pagestyle{{fancy}}\fancyhf{{}}
\lhead{{{_escape(config.site_name)}}}\rhead{{{_escape(period.kind.title())} report}}
\cfoot{{Page \thepage\ of \pageref{{LastPage}}}}
\setlength{{\parindent}}{{0pt}}
\begin{{document}}
{{\color{{ReportNavy}}\LARGE\bfseries HVAC System Performance Report}}\\[4pt]
{{\large {_escape(period.label)}}} \hfill {{\color{{{color}}}\bfseries {status}}}\\[6pt]
\small Report window: {_escape(period.start.strftime('%Y-%m-%d %H:%M %Z'))} to {_escape(period.end.strftime('%Y-%m-%d %H:%M %Z'))}\\
Observed: {v['observed_hours']:.2f} of {v['period_hours']:.2f} hours ({v['coverage']:.1%}); {v['rows']:,} samples.\\[10pt]

\begin{{tabularx}}{{\textwidth}}{{XXXX}}
\textbf{{Cooling starts}} & \textbf{{Vent cycles}} & \textbf{{Main calls}} & \textbf{{Apartment calls}}\\
{v['cooling_starts']} & {v['vent_cycles']} & {v['main_calls']} & {v['apartment_calls']}\\[5pt]
\textbf{{Main median call}} & \textbf{{Apartment median call}} & \textbf{{Max OAT}} & \textbf{{Active supply mean}}\\
{v['main_median_call_minutes']:.1f} min & {v['apartment_median_call_minutes']:.1f} min & {_value(v['max_oat_f'])} F & {_value(v['mean_active_supply_f'])} F
\end{{tabularx}}

\vspace{{10pt}}\input{{charts/fan.tex}}\par
\vspace{{8pt}}\input{{charts/temperatures.tex}}\par

\newpage
\input{{charts/main_zone_delivery.tex}}\par
\vspace{{8pt}}\input{{charts/apartment_zone_delivery.tex}}\par
\small White means damper commanded closed; gray means commanded open without that zone requesting airflow; zone color means commanded open with that zone requesting airflow. These are controller commands, not physical blade-position feedback.

\section*{{Operating-state totals}}
\begin{{tabular}}{{lr}}\toprule State & Hours\\\midrule
{state_rows}
\bottomrule\end{{tabular}}
\hfill
\begin{{tabular}}{{lr}}\toprule Diagnostic & Result\\\midrule
Static-pressure input OK & {v['static_pressure_ok_percent'] * 100:.1f}\% of samples\\
ERROR\_IN samples & {v['error_input_samples']}\\
\bottomrule\end{{tabular}}

\section*{{Daily aggregation}}
\begin{{tabular}}{{lrrr}}\toprule Date & Observed h & Cooling h & Vent h\\\midrule
{daily_rows}
\bottomrule\end{{tabular}}

\section*{{Interpretation notes}}
\begin{{itemize}}
\item Durations exclude sample gaps longer than the configured maximum gap.
\item Demand and runtime totals describe controller inputs and outputs, not room temperature or Ecobee setpoints.
\item SVG files beside this PDF contain the same chart data in a text-friendly format suitable for versioning or web display.
\item A report below 98\% coverage is explicitly marked incomplete and should not be used for comparative efficiency conclusions without reviewing missing intervals.
\end{{itemize}}
\end{{document}}
"""
    Path(path).write_text(document, encoding="utf-8")


def compile_pdf(tex_path):
    tex_path = Path(tex_path)
    latexmk = shutil.which("latexmk") or "/Library/TeX/texbin/latexmk"
    result = subprocess.run([latexmk, "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name], cwd=tex_path.parent, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("LaTeX failed:\n" + result.stdout[-4000:] + result.stderr[-1000:])
    return tex_path.with_suffix(".pdf")
