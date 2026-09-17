"""
Prometheus HTTP API JSON importer.

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
from collections import defaultdict
from datetime import datetime, timezone


def _bucket_by_week(samples):
    """Group [(unix_ts, value_str), ...] into ISO-week buckets.
    Returns {iso_week: [values]}."""
    buckets = defaultdict(list)
    for ts, val in samples:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        # ISO week: (year, week_number)
        iso = dt.isocalendar()
        buckets[(iso[0], iso[1])].append(float(val))
    return buckets


def import_prometheus(input_path, output_path, **opts):
    raw = json.loads(open(input_path).read())
    if raw.get("status") != "success":
        raise ValueError(
            f"Prometheus query failed: {raw.get('error', 'unknown')}")
    results = raw.get("data", {}).get("result", [])

    # Group samples by metric name. Only FDE-prefixed metrics count;
    # any other Prometheus series in the dump is ignored. This lets the
    # user mix application metrics (http_requests_total, etc.) with the
    # FDE measurement stream in the same dump.
    FDE_PREFIX = "fde_"
    by_metric = {}
    for series in results:
        name = series.get("metric", {}).get("__name__", "unknown")
        if not name.startswith(FDE_PREFIX):
            continue
        by_metric[name] = series.get("values", [])

    if not by_metric:
        raise ValueError(
            "No FDE-named metrics found in Prometheus dump "
            "(expected fde_p99_ms, fde_error_rate, fde_availability_pct, "
            "fde_metric_value — all must be prefixed with 'fde_')")

    # Bucket each metric by ISO week; the keys tell us the engagement
    # already has a name (e.g. "fde_p99_ms" → p99 axis).
    weeks = {}
    for name, samples in by_metric.items():
        for (year, wk), values in _bucket_by_week(samples).items():
            entry = weeks.setdefault((year, wk), {"week": wk})
            avg = sum(values) / len(values)
            if name == "fde_p99_ms":
                entry["p99_ms"] = round(avg, 1)
            elif name == "fde_error_rate":
                entry["error_rate"] = avg
            elif name == "fde_availability_pct":
                entry["availability_pct"] = round(avg, 3)
            elif name == "fde_metric_value":
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
    return {"weeks": len(sorted_weeks),
            "metrics": sorted(by_metric.keys())}


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
