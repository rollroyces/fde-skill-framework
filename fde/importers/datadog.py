"""
Datadog metrics API JSON importer.

Input shape (what `curl https://api.datadoghq.com/api/v1/query?query=...`
returns):

{
  "series": [
    {
      "metric": "fde.p99_ms",
      "pointlist": [
        [1714567890000, 468.3],         # [unix_ms, value]
        [1714574490000, 459.7],
        ...
      ]
    },
    {
      "metric": "fde.error_rate",
      "pointlist": [...]
    },
    ...
  ]
}

Datadog uses millisecond timestamps (vs Prometheus's seconds) and dot
notation in metric names (vs underscores). We normalize both.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

NAME_MAP = {
    "fde.p99_ms": "p99_ms",
    "fde.error_rate": "error_rate",
    "fde.availability_pct": "availability_pct",
    "fde.metric_value": "metric_value",
}


def _bucket_by_week(samples):
    buckets = defaultdict(list)
    for ts_ms, value in samples:
        dt = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        iso = dt.isocalendar()
        buckets[(iso[0], iso[1])].append(float(value))
    return buckets


def import_datadog(input_path, output_path, **opts):
    raw = json.loads(open(input_path).read())
    series_list = raw.get("series", [])
    if not series_list:
        raise ValueError("Datadog dump contained no series")

    weeks = {}
    matched_metrics = []
    for series in series_list:
        dd_name = series.get("metric", "")
        canonical = NAME_MAP.get(dd_name)
        if not canonical:
            continue  # skip non-FDE metrics silently
        matched_metrics.append(dd_name)
        samples = series.get("pointlist", [])
        for (year, wk), values in _bucket_by_week(samples).items():
            entry = weeks.setdefault((year, wk), {"week": wk})
            avg = sum(values) / len(values)
            entry[canonical] = round(avg, 5)                 if canonical == "error_rate" else round(avg, 1)

    if not weeks:
        raise ValueError(
            f"No FDE metrics found in Datadog dump. Expected one of: "
            f"{sorted(NAME_MAP)}. Got: {[s.get('metric') for s in series_list]}")

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
        "_imported_from": f"datadog:{input_path}",
        "_imported_weeks": len(sorted_weeks),
    }
    output_path.write_text(json.dumps(log, indent=2))
    return {"weeks": len(sorted_weeks),
            "metrics": matched_metrics}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: datadog INPUT OUTPUT [--engagement NAME]",
              file=sys.stderr)
        sys.exit(2)
    in_path, out_path = sys.argv[1], Path(sys.argv[2])
    engagement = None
    if "--engagement" in sys.argv:
        i = sys.argv.index("--engagement")
        engagement = sys.argv[i + 1]
    summary = import_datadog(Path(in_path), out_path, engagement=engagement)
    print(f"imported {summary['weeks']} weeks from Datadog")
