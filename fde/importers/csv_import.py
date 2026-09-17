"""
CSV importer for ad-hoc measurements.

Input shape (header required):

    week,p99_ms,error_rate,availability_pct,metric_value
    1,468.3,0.0003,99.92,180
    2,459.7,0.0002,99.93,170
    ...

Only `week` is required; the rest are optional. Use this when you have
neither Prometheus nor Datadog, or when you want to type the values in
by hand from a status dashboard.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path


REQUIRED_FIELDS = {"week"}
OPTIONAL_FIELDS = {"p99_ms", "error_rate", "availability_pct",
                   "metric_value"}


def import_csv(input_path, output_path, **opts):
    rows = []
    with open(input_path) as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV file {input_path} has no header")
        missing = REQUIRED_FIELDS - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"CSV missing required columns: {sorted(missing)}. "
                f"Got: {reader.fieldnames}")
        for i, row in enumerate(reader, start=2):
            entry = {}
            try:
                entry["week"] = int(row["week"])
            except (TypeError, ValueError):
                raise ValueError(
                    f"row {i}: 'week' must be an integer, got {row['week']!r}")
            for col in OPTIONAL_FIELDS:
                if col in row and row[col] not in (None, ""):
                    try:
                        entry[col] = float(row[col])
                    except ValueError:
                        raise ValueError(
                            f"row {i}: '{col}' must be a number, "
                            f"got {row[col]!r}")
            rows.append(entry)

    if not rows:
        raise ValueError("CSV file contained no data rows")

    rows.sort(key=lambda r: r["week"])
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
        "post_ga_log": rows,
        "_imported_from": f"csv:{input_path}",
        "_imported_weeks": len(rows),
    }
    output_path.write_text(
        __import__("json").dumps(log, indent=2))
    return {"weeks": len(rows)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: csv INPUT OUTPUT [--engagement NAME]",
              file=sys.stderr)
        sys.exit(2)
    in_path, out_path = sys.argv[1], Path(sys.argv[2])
    engagement = None
    if "--engagement" in sys.argv:
        i = sys.argv.index("--engagement")
        engagement = sys.argv[i + 1]
    summary = import_csv(Path(in_path), out_path, engagement=engagement)
    print(f"imported {summary['weeks']} weeks from CSV")
