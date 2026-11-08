"""Loudness history across analysis runs (ported from DJ_Loudness_Analyzer/dashboard.py).

A run is {"id", "scope": file|folder, "complete", "config": {"input"}, "manifest": [paths],
"tracks": [rows with path, sha256, status, integrated_lufs, ...]}, oldest first.
"""
import statistics
from pathlib import Path


def valid(row):
    return row.get("status") == "OK" and all(
        isinstance(row.get(k), (int, float)) for k in ("integrated_lufs", "true_peak_dbtp", "loudness_range_lu"))


def median_lufs(rows):
    values = [r["integrated_lufs"] for r in rows if valid(r)]
    return statistics.median(values) if values else None


def current_library(runs):
    """Latest measurement per path. Missing files keep their history and are flagged;
    renamed files are linked only when their SHA-256 hashes match."""
    current = {}
    hashes = {}
    for run in runs:
        if run["scope"] == "test":
            continue
        if run["scope"] == "folder" and run["complete"]:
            root = Path(run["config"]["input"])
            present = set(run["manifest"])
            for path, row in current.items():
                if Path(path).is_relative_to(root):
                    row["missing"] = path not in present
        for original in run["tracks"]:
            row = dict(original, run_id=run["id"], missing=False)
            path = row["path"]
            digest = row.get("sha256")
            previous = hashes.get(digest) if digest else None
            if previous and previous != path and not Path(previous).exists():
                current.pop(previous, None)
            current[path] = row
            if digest:
                hashes[digest] = path
    for path, row in current.items():
        row["missing"] = row["missing"] or not Path(path).is_file()
    return list(current.values())
