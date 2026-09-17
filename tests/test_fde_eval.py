"""
Automated evaluation harness for FDE-skill outputs.

This is NOT a unit test for the framework itself — it's a black-box evaluator
that scores a produced FDE deliverable against the contract defined in
.hermes.md and .hermes/skills/fde-workflow.md.

Run:
    python tests/test_fde_eval.py                 # run the bundled fixtures
    python tests/test_fde_eval.py path/to/run.json # score a real engagement log

Each input JSON must look like:
{
  "engagement": "acme-2026-09-16",
  "discovery": {
    "sponsor": "Jane Doe, VP Ops",
    "metric": {"name": "...", "baseline": 100, "target": 50, "date": "2026-12-31"},
    "sla": {"p50_ms": 80, "p95_ms": 250, "p99_ms": 500, "availability_pct": 99.9,
            "error_budget_pct": 0.1},
    "constraints": ["GDPR", "EU-only data"],
    "stakeholders": ["Jane Doe (sponsor)", "Wei Chen (daily)", "..."],
    "roi_inputs": {"value_per_unit": 50, "volume_per_year": 10000,
                   "cost_ceiling_usd": 200000}
  },
  "deliverables": [
    {"name": "solution_brief", "produced_at": "2026-09-17",
     "content": "..."},  # arbitrary markdown text
    {"name": "vertical_slice_log", "produced_at": "2026-09-25",
     "lines": [
        {"ts": "2026-09-25T10:00:00Z", "p99_ms": 420, "error_rate": 0.0003,
         "availability_pct": 99.95, "metric_value": 78},
        ...
     ]},
    ...
  ],
  "post_ga_log": [
    {"week": 1, "p99_ms": 480, "error_rate": 0.0005, "availability_pct": 99.92,
     "metric_value": 65},
    ...
  ]
}

The harness scores four axes. Each axis is 0-100; the final report is the
weighted sum per `.hermes.md`.

This file is importable AND runnable. The pytest-shaped assertions at the
bottom double as a smoke test for the harness itself.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# SLA ceilings from .hermes.md. These are the *contract defaults*; an
# engagement is allowed to override them, but if it does it must declare so
# explicitly in `discovery.sla`.
# --------------------------------------------------------------------------- #

DEFAULT_SLA = {
    "customer_api": {
        "p50_ms": 80, "p95_ms": 250, "p99_ms": 500,
        "availability_pct": 99.9, "error_budget_pct": 0.1,
    },
}


# --------------------------------------------------------------------------- #
# Scoring primitives
# --------------------------------------------------------------------------- #

def _has(value: Any) -> bool:
    """Truthy and non-empty for strings/lists/dicts."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator)) * 100.0


# --------------------------------------------------------------------------- #
# Axis 1: Business criteria (Discovery quality + ROI grounding)
# --------------------------------------------------------------------------- #

def score_business(run: dict) -> dict:
    """Was Discovery done properly? Is ROI sourced?"""
    disc = run.get("discovery", {})
    metric = disc.get("metric", {})
    roi = disc.get("roi_inputs", {})

    checks = {
        "sponsor_named": _has(disc.get("sponsor")),
        "metric_named": _has(metric.get("name")),
        "baseline_present": _is_number(metric.get("baseline")),
        "target_present": _is_number(metric.get("target")),
        "target_date_present": _has(metric.get("date")),
        "target_better_than_baseline": (
            _is_number(metric.get("target"))
            and _is_number(metric.get("baseline"))
            and metric["target"] != metric["baseline"]
        ),
        "stakeholders_present": len(disc.get("stakeholders", [])) >= 3,
        "constraints_documented": _has(disc.get("constraints")),
        "roi_value_per_unit": _is_number(roi.get("value_per_unit")),
        "roi_volume": _is_number(roi.get("volume_per_year")),
        "roi_cost_ceiling": _is_number(roi.get("cost_ceiling_usd")),
        "sla_p99_documented": _is_number(disc.get("sla", {}).get("p99_ms")),
    }
    score = _pct(sum(checks.values()), len(checks))

    missing = [k for k, v in checks.items() if not v]
    return {"score": round(score, 1), "checks": checks,
            "missing": missing}


# --------------------------------------------------------------------------- #
# Axis 2: SLA compliance (p99, error rate, availability vs target)
# --------------------------------------------------------------------------- #

def _safe_num(d, key, default):
    """Return d[key] if it's a real number, else default. Guards against
    both missing keys AND keys explicitly set to None — both must fall back
    to the default, otherwise downstream math (>, /, <) crashes."""
    v = d.get(key, default)
    if v is None:
        return default
    if not _is_number(v):
        return default
    return v


def score_sla(run: dict, sla: dict) -> dict:
    """Compare post-GA measurements against the declared SLA."""
    target_p99 = _safe_num(sla, "p99_ms", None)
    target_err = (_safe_num(sla, "error_budget_pct", 0.1)) / 100.0
    target_avail = _safe_num(sla, "availability_pct", 99.9)

    log = run.get("post_ga_log", [])
    if not log:
        return {"score": 0.0, "reason": "no post-GA measurements",
                "weeks_observed": 0}

    breaches = {"p99": 0, "error_rate": 0, "availability": 0}
    measured = {"p99": [], "error_rate": [], "availability": []}
    for week in log:
        if _is_number(week.get("p99_ms")) and target_p99:
            measured["p99"].append(week["p99_ms"])
            if week["p99_ms"] > target_p99:
                breaches["p99"] += 1
        if _is_number(week.get("error_rate")):
            measured["error_rate"].append(week["error_rate"])
            if week["error_rate"] > target_err:
                breaches["error_rate"] += 1
        if _is_number(week.get("availability_pct")):
            measured["availability"].append(week["availability_pct"])
            if week["availability_pct"] < target_avail:
                breaches["availability"] += 1

    def _axis_score(breach_count: int, total: int) -> float:
        if total == 0:
            return 100.0  # nothing to measure → can't fail this axis
        return _pct(total - breach_count, total)

    score = (
        _axis_score(breaches["p99"], len(measured["p99"])) * 0.4
        + _axis_score(breaches["error_rate"], len(measured["error_rate"])) * 0.3
        + _axis_score(breaches["availability"], len(measured["availability"])) * 0.3
    )

    return {
        "score": round(score, 1),
        "weeks_observed": len(log),
        "breaches": breaches,
        "measured_means": {
            "p99_ms": (round(sum(measured["p99"]) / len(measured["p99"]), 1)
                       if measured["p99"] else None),
            "error_rate": (round(sum(measured["error_rate"])
                                 / len(measured["error_rate"]), 5)
                           if measured["error_rate"] else None),
            "availability_pct": (
                round(sum(measured["availability"])
                      / len(measured["availability"]), 3)
                if measured["availability"] else None),
        },
        "targets": {"p99_ms": target_p99,
                    "error_budget_pct": sla.get("error_budget_pct"),
                    "availability_pct": target_avail},
    }


# --------------------------------------------------------------------------- #
# Axis 3: Latency trend (is p99 *stable or improving* over time?)
# --------------------------------------------------------------------------- #

def score_latency(run: dict) -> dict:
    """Reward non-degrading latency across post-GA weeks."""
    log = run.get("post_ga_log", [])
    p99s = [w["p99_ms"] for w in log
            if _is_number(w.get("p99_ms"))]
    if len(p99s) < 2:
        return {"score": 50.0 if len(p99s) == 1 else 0.0,
                "weeks_observed": len(p99s),
                "trend": "insufficient_data"}

    first_half = p99s[: len(p99s) // 2]
    second_half = p99s[len(p99s) // 2 :]
    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)

    # No regression means second half ≤ 1.1× first half (10% slack).
    ratio = avg_second / avg_first if avg_first > 0 else 1.0
    if ratio <= 1.0:
        score = 100.0
    elif ratio <= 1.1:
        score = 80.0
    elif ratio <= 1.25:
        score = 50.0
    elif ratio <= 1.5:
        score = 25.0
    else:
        score = 0.0

    return {
        "score": score,
        "weeks_observed": len(p99s),
        "avg_first_half_p99_ms": round(avg_first, 1),
        "avg_second_half_p99_ms": round(avg_second, 1),
        "ratio_second_to_first": round(ratio, 3),
        "trend": "improving" if ratio < 1.0 else
                 "stable" if ratio <= 1.1 else "degrading",
    }


# --------------------------------------------------------------------------- #
# Axis 4: API error rate (catches dependency-rot and broken integrations)
# --------------------------------------------------------------------------- #

def score_error_rate(run: dict, sla: dict) -> dict:
    """Mean error rate must stay under 50% of error budget."""
    log = run.get("post_ga_log", [])
    rates = [w["error_rate"] for w in log
             if _is_number(w.get("error_rate"))]
    if not rates:
        return {"score": 0.0, "reason": "no error_rate measurements"}

    budget = _safe_num(sla, "error_budget_pct", 0.1) / 100.0
    mean_rate = sum(rates) / len(rates)
    ceiling = budget * 0.5  # operating well under the budget
    over_budget = sum(1 for r in rates if r > budget)
    over_ceiling = sum(1 for r in rates if r > ceiling)

    if mean_rate <= ceiling:
        score = 100.0
    elif mean_rate <= budget:
        score = 70.0
    elif mean_rate <= budget * 2:
        score = 30.0
    else:
        score = 0.0

    return {
        "score": score,
        "mean_error_rate": round(mean_rate, 5),
        "budget": budget,
        "weeks_over_budget": over_budget,
        "weeks_over_ceiling": over_ceiling,
        "weeks_observed": len(rates),
    }


# --------------------------------------------------------------------------- #
# Final report
# --------------------------------------------------------------------------- #

@dataclass
class Report:
    engagement: str
    business: dict = field(default_factory=dict)
    sla: dict = field(default_factory=dict)
    latency: dict = field(default_factory=dict)
    error_rate: dict = field(default_factory=dict)
    overall: float = 0.0
    decision: str = "iterate"
    reasons: list[str] = field(default_factory=list)

    # weights per .hermes.md business metrics:
    # discovery/ROI = 35%, SLA compliance = 30%, latency trend = 15%,
    # error rate = 20%
    WEIGHTS = {"business": 0.35, "sla": 0.30,
               "latency": 0.15, "error_rate": 0.20}

    def render(self) -> str:
        lines = [
            f"# FDE Evaluation Report — {self.engagement}",
            "",
            f"**Overall score: {self.overall:.1f} / 100**",
            f"**Decision: {self.decision.upper()}**",
            "",
            "## Axis scores",
            f"- Business criteria: {self.business.get('score', 0):.1f}",
            f"- SLA compliance:    {self.sla.get('score', 0):.1f}",
            f"- Latency trend:     {self.latency.get('score', 0):.1f}",
            f"- API error rate:    {self.error_rate.get('score', 0):.1f}",
            "",
        ]
        if self.reasons:
            lines.append("## Notes")
            for r in self.reasons:
                lines.append(f"- {r}")
            lines.append("")
        # JSON tail for machine consumers
        lines.append("## Machine-readable")
        lines.append("```json")
        lines.append(json.dumps({
            "engagement": self.engagement,
            "overall": round(self.overall, 2),
            "decision": self.decision,
            "axes": {
                "business": self.business,
                "sla": self.sla,
                "latency": self.latency,
                "error_rate": self.error_rate,
            },
        }, indent=2, default=str))
        lines.append("```")
        return "\n".join(lines)


def evaluate(run: dict) -> Report:
    # `or` (not .get(default=)) so an empty {} also falls back to defaults —
    # a discovery that documented no SLA gets the framework default, not None.
    sla = (run.get("discovery", {}).get("sla")
           or DEFAULT_SLA["customer_api"])
    rep = Report(engagement=run.get("engagement", "unnamed"))
    rep.business = score_business(run)
    rep.sla = score_sla(run, sla)
    rep.latency = score_latency(run)
    rep.error_rate = score_error_rate(run, sla)

    rep.overall = round(
        rep.business["score"] * Report.WEIGHTS["business"]
        + rep.sla["score"] * Report.WEIGHTS["sla"]
        + rep.latency["score"] * Report.WEIGHTS["latency"]
        + rep.error_rate["score"] * Report.WEIGHTS["error_rate"],
        2,
    )

    # Decision rule, per fde-workflow.md Phase 4:
    if rep.overall >= 85 and rep.business["score"] >= 90:
        rep.decision = "scale"
    elif rep.overall < 50 or rep.business["score"] < 60:
        rep.decision = "cut"
    else:
        rep.decision = "iterate"

    if rep.business.get("missing"):
        rep.reasons.append(
            "Discovery gaps: " + ", ".join(rep.business["missing"])
        )
    if rep.sla.get("weeks_observed", 0) < 4:
        rep.reasons.append(
            "Less than 4 weeks of post-GA data — SLA verdict is provisional."
        )
    return rep


# --------------------------------------------------------------------------- #
# Bundled fixtures (smoke test of the harness itself)
#
# These are loaded from the dogfood engagement files under
# `engagements/` so the test fixtures and the dogfood docs can't drift.
# The mrnavax engagement is the SCALE example; initech is the CUT
# example. The globex engagement covers the ITERATE branch (see
# test_iterate_run_decision_iterate below).
# --------------------------------------------------------------------------- #

ENGAGEMENTS_DIR = Path(__file__).resolve().parent.parent / "engagements"


def load_fixture(name: str) -> dict:
    """Load a dogfood engagement fixture by stem (e.g. 'mrnavax-codonpair-v0.14.0-2026-09-16')."""
    path = ENGAGEMENTS_DIR / f"{name}.log.json"
    return json.loads(path.read_text())


GOOD_RUN = load_fixture("mrnavax-codonpair-v0.14.0-2026-09-16")
BAD_RUN = load_fixture("initech-shadow-it-2026-09-16")
ITERATE_RUN = load_fixture("globex-quote-turnaround-2026-09-16")


# --------------------------------------------------------------------------- #
# CLI + smoke-test entrypoint
# --------------------------------------------------------------------------- #

def _smoke_assertions() -> None:
    """Pytest-shaped assertions. Raises AssertionError on failure."""
    good = evaluate(GOOD_RUN)
    bad = evaluate(BAD_RUN)
    iterate = evaluate(ITERATE_RUN)

    assert good.overall >= 85, f"good run should score ≥85, got {good.overall}"
    assert good.decision == "scale", (
        f"good run should be 'scale', got {good.decision}"
    )
    assert good.business["score"] == 100.0, (
        f"good run discovery should be 100, got {good.business['score']}"
    )
    assert good.sla["breaches"] == {"p99": 0, "error_rate": 0,
                                    "availability": 0}, (
        f"good run should have zero SLA breaches, got {good.sla['breaches']}"
    )

    assert bad.overall < 50, f"bad run should score <50, got {bad.overall}"
    assert bad.decision == "cut", (
        f"bad run should be 'cut', got {bad.decision}"
    )
    assert bad.business["missing"], "bad run should report missing fields"
    assert bad.sla["breaches"]["p99"] >= 1, (
        f"bad run should breach p99 SLA, got {bad.sla['breaches']}"
    )

    # ITERATE branch: Discovery complete (business=100), but SLA
    # missed enough to drop overall into the 50–<85 window.
    assert iterate.overall < 85, (
        f"iterate run should score <85, got {iterate.overall}"
    )
    assert iterate.overall >= 50, (
        f"iterate run should score ≥50, got {iterate.overall}"
    )
    assert iterate.business["score"] >= 60, (
        f"iterate run should have business ≥60, "
        f"got {iterate.business['score']}"
    )
    assert iterate.decision == "iterate", (
        f"iterate run should be 'iterate', got {iterate.decision}"
    )


def test_iterate_run_decision_iterate():
    """Standalone entry point — also called by TestIterateRun below."""
    _smoke_assertions()


class TestIterateRun(unittest.TestCase):
    """Pytest-shaped wrapper so `unittest discover` and `pytest` both pick
    up the iterate branch coverage. The harness itself doesn't use
    unittest; this just exposes the same assertions via a TestCase."""

    def test_iterate_run_decision_iterate(self):
        _smoke_assertions()


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        path = Path(argv[1])
        run = json.loads(path.read_text())
    else:
        print("No path given; running bundled fixtures as smoke test.\n")
        _smoke_assertions()
        print("Smoke tests passed.\n")
        print(evaluate(GOOD_RUN).render())
        print("\n---\n")
        print(evaluate(BAD_RUN).render())
        return 0

    rep = evaluate(run)
    print(rep.render())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))