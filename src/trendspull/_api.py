"""The single public collection function and its input/output contract."""
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
    if len(keywords) > 5:
        raise ValueError("Google Trends comparisons support at most 5 keywords; separate batches would have different scales")
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


def _table(records):
    data = pd.DataFrame.from_records(records, columns=_COLUMNS)
    for column in ("date", "retrieved_at"):
        data[column] = pd.to_datetime(data[column], utc=True)
    for column in ("value", "category"):
        data[column] = pd.array(data[column], dtype="Int64")
    for column in ("has_data", "is_partial", "low_volume"):
        data[column] = pd.array(data[column], dtype="boolean")
    for column in ("keyword", "geo", "formatted_value", "start", "end", "search_type", "language", "request_id"):
        data[column] = pd.array(data[column], dtype="string")
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
) -> pd.DataFrame:
    """Return a tidy pandas DataFrame of Google's interest-over-time observations.

    Parameters
    ----------
    keywords : str or list/tuple of str
        One to five search strings or Google Topic IDs, compared together per geography.
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

    Returns
    -------
    pandas.DataFrame
        One row per returned timestamp, keyword and geography. Values remain on Google's
        shared 0-100 comparison scale within each geography request. Separate geographies
        and calls have separate scales. At selected dates, quality flags, zeros and
        partial periods are retained; missing flags remain pd.NA. No alignment or imputation occurs.
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
    manifest = dict(version=_VERSION, source="Google Trends website", started_at=_now(), status="running",
                    settings=dict(keywords=keywords, start=start, end=end, geo=geos, category=category,
                                  search_type=search_type, language=language, tz=0,
                                  delay=list(delay), max_attempts=max_attempts, timeout=timeout,
                                  min_gap_days=min_gap_days),
                    normalization="shared keyword scale within each geography request",
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
        for index, region in enumerate(geos):
            current = dict(request_id=uuid.uuid4().hex, keywords=list(keywords), geo=region,
                           requested_at=_now(), status="running")
            manifest["requests"].append(current)
            explore, multiline, resolution = client.timeline(keywords, region, start, end, category, search_type)
            retrieved_at = _now()
            if run_dir is not None:
                filename = f"{current['request_id']}.json"
                current["file"] = filename
                current["sha256"] = _atomic(run_dir / filename, dict(explore=explore, multiline=multiline))
            rows = _timeline(multiline, keywords)
            provider_row_count = len(rows)
            rows = _space_dates(rows, min_gap_days)
            current.update(status="ok" if rows else "empty", row_count=len(rows),
                           provider_row_count=provider_row_count, retrieved_at=retrieved_at, resolution=resolution)
            for row in rows:
                records.append(dict(row, geo=region, start=start, end=end, category=category,
                                    search_type=search_type, language=language, retrieved_at=retrieved_at,
                                    request_id=current["request_id"]))
            if not rows:
                warnings.warn(f"Google returned an empty timeline for {keywords!r} in {region or 'worldwide'}",
                              RuntimeWarning, stacklevel=2)
            if run_dir is not None:
                _atomic(run_dir / "manifest.json", manifest)
            if index + 1 < len(geos):
                time.sleep(random.uniform(*delay))
        data = _table(records)
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
