"""
fde — CLI wrapper around the FDE evaluation harness.

Zero dependencies (stdlib only). Uses the same `evaluate()` function the
pytest assertions in test_fde_eval.py exercise, so the scoring cannot drift
between the CLI and the tests.

Subcommands
-----------
  score <log.json>            Score an engagement log, print a scorecard.
                              --json   emit machine-readable JSON instead.
                              --strict exit non-zero on `cut` decision.
  init <customer> [--date D]  Scaffold engagements/<customer>-<date>.md
                              from the discovery template. Pre-fills date,
                              filenames; leaves the business questions blank
                              because those need a real interview.
  log-week <log.json>         Append one week of measurements to a log.
                              Prompts for p99_ms, error_rate, availability,
                              metric_value. Creates the file with an empty
                              skeleton if it doesn't exist.
  watch <log.json>            Tail a log file; re-score on every change and
                              print the scorecard. Bounded by --max N
                              re-evaluations; --once for single-shot (CI).
  import <source> <input> <output>
                              Convert a monitoring export into an engagement
                              log. <source> is one of: prometheus, datadog,
                              csv. Use --engagement NAME to set the
                              engagement id. Discovery fields are left
                              blank — humans fill those in, not importers.

Run `python -m fde <subcommand> --help` for full options.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Import the evaluator from the harness. We deliberately reuse its
# `evaluate()` rather than reimplementing scoring — the CLI cannot drift
# from what the tests assert.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "tests"))
import test_fde_eval as _harness  # noqa: E402


# --------------------------------------------------------------------------- #
# Shared formatters
# --------------------------------------------------------------------------- #

VERDICT_GLYPH = {"scale": "✓ SCALE ", "iterate": "↻ ITERATE", "cut": "✗ CUT   "}


def _format_scorecard(rep, as_json: bool = False) -> str:
    if as_json:
        payload = {
            "engagement": rep.engagement,
            "overall": rep.overall,
            "decision": rep.decision,
            "axes": {
                "business": rep.business,
                "sla": rep.sla,
                "latency": rep.latency,
                "error_rate": rep.error_rate,
            },
            "reasons": rep.reasons,
        }
        return json.dumps(payload, indent=2, default=str)

    axes = [
        ("Business", rep.business.get("score", 0), "discovery & ROI"),
        ("SLA     ", rep.sla.get("score", 0),
         f"{rep.sla.get('breaches', {}).get('p99', 0)} p99 / "
         f"{rep.sla.get('breaches', {}).get('error_rate', 0)} err / "
         f"{rep.sla.get('breaches', {}).get('availability', 0)} avail breaches"),
        ("Latency ", rep.latency.get("score", 0),
         f"{rep.latency.get('trend', '?')} "
         f"(ratio {rep.latency.get('ratio_second_to_first', '?')})"),
        ("Errors  ", rep.error_rate.get("score", 0),
         f"mean {rep.error_rate.get('mean_error_rate', '?')} "
         f"vs budget {rep.error_rate.get('budget', '?')}"),
    ]
    lines = [
        f"{VERDICT_GLYPH.get(rep.decision, rep.decision)}  "
        f"{rep.engagement}  →  overall {rep.overall:.1f} / 100",
        "",
    ]
    for label, score, detail in axes:
        bar_len = int(round(score / 5))  # 0-20 chars
        bar = "█" * bar_len + "·" * (20 - bar_len)
        lines.append(f"  {label}  {score:6.1f}  [{bar}]  {detail}")
    if rep.reasons:
        lines.append("")
        lines.append("  Notes:")
        for r in rep.reasons:
            lines.append(f"    - {r}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# score
# --------------------------------------------------------------------------- #

def cmd_score(args: argparse.Namespace) -> int:
    path = Path(args.log)
    if not path.is_file():
        print(f"error: log file not found: {path}", file=sys.stderr)
        return 2
    try:
        run = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"error: {path} is not valid JSON: {e}", file=sys.stderr)
        return 2
    rep = _harness.evaluate(run)
    print(_format_scorecard(rep, as_json=args.json))
    if args.strict and rep.decision == "cut":
        return 1
    return 0


# --------------------------------------------------------------------------- #
# init — scaffold a fresh engagement markdown
# --------------------------------------------------------------------------- #

DISCOVERY_HEADER = """\
# Engagement: {customer}, {date}

> Scaffolded by `fde init`. Fill in every row. Items left as `TBD` are
> blockers — Discovery is not complete until the sponsor signs off.

## 0. Engagement metadata

| Field                  | Value |
|------------------------|-------|
| Customer               | {customer} |
| Engagement codename    | TBD   |
| Sponsor                | TBD   |
| Daily technical contact| TBD   |
| Security reviewer      | TBD   |
| Legal/procurement      | TBD   |
| Discovery start        | {date} |
| Target GA              | TBD   |

## 1. Business metric (M)

- **Metric name:** TBD
- **How measured today:** TBD (dashboard URL / report / SQL)
- **Owner inside customer org:** TBD
- **Baseline:** TBD
- **Target at GA:** TBD
- **Target date:** TBD
- **What moves M outside our work?** TBD

## 2. SLA targets

| Surface | p50 | p95 | p99 | Availability | Error budget |
|---------|-----|-----|-----|--------------|--------------|
| (TBD)   |     |     |     |              |              |

- **Where measured:** TBD
- **Breach consequence:** TBD
- **Burst / seasonality:** TBD
- **Quiet hours:** TBD

## 3. Constraints

- Data residency: TBD
- Compliance regime: TBD
- Vendor allow / block list: TBD
- Tech stack: TBD
- Budget ceiling: TBD
- Fixed launch date: TBD
- Procurement timeline: TBD

## 4. Stakeholders & cadence

| Role | Name | Channel | Cadence |
|------|------|---------|---------|
| Sponsor |    |       | Daily status, weekly demo |
| Daily  |    |       | Pair, blockers ≤ 1 BD |
| Security |  |       | Pre-arch + pre-deploy review |
| Legal  |    |       | Contract changes |
| End user |  |       | Research, beta, feedback |

## 5. ROI inputs (sourced)

- Value per unit of M: TBD  (who told us: …)
- Volume per year: TBD       (source: …)
- Cost ceiling: TBD          (USD)

## 6. Open questions

- [ ] … (owner: …, due: …)

## 7. Sign-off

- [ ] Sponsor agrees M, baseline, target, date
- [ ] Sponsor agrees SLA envelope
- [ ] FDE lead agrees constraints complete
- [ ] Both sides agree ROI inputs

Signed: ________________________  Date: ____________

---

## Architecture (link to solution brief)

TBD

## Build (ship log)

- {date}: scaffolded engagement file via `fde init`

## ROI evaluation

TBD (use `fde log-week` to append measurements, then `fde score`)
"""


def cmd_init(args: argparse.Namespace) -> int:
    today = args.date or date.today().isoformat()
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.customer}-{today}.md"
    if out_path.exists() and not args.force:
        print(f"error: {out_path} exists; pass --force to overwrite",
              file=sys.stderr)
        return 2
    out_path.write_text(DISCOVERY_HEADER.format(
        customer=args.customer, date=today))
    print(f"wrote {out_path}")
    # Also drop a starter JSON log next to it so `fde score` works immediately.
    # The JSON `engagement` field is set to the customer codename (matching
    # the markdown's `# Engagement: <name>, <date>` header). The filename
    # stem is the canonical unique key; the engagement id is the human
    # codename and must match the markdown header so the consistency
    # check in tests/test_engagement_consistency.py passes.
    log_path = out_dir / f"{args.customer}-{today}.log.json"
    if not log_path.exists() or args.force:
        log_path.write_text(json.dumps({
            "engagement": args.customer,
            "discovery": {
                "sponsor": "",
                "metric": {"name": "", "baseline": None,
                           "target": None, "date": ""},
                "sla": {},
                "constraints": [],
                "stakeholders": [],
                "roi_inputs": {},
            },
            "post_ga_log": [],
        }, indent=2))
        print(f"wrote {log_path}")
    return 0


# --------------------------------------------------------------------------- #
# log-week — append one week of measurements
# --------------------------------------------------------------------------- #

def _prompt(label: str, cast=float, default=None) -> Any:
    raw = input(f"  {label}" + (f" [{default}]" if default is not None else "")
                + ": ").strip()
    if not raw and default is not None:
        return default
    return cast(raw)


def cmd_log_week(args: argparse.Namespace) -> int:
    path = Path(args.log)
    if path.exists():
        run = json.loads(path.read_text())
    else:
        # Auto-scaffold an empty log mirroring `init`. Discovery fields stay
        # empty; the user fills them with `fde init` separately.
        run = {
            "engagement": path.stem.replace(".log", ""),
            "discovery": {
                "sponsor": "", "metric": {}, "sla": {},
                "constraints": [], "stakeholders": [], "roi_inputs": {},
            },
            "post_ga_log": [],
        }
    existing_weeks = {w.get("week") for w in run.get("post_ga_log", [])}
    next_week = (max(existing_weeks) + 1) if existing_weeks and \
        all(isinstance(w, int) for w in existing_weeks) else 1

    print(f"Appending week {next_week} to {path} (Ctrl-C to abort):")
    entry = {
        "week": next_week,
        "p99_ms": _prompt("p99 latency (ms)", float),
        "error_rate": _prompt("error rate (0-1)", float),
        "availability_pct": _prompt("availability (%)", float),
        "metric_value": _prompt("metric value", float, default=None),
    }
    run.setdefault("post_ga_log", []).append(entry)
    path.write_text(json.dumps(run, indent=2))
    print(f"appended week {next_week}; re-scoring…")
    rep = _harness.evaluate(run)
    print(_format_scorecard(rep))
    return 0


# --------------------------------------------------------------------------- #
# import — convert monitoring exports into engagement logs
# --------------------------------------------------------------------------- #

def cmd_import(args: argparse.Namespace) -> int:
    """Convert a monitoring export into an engagement log.

    Discovery fields are NOT filled by importers — they require a human
    interview. The importer writes a skeleton with blank discovery fields
    and a non-empty post_ga_log, ready for the user to fill in sponsor,
    metric M, baseline, target, SLA via `fde log-week` or by editing JSON.
    """
    from fde.importers import IMPORTERS  # local import to keep CLI fast
    if args.source not in IMPORTERS:
        print(f"error: unknown source {args.source!r}; "
              f"choose one of: {sorted(IMPORTERS)}", file=sys.stderr)
        return 2
    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.is_file():
        print(f"error: input not found: {in_path}", file=sys.stderr)
        return 2
    try:
        summary = IMPORTERS[args.source](in_path, out_path,
                                          engagement=args.engagement)
    except json.JSONDecodeError as e:
        print(f"error: input is not valid JSON: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    weeks = summary.get("weeks", 0)
    metrics = summary.get("metrics", [])
    print(f"imported {weeks} weeks from {args.source} -> {out_path}")
    if metrics:
        print(f"  metrics found: {', '.join(metrics)}")
    print(f"\nNext: fill in the Discovery fields in {out_path} (sponsor, "
          f"metric M, baseline, target, SLA), then:")
    print(f"  python -m fde score {out_path}")
    return 0


# --------------------------------------------------------------------------- #
# watch — tail a log file, re-score on every change
# --------------------------------------------------------------------------- #

def _read_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def cmd_watch(args: argparse.Namespace) -> int:
    path = Path(args.log)
    if not path.exists() and not args.once:
        print(f"waiting for {path} to appear…", file=sys.stderr)
    polls = 0
    last_mtime = 0.0
    last_rep_id = None
    while True:
        mtime = _read_mtime(path)
        if mtime and mtime != last_mtime:
            last_mtime = mtime
            try:
                run = json.loads(path.read_text())
            except json.JSONDecodeError:
                # File mid-write; skip this tick.
                time.sleep(args.interval)
                polls += 1
                if args.max and polls >= args.max:
                    return 0
                continue
            rep = _harness.evaluate(run)
            # Only redraw when something material changes (avoid log spam).
            rep_id = (rep.overall, rep.decision,
                      rep.sla.get("breaches"),
                      rep.error_rate.get("mean_error_rate"))
            if rep_id != last_rep_id:
                ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                print(f"\n[{ts} UTC] {path} changed →")
                print(_format_scorecard(rep))
                last_rep_id = rep_id
        if args.once:
            return 0
        polls += 1
        if args.max and polls >= args.max:
            print(f"\n(--max {args.max} reached, exiting)", file=sys.stderr)
            return 0
        time.sleep(args.interval)


# --------------------------------------------------------------------------- #
# Argument parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fde",
        description="CLI wrapper around the FDE evaluation harness. "
                    "Subcommands: score, init, log-week, watch.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # score
    s = sub.add_parser("score", help="Score an engagement log.")
    s.add_argument("log", help="Path to engagement log JSON.")
    s.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON instead of scorecard.")
    s.add_argument("--strict", action="store_true",
                   help="Exit non-zero if decision is `cut`.")
    s.set_defaults(func=cmd_score)

    # init
    i = sub.add_parser("init",
                       help="Scaffold a new engagement file from template.")
    i.add_argument("customer", help="Customer legal name or codename.")
    i.add_argument("--date", help="Engagement date (YYYY-MM-DD). Defaults "
                                  "to today.")
    i.add_argument("--dir", default="engagements",
                   help="Output directory (default: ./engagements).")
    i.add_argument("--force", action="store_true",
                   help="Overwrite existing files.")
    i.set_defaults(func=cmd_init)

    # log-week
    l = sub.add_parser("log-week",
                       help="Append one week of measurements to a log.")
    l.add_argument("log", help="Path to engagement log JSON.")
    l.set_defaults(func=cmd_log_week)

    # watch
    w = sub.add_parser("watch",
                       help="Tail a log file; re-score on every change.")
    w.add_argument("log", help="Path to engagement log JSON.")
    w.add_argument("--interval", type=float, default=1.0,
                   help="Polling interval in seconds (default: 1.0).")
    w.add_argument("--max", type=int, default=0,
                   help="Stop after N polls (0 = forever).")
    w.add_argument("--once", action="store_true",
                   help="Score once and exit (use in CI).")
    w.set_defaults(func=cmd_watch)

    # import
    imp = sub.add_parser("import",
                         help="Convert a monitoring export to an engagement log.")
    imp.add_argument("source", choices=["prometheus", "datadog", "csv"],
                     help="Input format.")
    imp.add_argument("input", help="Path to the monitoring export.")
    imp.add_argument("output", help="Path to write the engagement log JSON.")
    imp.add_argument("--engagement", default=None,
                     help="Engagement id (e.g. 'acme-2026-09-16').")
    imp.set_defaults(func=cmd_import)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())