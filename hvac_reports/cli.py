import argparse
from datetime import date
from pathlib import Path
from .config import ReportConfig
from .periods import report_period
from .report import build_report
from .reader import discover_log_paths


def parser():
    p = argparse.ArgumentParser(description="Generate solar-day HVAC performance reports")
    p.add_argument("kind", choices=("daily", "weekly", "season", "annual"))
    p.add_argument("--date", default=date.today().isoformat(), help="Anchor date, YYYY-MM-DD")
    p.add_argument("--log", action="append", help="CSV or CSV.gz state log; repeat for rotated logs")
    p.add_argument("--log-dir", help="Discover active and archived state logs recursively")
    p.add_argument("--output", default="reports", help="Report output root")
    p.add_argument("--config", help="Optional public-safe JSON configuration")
    p.add_argument(
        "--format",
        choices=("text", "source", "html", "bundle", "pdf", "all", "both"),
        default="bundle",
        help="text; source (LaTeX/SVG); html; bundle (all three, default); pdf; or all",
    )
    p.add_argument("--ascii", action="store_true", help="Use strict ASCII instead of Unicode text graphics")
    p.add_argument("--no-pdf", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if not args.log and not args.log_dir:
        parser().error("provide at least one --log or --log-dir")
    config = ReportConfig.load(args.config)
    period = report_period(args.kind, date.fromisoformat(args.date), config)
    selected = "bundle" if args.no_pdf else args.format
    format_map = {
        "text": ("text",),
        "source": ("source",),
        "html": ("html",),
        "bundle": ("source", "text", "html"),
        "pdf": ("pdf",),
        "all": ("pdf", "text", "html"),
        "both": ("pdf", "text", "html"),
    }
    formats = format_map[selected]
    log_paths = [Path(p) for p in (args.log or [])]
    if args.log_dir:
        log_paths.extend(discover_log_paths(args.log_dir))
    log_paths = sorted(set(path.resolve() for path in log_paths))
    result = build_report(log_paths, period, config, args.output, formats, args.ascii)
    print(f"Report directory: {result['directory']}")
    print(f"Rows: {result['rows']}; coverage: {result['coverage']:.1%}")
    if result["pdf"]:
        print(f"PDF: {result['pdf']}")
    if result["text"]:
        print(f"Text: {result['text']}")
    if result["tex"] and not result["pdf"]:
        print(f"LaTeX source: {result['tex']}")
    if result["html"]:
        print(f"HTML: {result['html']}")
    return 0
