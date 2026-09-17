"""
Prometheus HTTP API JSON importer.

Tested against Prometheus v1 ``/api/v1/query_range``. The newer v2
endpoints return the same envelope shape but require bearer-token
auth, which the user adds via ``fde import`` flags rather than this
importer.

Known limitations:

* Engagement metadata is left blank — the user fills sponsor / SLA /
  metric target via ``fde log-week`` or by editing the JSON.
* Only metrics whose ``__name__`` starts with ``fde_`` are imported;
  other series in the dump are ignored.
* Duplicate series for the same FDE metric (e.g. multiple label
  combinations) are merged into a single per-week average so the
  result reflects every time series in the dump.

Input shape (what `curl http://prom/api/v1/query_range?query=...` returns):

{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      {
        "metric": {"__name__": "fde_p99_ms", "engagement": "acme"},
        "values": [
          [1714567890, "468.3"],      # [unix_ts, "value_str"]
          [1714574490, "459.7"],
          ...
        ]
      },
      {
        "metric": {"__name__": "fde_error_rate"},
        "values": [[..., "0.0003"], ...]
      },
      ...
    ]
  }
}

We bucket samples into ISO weeks. Output schema matches what
`fde score` expects in `post_ga_log`.

The engagement metadata (engagement name, sponsor, metric M, baseline,
target, SLA) is NOT filled by the importer — it's a human input. The
importer writes `engagement: "<unknown>"` and the user fills it in
via `fde log-week` or by editing the JSON.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Mapping of FDE-prefixed Prometheus metric names to the canonical
# post-GA-log field names. Mirrors ``NAME_MAP`` in datadog.py but
# using Prometheus's underscore convention.
PROM_NAME_MAP = {
    "fde_p99_ms": "p99_ms",
    "fde_error_rate": "error_rate",
    "fde_availability_pct": "availability_pct",
    "fde_metric_value": "metric_value",
}


def _bucket_by_week(samples, *, series_idx, unit):
    """Group [(unix_ts, value_str), ...] into ISO-week buckets.

    Returns {iso_week: [values]}. Raises ValueError naming the
    series/sample on the first malformed input.
    """
    buckets = defaultdict(list)
    for i, sample in enumerate(samples):
        if not isinstance(sample, (list, tuple)) or len(sample) != 2:
            raise ValueError(
                f"sample {i} in series {series_idx}: expected a "
                f"[timestamp, value] pair, got {sample!r}")
        ts_raw, val_raw = sample
        if ts_raw is None:
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp is "
                f"None (expected a {unit} Unix timestamp)")
        try:
            ts = float(ts_raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp "
                f"{ts_raw!r} is not a number")
        if ts < 0:
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp "
                f"{ts} is negative")
        if ts > 253402300799:  # 9999-12-31 23:59:59 UTC in seconds
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp "
                f"{ts} is beyond year 9999 (likely a bad export)")
        if val_raw is None:
            raise ValueError(
                f"sample {i} in series {series_idx}: value is None")
        try:
            val = float(val_raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"sample {i} in series {series_idx}: value "
                f"{val_raw!r} is not a number")
        if val != val or val == float("inf") or val == float("-inf"):
            raise ValueError(
                f"sample {i} in series {series_idx}: value "
                f"{val} is not finite")
        try:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp {ts} "
                f"could not be parsed as a datetime ({exc})") from exc
        iso = dt.isocalendar()
        buckets[(iso[0], iso[1])].append(val)
    return buckets


def import_prometheus(input_path, output_path, **opts):
    raw = json.loads(open(input_path).read())
    if raw.get("status") != "success":
        raise ValueError(
            f"Prometheus query failed: {raw.get('error', 'unknown')}")
    results = raw.get("data", {}).get("result", [])
    if not isinstance(results, list):
        raise ValueError(
            f"Prometheus dump 'data.result' must be a list, got "
            f"{type(results).__name__}")
    if not results:
        raise ValueError(
            "Prometheus dump contained no series (the result array "
            "is empty). Check that your query matched metrics in the "
            "time window.")

    # Group samples by canonical metric name. Only FDE-prefixed
    # metrics count; any other Prometheus series in the dump is
    # ignored. This lets the user mix application metrics
    # (http_requests_total, etc.) with the FDE measurement stream
    # in the same dump.
    FDE_PREFIX = "fde_"
    by_metric = {}
    skipped_empty_series = 0
    for s_idx, series in enumerate(results):
        if not isinstance(series, dict):
            raise ValueError(
                f"series {s_idx} is not an object: {series!r}")
        name = series.get("metric", {}).get("__name__", "unknown")
        if not name.startswith(FDE_PREFIX):
            continue
        if name not in PROM_NAME_MAP:
            # Prefix matches but exact name doesn't — treat as a
            # near-miss typo and skip. We don't have a separate
            # near-miss table for Prometheus; if the user has
            # fde_response_ms they get the same skip silently as
            # non-FDE metrics. Keeping the existing behaviour.
            continue
        samples = series.get("values", [])
        if not isinstance(samples, list):
            raise ValueError(
                f"series {s_idx} ({name!r}): 'values' must be a "
                f"list, got {type(samples).__name__}")
        if not samples:
            skipped_empty_series += 1
            continue
        # Merge with any earlier series for the same metric — duplicate
        # series (different label sets, same metric name) contribute
        # all their samples to the same bucket pool.
        bucketed = _bucket_by_week(samples, series_idx=s_idx, unit="s")
        by_metric.setdefault(name, []).extend(bucketed.items())

    if not by_metric:
        raise ValueError(
            "No FDE-named metrics found in Prometheus dump "
            "(expected fde_p99_ms, fde_error_rate, fde_availability_pct, "
            "fde_metric_value — all must be prefixed with 'fde_')")

    # Bucket each metric by ISO week; the keys tell us the engagement
    # already has a name (e.g. "fde_p99_ms" → p99 axis).
    weeks = {}
    for name, per_series in by_metric.items():
        merged = defaultdict(list)
        for (year, wk), values in per_series:
            merged[(year, wk)].extend(values)
        for (year, wk), values in merged.items():
            entry = weeks.setdefault((year, wk), {"week": wk})
            avg = sum(values) / len(values)
            canonical = PROM_NAME_MAP[name]
            if canonical == "p99_ms":
                entry["p99_ms"] = round(avg, 1)
            elif canonical == "error_rate":
                entry["error_rate"] = avg
            elif canonical == "availability_pct":
                entry["availability_pct"] = round(avg, 3)
            elif canonical == "metric_value":
                entry["metric_value"] = avg

    sorted_weeks = sorted(weeks.values(), key=lambda w: w["week"])

    log = {
        "engagement": opts.get("engagement", "<unknown>"),
        "discovery": {
            "sponsor": "",
            "metric": {"name": "", "baseline": None,
                       "target": None, "date": ""},
            "sla": {},
            "constraints": [],
            "stakeholders": [],
            "roi_inputs": {},
        },
        "post_ga_log": sorted_weeks,
        "_imported_from": f"prometheus:{input_path}",
        "_imported_weeks": len(sorted_weeks),
    }
    output_path.write_text(json.dumps(log, indent=2))
    return {
        "weeks": len(sorted_weeks),
        "metrics": sorted(by_metric.keys()),
        "skipped_empty_series": skipped_empty_series,
    }


if __name__ == "__main__":
    # CLI: python -m fde.importers.prometheus INPUT OUTPUT [--engagement X]
    if len(sys.argv) < 3:
        print("usage: prometheus INPUT OUTPUT [--engagement NAME]",
              file=sys.stderr)
        sys.exit(2)
    in_path, out_path = sys.argv[1], Path(sys.argv[2])
    engagement = None
    if "--engagement" in sys.argv:
        i = sys.argv.index("--engagement")
        engagement = sys.argv[i + 1]
    summary = import_prometheus(Path(in_path), out_path, engagement=engagement)
    print(f"imported {summary['weeks']} weeks from Prometheus")