"""
Importer registry for `python -m fde import <source> --input <file>`.

Each importer is a callable: (input_path, output_path, **opts) -> dict
that returns the number of weeks imported. Errors are raised as
ValueError with a human-readable message; the CLI converts that to a
non-zero exit code.
"""
from .prometheus import import_prometheus
from .datadog import import_datadog
from .csv_import import import_csv

IMPORTERS = {
    "prometheus": import_prometheus,
    "datadog": import_datadog,
    "csv": import_csv,
}
