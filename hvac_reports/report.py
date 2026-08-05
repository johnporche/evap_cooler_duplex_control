from pathlib import Path
from .charts import generate_charts
from .latex import compile_pdf, write_latex
from .metrics import analyze
from .reader import read_rows
from .text import write_text_report
from .html import report_directory, write_html_report


def build_report(log_paths, period, config, output_root, formats=("source", "text", "html"), ascii_only=False):
    output_dir = Path(output_root) / period.kind / period.start.strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_rows(log_paths, period)
    metrics = analyze(rows, period, config)
    tex_path = None
    pdf_path = None
    text_path = None
    html_path = None
    if "source" in formats or "pdf" in formats:
        generate_charts(rows, period, output_dir)
        tex_path = output_dir / "report.tex"
        write_latex(tex_path, config, period, metrics)
    if "pdf" in formats:
        pdf_path = compile_pdf(tex_path)
    if "text" in formats:
        text_path = output_dir / ("report-ascii.txt" if ascii_only else "report.txt")
        write_text_report(text_path, config, period, metrics, rows, ascii_only)
    if "html" in formats:
        if "source" in formats or "pdf" in formats:
            svg_source = output_dir / "charts"
        else:
            html_report_dir = report_directory(Path(output_root) / "html", period)
            generate_charts(rows, period, html_report_dir, include_pgf=False)
            svg_source = html_report_dir / "charts"
        html_path = write_html_report(Path(output_root) / "html", config, period, metrics, svg_source)
    return {"directory": output_dir, "tex": tex_path, "pdf": pdf_path, "text": text_path, "html": html_path, "rows": len(rows), "coverage": metrics.values["coverage"]}
