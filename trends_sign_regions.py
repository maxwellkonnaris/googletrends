"""Sample-based covariance sign sensitivity for aligned Google Trends indices.

Assumes idealized positive shares with a common denominator. Observed indices
are sampled, rounded and censored proxies. This does not estimate total-search
SD, confidence intervals, or causal health effects.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd


def read_trends_csv(path):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    header = None
    for i, line in enumerate(lines):
        fields = next(csv.reader([line]), [])
        if fields and fields[0] in ("Week", "Day", "Month", "Time"):
            header = i
            break
    if header is None:
        raise ValueError(f"{Path(path).name}: no Trends date column")
    names = next(csv.reader([lines[header]]))
    terms, geos = [], set()
    for name in names[1:]:
        match = re.fullmatch(r"(.+):\s*\(([^()]+)\)\s*", name)
        if match is None:
            raise ValueError(f"{Path(path).name}: each column must identify its term and geography")
        terms.append(match[1].strip())
        geos.add(match[2].strip())
    if not terms or len(terms) != len(set(terms)) or len(geos) != 1:
        raise ValueError(f"{Path(path).name}: duplicate terms or mixed/missing geographies")
    frame = pd.read_csv(io.StringIO("\n".join(lines[header:])), index_col=0)
    frame.index = pd.to_datetime(frame.index, errors="raise")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Dates must be unique and increasing")
    frame.columns = terms
    frame = frame.replace("<1", 0.5).apply(pd.to_numeric)
    if not np.isfinite(frame.to_numpy()).all() or (frame < 0).any().any() or (frame > 100).any().any():
        raise ValueError("Indices must be finite values in [0, 100]")
    frame.attrs["geo"] = next(iter(geos))
    frame.attrs["requires_quality"] = bool(lines and lines[0].startswith(("Category: mean of ", "Category: pull ")))
    return frame


def load_folder(folder):
    folder = Path(folder)
    paths = [p for p in sorted(folder.glob("*.csv"))
             if not p.name.startswith(("trends_pair_sign_regions", "trends_log_share_covariance"))]
    if not paths:
        raise ValueError(f"No Trends CSVs in {folder}")
    frames = [read_trends_csv(p) for p in paths]
    if len({frame.attrs["geo"] for frame in frames}) != 1:
        raise ValueError("All CSVs must have the same geography")
    if any(not frame.index.equals(frames[0].index) for frame in frames[1:]):
        raise ValueError("All CSVs must have identical dates and resolution")
    columns = [c for frame in frames for c in frame.columns]
    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate terms across CSVs; choose one series per term")
    data = pd.concat(frames, axis=1)
    if len(data) < 20:
        raise ValueError("At least 20 shared dates are required")
    data.attrs["geo"] = frames[0].attrs["geo"]
    metadata_path = folder / "trends_quality.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != 1 or metadata.get("geo") != data.attrs["geo"]:
            raise ValueError("Incompatible quality metadata")
        if metadata["dates"] != list(data.index.strftime("%Y-%m-%d")) or set(metadata["terms"]) != set(columns):
            raise ValueError("Quality metadata does not match CSV dates or terms")
        used_files = set()
        for label, item in metadata["terms"].items():
            path = folder / item["file"]
            if path not in paths or item["file"] in used_files:
                raise ValueError("Quality metadata references unexpected or duplicate CSVs")
            used_files.add(item["file"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"CSV changed after assembly: {path.name}")
            if list(read_trends_csv(path).columns) != [label]:
                raise ValueError("Quality metadata term/filename mismatch")
            masks = item["low_volume_dates_by_pull"]
            if not masks or any(not set(dates).issubset(metadata["dates"]) for dates in masks.values()):
                raise ValueError("Invalid raw low-volume date mask")
        data.attrs["quality"] = metadata
    elif any(frame.attrs["requires_quality"] for frame in frames):
        raise ValueError("Generated exports require trends_quality.json; keep it with the CSVs")
    return data


def low_volume_share(data):
    metadata = data.attrs.get("quality")
    if metadata is None:
        return (data < 1).mean()
    dates = set(data.index.strftime("%Y-%m-%d"))
    return pd.Series({label: max(len(dates.intersection(mask)) / len(dates)
                                for mask in item["low_volume_dates_by_pull"].values())
                      for label, item in metadata["terms"].items()})


def sign_regions(log_shares):
    """Pairwise sharp bounds using sample moments and unrestricted dependence.

    For X=log W_i, Y=log W_j, Z=log T and s=SD(Z), absolute-log covariance
    lies in Cov(X,Y)+s² +/- s*SD(X+Y). Pairwise extrema need not be simultaneous.
    These sample plug-in moments do not identify population moments without
    additional assumptions or quantify statistical uncertainty.
    """
    if len(log_shares) < 2 or log_shares.shape[1] < 2:
        raise ValueError("At least two dates and two retained terms are required")
    if not np.isfinite(log_shares.to_numpy()).all():
        raise ValueError("Log indices must be finite")
    centred = log_shares - log_shares.mean(axis=0)
    covariance = np.cov(centred.to_numpy(), rowvar=False)
    if (np.diag(covariance) <= np.finfo(float).eps).any():
        raise ValueError("Constant or numerically zero-variance terms must be removed")
    terms, rows = list(log_shares.columns), []
    for i in range(len(terms)):
        for j in range(i + 1, len(terms)):
            cov = covariance[i, j]
            sd_sum = np.sqrt(max(0.0, covariance[i, i] + 2 * cov + covariance[j, j]))
            sd_diff = np.sqrt(max(0.0, covariance[i, i] - 2 * cov + covariance[j, j]))
            rows.append(dict(term_i=terms[i], term_j=terms[j], comp_cov=cov,
                             comp_corr=float(np.clip(cov / np.sqrt(covariance[i, i] * covariance[j, j]), -1, 1)),
                             comp_sign=int(np.sign(cov)), zero_band_lower=abs(sd_sum - sd_diff) / 2,
                             zero_band_upper=(sd_sum + sd_diff) / 2))
    return pd.DataFrame(rows), covariance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--floor", type=float, default=0.5, help="positive replacement for indices below the log floor")
    parser.add_argument("--start", help="first retained date, YYYY-MM-DD")
    parser.add_argument("--end", help="last retained date, YYYY-MM-DD")
    parser.add_argument("--max-zero-share", type=float, default=0.10,
                        help="maximum below-resolution fraction; worst pull when raw masks are available")
    args = parser.parse_args()
    try:
        if not np.isfinite(args.floor) or args.floor <= 0:
            raise ValueError("--floor must be finite and positive")
        if not np.isfinite(args.max_zero_share) or not 0 <= args.max_zero_share <= 1:
            raise ValueError("--max-zero-share must be between 0 and 1")
        full = load_folder(args.folder)
        data = full.loc[args.start:args.end].copy()
        data.attrs = full.attrs.copy()
        if len(data) < 20:
            raise ValueError("At least 20 dates must remain after date-window slicing")
        share = low_volume_share(data)
        kept = share.index[share <= args.max_zero_share]
        dropped = sorted(set(data.columns) - set(kept))
        if dropped:
            print("Dropped (raw below-resolution frequency):", ", ".join(dropped))
        if len(kept) < 2:
            raise ValueError("Fewer than two terms remain after the low-volume filter")
        logs = np.log(data[kept].clip(lower=args.floor))
        constants = list(logs.columns[logs.var(ddof=1) <= np.finfo(float).eps])
        if constants:
            print("Dropped (zero log variance):", ", ".join(constants))
            logs = logs.drop(columns=constants)
        pairs, covariance = sign_regions(logs)
        print(f"{data.index.min():%Y-%m-%d} to {data.index.max():%Y-%m-%d}: {len(logs)} dates x {logs.shape[1]} terms")
        print(pairs.sort_values("zero_band_lower", ascending=False).to_string(index=False))
        tag = f"_{args.start or 'start'}_{args.end or 'end'}" if args.start or args.end else ""
        folder = Path(args.folder)
        pairs.to_csv(folder / f"trends_pair_sign_regions{tag}.csv", index=False)
        pd.DataFrame(covariance, index=logs.columns, columns=logs.columns).to_csv(
            folder / f"trends_log_share_covariance{tag}.csv", index_label="term")
        print("Sample-moment sensitivity thresholds only; total-search SD and confidence intervals are not estimated.")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
