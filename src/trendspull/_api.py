"""The public collector, with optional G-TAB calibration across comparisons."""
import hashlib
import json
import logging
import math
from pathlib import Path
import platform
import random
import re
import time
import uuid
import warnings
from datetime import date, datetime, timezone
from typing import Optional, Sequence, Tuple, Union

import pandas as pd
import requests

from ._client import _SEARCH_TYPES, _TrendsClient, _timeline
from ._gtab import _CALIBRATED_COLUMNS, _calibrate, _groups, _next_bridge

_VERSION = "0.1.0.dev0"
_LOG = logging.getLogger(__name__)
_COLUMNS = ["date", "keyword", "geo", "value", "formatted_value", "has_data", "is_partial", "low_volume",
            "start", "end", "category", "search_type", "language", "retrieved_at", "request_id"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _strings(value, name, allow_empty=False):
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)) or not items:
        raise ValueError(f"{name} must be a string or a nonempty list/tuple of strings")
    if any(not isinstance(x, str) or (not allow_empty and not x.strip()) for x in items):
        raise ValueError(f"{name} must contain valid strings")
    if len(items) != len(set(items)):
        raise ValueError(f"{name} must not contain duplicates")
    return list(items)


def _fixed_date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{name} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from None


def _validate(keywords, start, end, geo, category, search_type, language, delay, max_attempts, timeout, min_gap_days):
    keywords, geos = _strings(keywords, "keywords"), _strings(geo, "geo", allow_empty=True)
    if _fixed_date(start, "start") > _fixed_date(end, "end"):
        raise ValueError("start must be on or before end")
    if any(not re.fullmatch(r"(?:[A-Z]{2}(?:-[A-Z0-9]+)*)?", g) for g in geos):
        raise ValueError("geo must be '' for worldwide or a code such as US or US-CA")
    if type(category) is not int or category < 0:
        raise ValueError("category must be a nonnegative Google category ID")
    if not isinstance(search_type, str) or search_type not in _SEARCH_TYPES:
        raise ValueError(f"search_type must be one of {', '.join(_SEARCH_TYPES)}")
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        raise ValueError("language must be a language tag, for example en-US")
    if (not isinstance(delay, (tuple, list)) or len(delay) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) or x < 0 for x in delay)
            or delay[0] > delay[1]):
        raise ValueError("delay must be a finite nonnegative (minimum, maximum) pair")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if min_gap_days is not None and (type(min_gap_days) is not int or min_gap_days < 1):
        raise ValueError("min_gap_days must be None or a positive integer")
    return keywords, geos


def _atomic(path, payload):
    data = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
    temporary.replace(path)
    return hashlib.sha256(data).hexdigest()


def _table(records, calibrated=False):
    data = pd.DataFrame.from_records(records, columns=_COLUMNS + (_CALIBRATED_COLUMNS if calibrated else []))
    for column in ("date", "retrieved_at"):
        data[column] = pd.to_datetime(data[column], utc=True)
    for column in ("value", "category"):
        data[column] = pd.array(data[column], dtype="Int64")
    for column in ("has_data", "is_partial", "low_volume"):
        data[column] = pd.array(data[column], dtype="boolean")
    for column in ("keyword", "geo", "formatted_value", "start", "end", "search_type", "language", "request_id"):
        data[column] = pd.array(data[column], dtype="string")
    if calibrated:
        for column in _CALIBRATED_COLUMNS[:-1]:
            data[column] = pd.array(data[column], dtype="Float64")
        data["calibration_reference"] = pd.array(data["calibration_reference"], dtype="string")
    return data


def _space_dates(rows, min_gap_days):
    if min_gap_days is None:
        return rows
    selected, previous = [], None
    for row in rows:
        timestamp = row["date"]
        if previous is None or timestamp == previous or (timestamp - previous).total_seconds() >= min_gap_days * 86400:
            selected.append(row)
            previous = timestamp
    return selected


def pull_trends(
    keywords: Union[str, Sequence[str]],
    start: str,
    end: str,
    *,
    geo: Union[str, Sequence[str]] = "",
    search_type: str = "web",
    category: int = 0,
    language: str = "en-US",
    min_gap_days: Optional[int] = None,
    archive: Optional[Union[str, Path]] = None,
    delay: Tuple[float, float] = (8, 20),
    max_attempts: int = 3,
    timeout: float = 60,
    calibration: str = "auto",
    reference: Optional[str] = None,
    anchors: Optional[Sequence[str]] = None,
    min_anchor_peak: int = 10,
    max_comparisons: int = 100,
) -> pd.DataFrame:
    """Return a tidy pandas DataFrame of Google's interest-over-time observations.

    Parameters
    ----------
    keywords : str or list/tuple of str
        Search strings or Google Topic IDs. Up to five are compared together;
        larger sets use G-TAB calibration automatically.
    start, end : str
        Fixed YYYY-MM-DD dates. Google chooses the time resolution and bucket labels.
    geo : str or list/tuple of str
        Google geography codes, e.g. 'US-CA'; '' requests worldwide data (default).
    search_type : str
        'web', 'images', 'news', 'youtube' or 'shopping'. Default 'web'.
    category : int
        Google category ID; 0 means all categories.
    language : str
        Interface language, default 'en-US'; this does not restrict searches by language.
    min_gap_days : int, optional
        Minimum elapsed days between retained timestamps, independently per geography.
        Keep the first returned timestamp, then the next at least this many days later.
        All keywords at each selected timestamp stay together. Default None keeps all
        dates. Selection does not rescale values or guarantee uncorrelated observations.
    archive : str or pathlib.Path, optional
        Save successful response texts, checksums and a manifest in a new run subfolder.
        No files are written by default. Existing runs are not overwritten or reused.
    delay : pair of float
        Random pause range in seconds between geography comparisons, default (8, 20).
    max_attempts : int
        Total attempts per chart request, default 3. Permanent HTTP errors fail immediately.
    timeout : float
        Requests timeout in seconds, default 60. Retries can extend total duration.
    calibration : {'auto', 'none', 'gtab'}
        'auto' uses raw joint comparisons for up to five terms and G-TAB for more.
        'none' rejects more than five terms. 'gtab' also calibrates smaller sets.
    reference : str, optional
        G-TAB reference term, default the first keyword. Its usable period peak is 1.
    anchors : list/tuple of str, optional
        Additional bridge terms for the G-TAB bank; not returned as observations.
        Requested terms are the bank candidates by default. Candidates are queried
        in overlapping groups of five, in input order, independently per geography.
        Targeted pair comparisons connect terms too small in the initial charts.
    min_anchor_peak : int
        Require both usable comparison peaks >= this integer (2-100), default 10.
        Known partial, unavailable and low-volume observations do not define peaks.
    max_comparisons : int
        Maximum comparison charts across all geographies, including adaptive anchor
        pairs, default 100. Oversized initial plans fail before network/file access;
        reaching the cap during adaptive calibration fails without a partial table.

    Returns
    -------
    pandas.DataFrame
        One row per returned timestamp, keyword and geography. Values remain on Google's
        shared 0-100 comparison scale within each geography request. Separate geographies
        and calls have separate scales. At selected dates, quality flags, zeros and
        partial periods are retained; missing flags remain pd.NA. No alignment or imputation occurs.
        G-TAB keeps these raw columns and adds calibrated_value, calibrated_lower,
        calibrated_upper, calibration_factor and calibration_reference. Use
        calibrated_value to compare terms across requests in the same geography/call.
        Units are fractions of the reference's usable period peak, not raw Google
        0-100 units. Bounds address integer rounding only, conditional on the sampled
        data; low-volume/unavailable/partial rows have missing bounds. The anchor
        bank must be connected by reliable peak ratios, otherwise the call fails.
        Calibration precedes optional date selection. Geographies remain separately scaled.
        All request settings and retrieval timestamps are included in columns; additional
        run/request metadata is in data.attrs['trendspull']. CSV exports can be read by R.

    Raises
    ------
    ValueError
        Invalid inputs, before network access or archive creation.
    RuntimeError
        A request or response failed. No partial DataFrame is returned. An optional
        archive retains completed responses and records the failure.
    """
    keywords, geos = _validate(keywords, start, end, geo, category, search_type,
                               language, delay, max_attempts, timeout, min_gap_days)
    if not isinstance(calibration, str) or calibration not in ("auto", "none", "gtab"):
        raise ValueError("calibration must be 'auto', 'none' or 'gtab'")
    calibrated = calibration == "gtab" or (calibration == "auto" and len(keywords) > 5)
    if not calibrated and len(keywords) > 5:
        raise ValueError("Google Trends comparisons support at most 5 keywords without G-TAB calibration")
    bridges = [] if anchors is None else _strings(anchors, "anchors")
    if not calibrated and (reference is not None or anchors is not None):
        raise ValueError("reference and anchors require G-TAB; set calibration='gtab'")
    terms = keywords + [term for term in bridges if term not in keywords]
    if reference is not None and (not isinstance(reference, str) or reference not in terms):
        raise ValueError("reference must be one of the keywords or anchors")
    reference = reference if reference is not None else keywords[0]
    if type(min_anchor_peak) is not int or not 2 <= min_anchor_peak <= 100:
        raise ValueError("min_anchor_peak must be an integer between 2 and 100")
    if type(max_comparisons) is not int or max_comparisons < 1:
        raise ValueError("max_comparisons must be a positive integer")
    groups = _groups(terms) if calibrated else [keywords]
    comparison_count = len(groups) * len(geos)
    if comparison_count > max_comparisons:
        raise ValueError(f"Planned {comparison_count} comparisons exceeds max_comparisons={max_comparisons}")
    manifest = dict(version=_VERSION, source="Google Trends website", started_at=_now(), status="running",
                    settings=dict(keywords=keywords, start=start, end=end, geo=geos, category=category,
                                  search_type=search_type, language=language, tz=0,
                                  delay=list(delay), max_attempts=max_attempts, timeout=timeout,
                                  min_gap_days=min_gap_days, calibration=calibration,
                                  reference=reference if calibrated else None, anchors=bridges,
                                  min_anchor_peak=min_anchor_peak, max_comparisons=max_comparisons),
                    normalization=("G-TAB: fractions of reference usable period peak, separately per geography"
                                   if calibrated else "shared keyword scale within each geography request"),
                    calibration=dict(method="gtab" if calibrated else "none", geographies={},
                                     citation="https://doi.org/10.1145/3340531.3412075" if calibrated else None,
                                     bank="requested terms plus optional anchors; overlapping groups of five and adaptive pairs" if calibrated else None),
                    runtime=dict(python=platform.python_version(), pandas=pd.__version__, requests=requests.__version__),
                    requests=[])
    run_dir = None
    if archive is not None:
        root = Path(archive)
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / f"run-{uuid.uuid4().hex}"
        run_dir.mkdir()
        _atomic(run_dir / "manifest.json", manifest)
    records, client, current = [], None, None
    try:
        client = _TrendsClient(language, max_attempts, timeout)
        def fetch(group, region):
            nonlocal current
            if len(manifest["requests"]) >= max_comparisons:
                raise ValueError(f"G-TAB reached max_comparisons={max_comparisons}; calibration is incomplete")
            if manifest["requests"]:
                time.sleep(random.uniform(*delay))
            current = dict(request_id=uuid.uuid4().hex, keywords=list(group), geo=region,
                           requested_at=_now(), status="running")
            manifest["requests"].append(current)
            explore, multiline, resolution = client.timeline(group, region, start, end, category, search_type)
            retrieved_at = _now()
            if run_dir is not None:
                filename = f"{current['request_id']}.json"
                current["file"] = filename
                current["sha256"] = _atomic(run_dir / filename, dict(explore=explore, multiline=multiline))
            rows = _timeline(multiline, group)
            provider_row_count = len(rows)
            rows = rows if calibrated else _space_dates(rows, min_gap_days)
            current.update(status="ok" if rows else "empty", row_count=len(rows),
                           provider_row_count=provider_row_count, retrieved_at=retrieved_at, resolution=resolution)
            rows = [dict(row, geo=region, start=start, end=end, category=category,
                         search_type=search_type, language=language, retrieved_at=retrieved_at,
                         request_id=current["request_id"]) for row in rows]
            if not rows:
                warnings.warn(f"Google returned an empty timeline for {group!r} in {region or 'worldwide'}",
                              RuntimeWarning, stacklevel=2)
            if run_dir is not None:
                _atomic(run_dir / "manifest.json", manifest)
            return dict(request_id=current["request_id"], keywords=group, resolution=resolution, rows=rows)

        for region in geos:
            comparisons = [fetch(group, region) for group in groups]
            if calibrated:
                while True:
                    pair = _next_bridge(comparisons, keywords, reference, min_anchor_peak)
                    if pair is None:
                        break
                    comparisons.append(fetch(pair, region))
                rows, details = _calibrate(comparisons, keywords, reference, min_anchor_peak)
                records.extend(_space_dates(rows, min_gap_days))
                manifest["calibration"]["geographies"][region] = details
            else:
                records.extend(comparisons[0]["rows"])
        if calibrated:
            for entry in manifest["requests"]:
                entry["row_count"] = sum(row["request_id"] == entry["request_id"] for row in records)
        data = _table(records, calibrated)
        manifest.update(status="complete", completed_at=_now(), row_count=len(data))
    except BaseException as error:
        manifest.update(status="failed", completed_at=_now(), error=f"{type(error).__name__}: {error}")
        if current is not None and current["status"] == "running":
            current.update(status="failed", error=str(error))
        if run_dir is not None:
            try:
                _atomic(run_dir / "manifest.json", manifest)
            except OSError as archive_error:
                _LOG.warning("Could not record collection failure in archive: %s", archive_error)
        if isinstance(error, Exception):
            context = f" for {current['keywords']!r} in {current['geo'] or 'worldwide'}" if current else ""
            raise RuntimeError(f"Google Trends collection failed{context}: {error}") from error
        raise
    finally:
        if client is not None:
            client.close()
    if run_dir is not None:
        _atomic(run_dir / "manifest.json", manifest)
    data.attrs["trendspull"] = dict(manifest, archive=str(run_dir.resolve()) if run_dir else None,
                                    timezone="UTC")
    return data
