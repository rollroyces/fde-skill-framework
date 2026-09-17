"""
Datadog metrics API JSON importer.

Tested against Datadog API v1; if you're using v2 (the newer series
endpoint), the response shape is different and this importer will not
work as-is.

Known limitations:

* Assumes millisecond Unix timestamps in ``pointlist``. Datadog's v1
  query endpoint always returns ms, but the v2 series endpoint may
  return seconds and use a different envelope shape.
* Engagement metadata is left blank — the user fills sponsor / SLA /
  metric target via ``fde log-week`` or by editing the JSON.
* Non-FDE metrics in the response are skipped silently except for
  near-miss names (``fde.p99_latency_ms`` vs ``fde.p99_ms``) which are
  logged as warnings so the user can rename before re-importing.

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

Edge cases we handle:

* Empty ``series`` list — ValueError with clear message.
* Series with empty ``pointlist`` — skipped (not an error).
* Malformed timestamps (negative, None, non-numeric string, far-future
  that overflows ``datetime.fromtimestamp``) — ValueError naming the
  series index and sample index.
* Multiple series for the same canonical metric (Datadog returns one
  series per tag combination) — samples are merged before bucketing,
  so the resulting per-week average reflects every tag.
* Near-miss metric names (``fde.p99_latency_ms`` instead of
  ``fde.p99_ms``) — warned to stderr, skipped, not an error.
* Numeric overflow — Python floats handle ``1e308`` natively; values
  outside ``float``'s representable range become ``inf`` which round-
  trips through ``json`` but is not strictly valid JSON. We treat
  ``inf``/``nan`` as malformed and raise a ValueError naming the
  sample index so the user can clip or drop the offending source.
* Engagement names with spaces, slashes, or unicode — preserved
  verbatim.
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

# Names close enough to canonical FDE metrics that the user probably
# mistyped. We warn rather than silently drop so they can rename and
# re-run. Keys are lowercase canonical candidates; values are the
# canonical NAME_MAP keys they suggest.
NEAR_MISS_HINTS = {
    "fde.p99_latency_ms": "fde.p99_ms",
    "fde.p99_response_ms": "fde.p99_ms",
    "fde.errors": "fde.error_rate",
    "fde.error_ratio": "fde.error_rate",
    "fde.uptime_pct": "fde.availability_pct",
    "fde.availability": "fde.availability_pct",
}


def _bucket_by_week(samples, *, series_idx, ts_scale):
    """Group [(ts, value), ...] into ISO-week buckets.

    ``ts_scale`` divides each timestamp to land in seconds — pass 1000
    for Datadog (millisecond timestamps) and 1 for Prometheus
    (already in seconds).

    Returns {iso_week: [values]}. Raises ValueError naming the
    series/sample on the first malformed input.
    """
    # Upper bound in the source unit; 9999-12-31 23:59:59 UTC.
    max_seconds = 253402300799
    max_ts = max_seconds * ts_scale
    unit = "ms" if ts_scale != 1 else "s"
    buckets = defaultdict(list)
    for i, sample in enumerate(samples):
        # Datadog: [ts_ms, value]. Prometheus: [ts_s, "value_str"].
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
        if ts > max_ts:
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
        # Convert source-unit timestamp to seconds for datetime.
        ts_seconds = ts / ts_scale
        try:
            dt = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(
                f"sample {i} in series {series_idx}: timestamp {ts} "
                f"could not be parsed as a datetime ({exc})") from exc
        iso = dt.isocalendar()
        buckets[(iso[0], iso[1])].append(val)
    return buckets


def _resolve_metric(dd_name, *, series_idx, warnings):
    """Return canonical NAME for an FDE metric, or None to skip.

    Logs near-miss names to ``warnings`` (and stderr) so the user can
    rename and re-run.
    """
    if dd_name in NAME_MAP:
        return NAME_MAP[dd_name]
    if dd_name in NEAR_MISS_HINTS:
        suggestion = NEAR_MISS_HINTS[dd_name]
        msg = (
            f"series {series_idx}: metric {dd_name!r} is not in the "
            f"FDE name map but looks like a typo for "
            f"{suggestion!r}; rename before re-importing")
        warnings.append(msg)
        print(f"warning: {msg}", file=sys.stderr)
        return None
    return None


def import_datadog(input_path, output_path, **opts):
    raw = json.loads(open(input_path).read())
    series_list = raw.get("series", [])
    if not isinstance(series_list, list):
        raise ValueError(
            f"Datadog dump 'series' field must be a list, got "
            f"{type(series_list).__name__}")
    if not series_list:
        raise ValueError(
            "Datadog dump contained no series (the 'series' array is "
            "empty). Check that your query matched metrics in the "
            "time window.")

    warnings = []
    # Aggregate samples per canonical metric name so duplicate series
    # (Datadog returns one per tag combination) merge into a single
    # per-week average rather than overwriting each other.
    samples_by_canonical = defaultdict(list)
    matched_metrics = set()
    skipped_empty_series = 0
    for s_idx, series in enumerate(series_list):
        if not isinstance(series, dict):
            raise ValueError(
                f"series {s_idx} is not an object: {series!r}")
        dd_name = series.get("metric", "")
        canonical = _resolve_metric(dd_name, series_idx=s_idx,
                                    warnings=warnings)
        if canonical is None:
            continue
        matched_metrics.add(dd_name)
        samples = series.get("pointlist", [])
        if not isinstance(samples, list):
            raise ValueError(
                f"series {s_idx} ({dd_name!r}): 'pointlist' must be "
                f"a list, got {type(samples).__name__}")
        if not samples:
            skipped_empty_series += 1
            continue
        bucketed = _bucket_by_week(samples, series_idx=s_idx, ts_scale=1000)
        # Convert ms → seconds for the per-metric aggregator. The
        # bucket function worked on ms because that's what Datadog
        # sends; now that we're aggregating across series we no longer
        # need ms.
        for (year, wk), values in bucketed.items():
            samples_by_canonical[canonical].append(((year, wk), values))

    if not matched_metrics:
        seen = sorted({s.get("metric", "") for s in series_list
                       if isinstance(s, dict)})
        raise ValueError(
            f"No FDE metrics found in Datadog dump. Expected one of: "
            f"{sorted(NAME_MAP)}. Got: {seen}")

    if not samples_by_canonical:
        # All FDE-named series had empty pointlists. That's distinct
        # from "no FDE metrics at all" — the metric exists but has no
        # data in the queried window.
        raise ValueError(
            f"Found FDE metrics {sorted(matched_metrics)} but every "
            f"series had an empty pointlist. Widen your time window "
            f"or check that the metrics are being reported.")

    weeks = {}
    for canonical, per_series in samples_by_canonical.items():
        # Merge: same (year, wk) across series must accumulate, not
        # overwrite. Then average over all contributing samples.
        merged = defaultdict(list)
        for (year, wk), values in per_series:
            merged[(year, wk)].extend(values)
        for (year, wk), values in merged.items():
            entry = weeks.setdefault((year, wk), {"week": wk})
            avg = sum(values) / len(values)
            entry[canonical] = (round(avg, 5) if canonical == "error_rate"
                                else round(avg, 1))

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
    return {
        "weeks": len(sorted_weeks),
        "metrics": sorted(matched_metrics),
        "warnings": warnings,
        "skipped_empty_series": skipped_empty_series,
    }


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