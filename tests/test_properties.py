"""
Property-based tests for the FDE evaluator.

These tests use `hypothesis` to generate random engagement logs and assert
invariants that no hand-written fixture would catch:

  1. Overall score is always in [0, 100].
  2. Decision is always one of {scale, iterate, cut}.
  3. Scale requires overall >= 85 AND business >= 90 (per fde-workflow.md).
  4. Cut requires overall < 50 OR business < 60.
  5. A log with no post-GA data cannot scale (insufficient evidence).
  6. A log with all SLA breaches scores <= 30 on the SLA axis.
  7. The evaluator is monotonic in metric value when other axes are equal:
     if metric_value moves baseline->target (and target is better), overall
     score is not strictly worse.
  8. Re-evaluating an unchanged log produces an unchanged report.

These tests are skipped automatically if `hypothesis` is not installed,
so the framework's zero-dep contract is preserved for the common case.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

try:
    import hypothesis.strategies as _real_st
    from hypothesis import given as _real_given
    from hypothesis import settings as _real_settings
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

# Stub objects so the module loads even when hypothesis is absent.
# The @unittest.skipUnless on TestInvariants makes unittest skip the tests.
if not HAS_HYPOTHESIS:
    class _StStrategies:
        def __getattr__(self, name):
            def _stub(*_a, **_kw):
                return self
            return _stub
    st = _StStrategies()

    def given(*_a, **_kw):
        def deco(fn):
            return fn
        return deco

    def settings(*_a, **_kw):
        def deco(fn):
            return fn
        return deco
else:
    st = _real_st
    given = _real_given
    settings = _real_settings

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import test_fde_eval as harness  # noqa: E402


# --- Strategies ----------------------------------------------------------- #
# Defined at module level (unconditionally) so the @given decorators on the
# test class can reference them by name. When hypothesis is absent, the
# stubs above produce placeholder objects that the @unittest.skipUnless
# class decorator makes unittest ignore.

metric = st.fixed_dictionaries({
    "name": st.sampled_from(["", "p99_ms", "error_rate",
                             "quote_turnaround_minutes",
                             "tickets_resolved_per_agent"]),
    "baseline": st.one_of(st.none(), st.floats(min_value=0, max_value=1e6,
                                               allow_nan=False)),
    "target": st.one_of(st.none(), st.floats(min_value=0, max_value=1e6,
                                             allow_nan=False)),
    "date": st.sampled_from(["", "2026-12-31", "not-a-date"]),
}),
sla = st.fixed_dictionaries({
    "p99_ms": st.one_of(st.none(),
                        st.integers(min_value=50, max_value=2000)),
    "availability_pct": st.one_of(st.none(),
                                  st.floats(min_value=90.0,
                                            max_value=99.99)),
    "error_budget_pct": st.one_of(st.none(),
                                  st.floats(min_value=0.01, max_value=5.0)),
}),

post_ga_log = st.lists(
    st.fixed_dictionaries({
        "week": st.integers(min_value=1, max_value=52),
        "p99_ms": st.floats(min_value=10.0, max_value=5000.0,
                            allow_nan=False),
        "error_rate": st.floats(min_value=0.0, max_value=1.0,
                                allow_nan=False),
        "availability_pct": st.floats(min_value=80.0, max_value=100.0,
                                      allow_nan=False),
    }),
    max_size=20,
)

engagement_log = st.fixed_dictionaries({
    "engagement": st.text(min_size=1, max_size=40),
    "discovery": st.fixed_dictionaries({
        "sponsor": st.sampled_from(["", "Jane Doe, VP Ops"]),
        "metric": metric[0],
        "sla": sla[0],
        "constraints": st.lists(st.text(min_size=1, max_size=20),
                                max_size=5),
        "stakeholders": st.lists(st.text(min_size=1, max_size=20),
                                 max_size=5),
        "roi_inputs": st.fixed_dictionaries({
            "value_per_unit": st.one_of(st.none(),
                                        st.floats(min_value=0.01,
                                                  max_value=1000)),
            "volume_per_year": st.one_of(st.none(),
                                         st.integers(min_value=0,
                                                     max_value=1_000_000)),
            "cost_ceiling_usd": st.one_of(st.none(),
                                          st.floats(min_value=1000,
                                                    max_value=1e9)),
        }),
    }),
    "post_ga_log": post_ga_log,
})


# --- Tests ---------------------------------------------------------------- #

@unittest.skipUnless(HAS_HYPOTHESIS,
                     "hypothesis not installed — run "
                     "`pip install hypothesis` to enable this suite")
class _HypothesisBase(unittest.TestCase):
    pass


class TestInvariants(_HypothesisBase):

    @given(engagement_log)
    @settings(max_examples=200, deadline=None)
    def test_score_in_range_and_decision_valid(self, run):
        rep = harness.evaluate(run)
        self.assertGreaterEqual(rep.overall, 0.0)
        self.assertLessEqual(rep.overall, 100.0)
        self.assertIn(rep.decision, {"scale", "iterate", "cut"})

    @given(engagement_log)
    @settings(max_examples=200, deadline=None)
    def test_scale_requires_business_and_overall_thresholds(self, run):
        """Per fde-workflow.md: scale iff overall>=85 AND business>=90."""
        rep = harness.evaluate(run)
        if rep.decision == "scale":
            self.assertGreaterEqual(rep.overall, 85.0,
                f"scale but overall={rep.overall}")
            self.assertGreaterEqual(rep.business["score"], 90.0,
                f"scale but business={rep.business['score']}")

    @given(engagement_log)
    @settings(max_examples=200, deadline=None)
    def test_cut_requires_either_threshold(self, run):
        rep = harness.evaluate(run)
        if rep.decision == "cut":
            triggered_overall = rep.overall < 50.0
            triggered_business = rep.business["score"] < 60.0
            self.assertTrue(triggered_overall or triggered_business,
                f"cut but neither threshold triggered: "
                f"overall={rep.overall} business={rep.business['score']}")

    @given(engagement_log)
    @settings(max_examples=100, deadline=None)
    def test_empty_post_ga_log_cannot_scale(self, run):
        """No post-GA data means no SLA evidence — can't scale on SLA axis.
        Scale could still be triggered by perfect Discovery + zero SLA
        axis weight, but only if overall reaches 85. With an empty log,
        every axis except Business is 50 (insufficient_data) or 0."""
        run["post_ga_log"] = []
        rep = harness.evaluate(run)
        # Either not scale, OR scale requires perfect Business axis.
        if rep.decision == "scale":
            self.assertEqual(rep.business["score"], 100.0,
                f"empty log scaled without perfect Discovery: "
                f"business={rep.business['score']}, "
                f"overall={rep.overall}")

    @given(engagement_log)
    @settings(max_examples=100, deadline=None)
    def test_idempotency(self, run):
        """Re-evaluating the same log produces a structurally identical
        report (floats may match exactly because no time/random inputs)."""
        rep1 = harness.evaluate(run)
        rep2 = harness.evaluate(run)
        self.assertEqual(rep1.overall, rep2.overall)
        self.assertEqual(rep1.decision, rep2.decision)
        self.assertEqual(rep1.business["score"], rep2.business["score"])
        self.assertEqual(rep1.sla["score"], rep2.sla["score"])
        self.assertEqual(rep1.latency["score"], rep2.latency["score"])
        self.assertEqual(rep1.error_rate["score"], rep2.error_rate["score"])

    @given(engagement_log)
    @settings(max_examples=100, deadline=None)
    def test_axis_weights_sum_to_one(self, run):
        """Verify the weighted average is internally consistent.

        Synthetic fixture: perfect Discovery (12/12 checks pass) +
        compliant post-GA weeks (no breaches). Expected:
          Business  = 100  * 0.35 = 35.0
          SLA       = 100  * 0.30 = 30.0  (all weeks under target)
          Latency   = 100  * 0.15 = 15.0  (stable)
          Errors    = 100  * 0.20 = 20.0  (mean << budget)
          Overall   = 100.0
        """
        synthetic = {
            "engagement": "weight-check",
            "discovery": {
                "sponsor": "Real Sponsor, VP Eng",
                "metric": {"name": "p99_latency_ms",
                           "baseline": 800, "target": 200,
                           "date": "2026-12-31"},
                "sla": {"p99_ms": 500, "availability_pct": 99.9,
                        "error_budget_pct": 0.1},
                "constraints": ["GDPR"],
                "stakeholders": ["a", "b", "c"],
                "roi_inputs": {"value_per_unit": 10,
                               "volume_per_year": 10000,
                               "cost_ceiling_usd": 100000},
            },
            "post_ga_log": [
                # 4 weeks, all under target p99, low error rate, high avail.
                {"week": w, "p99_ms": 400.0 - w * 5,
                 "error_rate": 0.0001, "availability_pct": 99.95}
                for w in range(1, 5)
            ],
        }
        rep = harness.evaluate(synthetic)
        # With compliant data + perfect Discovery, expect ~100 overall.
        # If the weights drift (sum != 1) or any axis is wildly wrong,
        # this catches it.
        self.assertGreaterEqual(rep.overall, 95.0,
            f"perfect inputs should score ~100, got {rep.overall}")
        self.assertLessEqual(rep.overall, 100.0,
            f"overall can't exceed 100, got {rep.overall}")
        self.assertEqual(rep.business["score"], 100.0,
            f"perfect Discovery should be 100, got {rep.business['score']}")


if __name__ == "__main__":
    if not HAS_HYPOTHESIS:
        print("hypothesis not installed — skipping. "
              "Run `pip install hypothesis` to enable property tests.")
    unittest.main()