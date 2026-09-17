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
# Doctor — explain WHY an engagement scored what it did
# --------------------------------------------------------------------------- #

# Friendly labels for Discovery checks (matches harness order so the list
# reads top-down in the same order the scorecard was computed).
_BUSINESS_CHECK_LABELS = {
    "sponsor_named":              "sponsor name",
    "metric_named":               "metric M name",
    "baseline_present":           "metric baseline",
    "target_present":             "metric target",
    "target_date_present":        "metric target date",
    "target_better_than_baseline": "metric target differs from baseline",
    "stakeholders_present":       ">=3 stakeholders named",
    "constraints_documented":     "constraints documented",
    "roi_value_per_unit":         "ROI value_per_unit",
    "roi_volume":                 "ROI volume_per_year",
    "roi_cost_ceiling":           "ROI cost_ceiling_usd",
    "sla_p99_documented":         "SLA p99_ms",
}


def _classify_week(week: dict, sla: dict) -> dict:
    """Compare a single week's measurement against the SLA. Mirrors the
    logic in test_fde_eval.score_sla so the doctor can name weeks, not
    just count them."""
    out = {"week": week.get("week")}
    if _harness._is_number(week.get("p99_ms")) and _harness._is_number(
            sla.get("p99_ms")):
        out["p99_breach"] = week["p99_ms"] > sla["p99_ms"]
        out["p99_ms"] = week["p99_ms"]
    if _harness._is_number(week.get("error_rate")) and _harness._is_number(
            sla.get("error_budget_pct")):
        budget = sla["error_budget_pct"] / 100.0
        out["err_breach"] = week["error_rate"] > budget
        out["error_rate"] = week["error_rate"]
    if _harness._is_number(week.get("availability_pct")) and \
            _harness._is_number(sla.get("availability_pct")):
        out["avail_breach"] = week["availability_pct"] < sla["availability_pct"]
        out["availability_pct"] = week["availability_pct"]
    return out


def _explain(run: dict, rep, sla: dict) -> dict:
    """Build a structured explanation of the Report. Returns a dict so
    the same structure can be JSON-emitted."""
    business_missing = rep.business.get("missing", [])
    breaches = rep.sla.get("breaches", {}) or {}
    latency = rep.latency
    errors = rep.error_rate

    # Walk the post-GA log to identify the specific weeks that breached.
    # The harness only counts breaches; doctor names them.
    weekly = [_classify_week(w, sla) for w in run.get("post_ga_log", [])]
    p99_weeks = [w["week"] for w in weekly if w.get("p99_breach")]
    err_weeks = [w["week"] for w in weekly if w.get("err_breach")]
    avail_weeks = [w["week"] for w in weekly if w.get("avail_breach")]
    total_breach_weeks = sorted({
        w for w in (p99_weeks + err_weeks + avail_weeks)
        if w is not None
    })

    return {
        "engagement": rep.engagement,
        "overall": rep.overall,
        "decision": rep.decision,
        "business": {
            "score": rep.business.get("score", 0),
            "missing": business_missing,
            "missing_labels": [_BUSINESS_CHECK_LABELS.get(m, m)
                               for m in business_missing],
            "healthy": not business_missing,
        },
        "sla": {
            "score": rep.sla.get("score", 0),
            "weeks_observed": rep.sla.get("weeks_observed", 0),
            "breaches": breaches,
            "breach_weeks": {
                "p99": p99_weeks,
                "error_rate": err_weeks,
                "availability": avail_weeks,
            },
            "weeks_with_any_breach": total_breach_weeks,
            "targets": rep.sla.get("targets", {}),
            "measured_means": rep.sla.get("measured_means", {}),
            "healthy": (
                breaches.get("p99", 0) == 0
                and breaches.get("error_rate", 0) == 0
                and breaches.get("availability", 0) == 0
                and rep.sla.get("weeks_observed", 0) > 0
            ),
        },
        "latency": {
            "score": latency.get("score", 0),
            "trend": latency.get("trend", "?"),
            "ratio_second_to_first": latency.get("ratio_second_to_first"),
            "avg_first_half_p99_ms": latency.get("avg_first_half_p99_ms"),
            "avg_second_half_p99_ms": latency.get("avg_second_half_p99_ms"),
            "healthy": latency.get("trend") in ("improving", "stable"),
        },
        "errors": {
            "score": errors.get("score", 0),
            "mean_error_rate": errors.get("mean_error_rate"),
            "budget": errors.get("budget"),
            "weeks_over_budget": errors.get("weeks_over_budget", 0),
            "weeks_over_ceiling": errors.get("weeks_over_ceiling", 0),
            "weeks_observed": errors.get("weeks_observed", 0),
            "healthy": (
                errors.get("weeks_over_budget", 0) == 0
                and errors.get("weeks_observed", 0) > 0
            ),
        },
        "reasons": rep.reasons,
    }


def _format_doctor(expl: dict) -> str:
    """Render an explanation dict as human-readable text. Sized to fit a
    typical terminal (~35 lines) so the doctor output doesn't scroll-spam."""
    lines = []
    eng = expl["engagement"]
    overall = expl["overall"]
    decision = expl["decision"]
    glyph = VERDICT_GLYPH.get(decision, decision)

    lines.append(f"{glyph}  {eng}  ->  overall {overall:.1f} / 100")
    lines.append("")

    # --- Discovery ---
    biz = expl["business"]
    if biz["healthy"]:
        lines.append("Discovery: complete (no missing fields).")
        lines.append("  -> next: keep Discovery fresh -- re-check on every "
                     "scope change.")
    else:
        miss = biz["missing_labels"]
        lines.append(f"Discovery: missing {len(miss)} of 12 checks:")
        for label in miss:
            lines.append(f"  - {label}")
        lines.append("  -> next: run `fde log-week` or edit the JSON to fill "
                     "these in before any further ship.")

    # --- SLA ---
    sla = expl["sla"]
    weeks_obs = sla["weeks_observed"]
    weeks_label = "week" if weeks_obs == 1 else "weeks"
    b = sla["breaches"]
    total = (b.get("p99", 0) + b.get("error_rate", 0)
             + b.get("availability", 0))
    if weeks_obs == 0:
        lines.append("")
        lines.append("SLA: no post-GA measurements yet (0 weeks observed).")
        lines.append("  -> next: run `fde log-week` weekly after each ship.")
    elif total == 0:
        means = sla.get("measured_means") or {}
        targets = sla.get("targets") or {}
        target_p99 = targets.get("p99_ms")
        mean_p99 = means.get("p99_ms")
        p99_str = (f"p99 mean {mean_p99}ms vs target {target_p99}ms"
                   if mean_p99 is not None and target_p99 is not None
                   else "")
        lines.append("")
        lines.append(f"SLA: 0 breaches across {weeks_obs} {weeks_label}"
                     + (f" ({p99_str})." if p99_str else "."))
        lines.append("  -> next: keep watching; any single breach drops the "
                     "SLA score.")
    else:
        any_weeks = sla["weeks_with_any_breach"]
        week_str = (f" -- weeks {any_weeks}" if any_weeks else "")
        parts = []
        if b.get("p99"):
            parts.append(f"{b['p99']}x p99 "
                         f"(weeks {sla['breach_weeks']['p99']})")
        if b.get("error_rate"):
            parts.append(f"{b['error_rate']}x error_rate "
                         f"(weeks {sla['breach_weeks']['error_rate']})")
        if b.get("availability"):
            parts.append(f"{b['availability']}x availability "
                         f"(weeks {sla['breach_weeks']['availability']})")
        targets = sla.get("targets") or {}
        target_p99 = targets.get("p99_ms")
        means = sla.get("measured_means") or {}
        mean_p99 = means.get("p99_ms")
        p99_str = (f", p99 mean {mean_p99}ms vs target {target_p99}ms"
                   if mean_p99 is not None and target_p99 is not None
                   else "")
        lines.append("")
        lines.append(
            f"SLA: {total} breach{'es' if total != 1 else ''} across "
            f"{weeks_obs} {weeks_label}{week_str} -- "
            f"{'; '.join(parts)}{p99_str}."
        )
        lines.append("  -> next: investigate the named weeks first; a "
                     "single repeat breach can be a flake, a cluster is a "
                     "real regression.")

    # --- Latency ---
    lat = expl["latency"]
    ratio = lat["ratio_second_to_first"]
    ratio_str = (f"{ratio:.3f}" if isinstance(ratio, (int, float))
                 else str(ratio))
    healthy_label = {"improving": "improving", "stable": "stable",
                     "degrading": "DEGRADING",
                     "insufficient_data": "insufficient data"}.get(
        lat["trend"], lat["trend"])
    lines.append("")
    if lat["trend"] == "insufficient_data":
        lines.append("Latency: insufficient data (<2 weeks observed).")
        lines.append("  -> next: keep logging weekly; trend needs >=2 weeks.")
    else:
        lines.append(f"Latency: trending {healthy_label} (ratio "
                     f"second/first = {ratio_str}).")
        if lat["trend"] == "degrading":
            lines.append("  -> next: open a regression ticket -- second-half "
                         "p99 is climbing.")
        else:
            lines.append("  -> next: no action; keep logging.")

    # --- Errors ---
    err = expl["errors"]
    lines.append("")
    err_weeks_obs = err["weeks_observed"]
    err_weeks_label = "week" if err_weeks_obs == 1 else "weeks"
    if err_weeks_obs == 0:
        lines.append("Errors: no error_rate measurements yet.")
        lines.append("  -> next: log error_rate in `fde log-week`.")
    else:
        over = err["weeks_over_budget"]
        over_ceil = err["weeks_over_ceiling"]
        budget = err["budget"]
        mean = err["mean_error_rate"]
        over_str = (f" ({over} week{'s' if over != 1 else ''} over budget"
                    f", {over_ceil} over the 50% ceiling)"
                    if over or over_ceil else "")
        lines.append(f"Errors: mean {mean} vs budget {budget}{over_str} "
                     f"across {err_weeks_obs} {err_weeks_label}.")
        if over:
            lines.append("  -> next: dependency-rot suspect -- check upstream "
                         "APIs and timeouts.")
        else:
            lines.append("  -> next: no action; error rate is within budget.")

    # --- Decision ---
    lines.append("")
    lines.append(f"Decision: {decision.upper()} "
                 f"(overall {overall:.1f}, business {biz['score']:.1f}).")
    if decision == "cut":
        lines.append("  -> next: wind down cleanly, write up lessons, hand "
                     "off what shipped.")
    elif decision == "iterate":
        lines.append("  -> next: pick the lowest-scoring axis and run one "
                     "bounded iteration.")
    else:
        lines.append("  -> next: expand to the next workflow / customer.")

    return "\n".join(lines)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Introspect an engagement log and explain WHY each axis scored what
    it did. Exit codes: 0 healthy, 1 actionable issues, 2 file/JSON
    unreadable."""
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
    # Same SLA fallback the harness uses, so breach math here matches
    # breach counts in the report exactly.
    sla = (run.get("discovery", {}).get("sla")
           or _harness.DEFAULT_SLA["customer_api"])

    expl = _explain(run, rep, sla)
    if args.json:
        print(json.dumps(expl, indent=2, default=str))
    else:
        print(_format_doctor(expl))

    if expl["business"]["healthy"] and expl["sla"]["healthy"] \
            and expl["latency"]["healthy"] and expl["errors"]["healthy"]:
        return 0
    return 1


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


# --------------------------------------------------------------------------- #
# list — index of every engagement under a directory
# --------------------------------------------------------------------------- #

def _safe_relative(path: Path, anchor: Path) -> str:
    """Return str(path) relative to anchor, falling back to the path's
    own string if path is not inside anchor. Without this, listing
    engagement logs outside the repo (e.g. /tmp/...) raises ValueError."""
    try:
        return str(path.resolve().relative_to(anchor.resolve()))
    except ValueError:
        return str(path)


def _score_engagement(log_path: Path) -> dict | None:
    """Score a single engagement log and return a compact summary dict.

    Returns None if the log is malformed (so the caller can skip without
    crashing the whole list). The summary is the minimum info needed
    to render a navigable index table.
    """
    try:
        run = json.loads(log_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    try:
        rep = _harness.evaluate(run)
    except Exception:
        return None
    metric = run.get("discovery", {}).get("metric", {})
    metric_name = metric.get("name") or "?"
    baseline = metric.get("baseline")
    target = metric.get("target")
    weeks = len(run.get("post_ga_log", []))
    return {
        "engagement": run.get("engagement", log_path.stem),
        "file": _safe_relative(log_path, _HERE.parent),
        "sponsor": run.get("discovery", {}).get("sponsor") or "",
        "metric_name": metric_name,
        "baseline": baseline,
        "target": target,
        "weeks": weeks,
        "overall": rep.overall,
        "decision": rep.decision,
    }


def _format_list_table(rows: list[dict]) -> str:
    """Render rows as a fixed-width human-readable table."""
    if not rows:
        return "(no engagement logs found)\n"

    headers = ("Engagement", "Sponsor", "Metric", "Weeks",
               "Overall", "Decision")
    widths = [22, 18, 22, 6, 8, 10]

    def _truncate(s: str, w: int) -> str:
        s = (s or "").strip()
        return s[: w - 1] + "…" if len(s) > w else s

    def _row(name, sponsor, metric, weeks, overall, decision):
        return (
            _truncate(name, widths[0]).ljust(widths[0]),
            _truncate(sponsor, widths[1]).ljust(widths[1]),
            _truncate(metric, widths[2]).ljust(widths[2]),
            str(weeks).rjust(widths[3]),
            f"{overall:6.1f}".rjust(widths[4]),
            decision.ljust(widths[5]),
        )

    lines = []
    sep = "  ".join("-" * w for w in widths)
    lines.append("  ".join(h.ljust(widths[i]) if i not in (3, 4)
                              else h.rjust(widths[i])
                              for i, h in enumerate(headers)))
    lines.append(sep)
    for r in rows:
        cols = _row(r["engagement"], r["sponsor"], r["metric_name"],
                    r["weeks"], r["overall"], r["decision"])
        lines.append("  ".join(cols))
    return "\n".join(lines) + "\n"


def _format_list_markdown(rows: list[dict]) -> str:
    """Render rows as a Markdown table for engagements/INDEX.md."""
    if not rows:
        return "# Engagements index\n\n(no engagement logs found)\n"
    lines = ["# Engagements index\n",
             f"_{len(rows)} engagement{'s' if len(rows) != 1 else ''}._\n",
             "| Engagement | Sponsor | Metric | Weeks | Overall | Decision |",
             "|---|---|---|---:|---:|---|"]
    for r in rows:
        sponsor = r["sponsor"] or "(none)"
        lines.append(
            f"| `{r['engagement']}` | {sponsor} | {r['metric_name']} | "
            f"{r['weeks']} | {r['overall']:.1f} | {r['decision']} |"
        )
    return "\n".join(lines) + "\n"


def cmd_list(args: argparse.Namespace) -> int:
    """Index every engagement under a directory.

    Scans for `*.log.json` files, scores each, and prints a navigable
    table. Outputs go to stdout, errors go to stderr. Exit 0 even when
    the directory is empty (no engagements yet is a valid state).
    """
    target = Path(args.dir)
    if not target.is_dir():
        print(f"error: not a directory: {target}", file=sys.stderr)
        return 2
    logs = sorted(target.glob("*.log.json"))
    rows = []
    for p in logs:
        summary = _score_engagement(p)
        if summary is not None:
            rows.append(summary)
    if args.json:
        print(json.dumps(rows, indent=2))
    elif args.markdown:
        # Markdown output writes the file (and prints nothing extra) so
        # `python -m fde list --markdown > INDEX.md` works as expected.
        md = _format_list_markdown(rows)
        out = Path(args.markdown)
        out.write_text(md)
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(_format_list_table(rows))
    return 0


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
        # empty; the user fills them with `fde init` separately. The
        # `engagement` field is the human codename (matches the markdown
        # header produced by `fde init`); the filename stem may have a
        # date suffix for uniqueness.
        run = {
            "engagement": path.stem.split("-")[0]
                          if re.match(r"^[A-Za-z0-9_-]+$", path.stem)
                          else path.stem,
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
                    "Subcommands: score, init, log-week, watch, doctor.",
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

    # doctor
    d = sub.add_parser(
        "doctor",
        help="Explain WHY each axis scored what it did (missing Discovery "
             "fields, breached weeks, next actions).")
    d.add_argument("log", help="Path to engagement log JSON.")
    d.add_argument("--json", action="store_true",
                   help="Emit machine-readable explanation JSON.")
    d.set_defaults(func=cmd_doctor)

    # list
    ls = sub.add_parser(
        "list",
        help="Index every engagement log under a directory with score, "
             "decision, and one-line summary.")
    ls.add_argument("--dir", default="engagements",
                    help="Directory to scan for *.log.json (default: "
                         "./engagements).")
    ls.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of a table.")
    ls.add_argument("--markdown", metavar="PATH",
                    help="Write a Markdown index to this path (e.g. "
                         "engagements/INDEX.md).")
    ls.set_defaults(func=cmd_list)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())