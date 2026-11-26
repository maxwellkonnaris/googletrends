#!/usr/bin/env python3
"""Collect, archive and assemble fixed-specification Google Trends timelines.

Uses unofficial website endpoints. See README.md for quality rules and limits.
"""
import argparse
import hashlib
import io
import json
import math
import platform
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

TOOL_VERSION = "2.0.0"
BASE = "https://trends.google.com/trends"
EXPLORE_URL = f"{BASE}/api/explore"
MULTILINE_URL = f"{BASE}/api/widgetdata/multiline"
COOKIE_URL = f"{BASE}/explore?geo=US"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def utc_now():
    return datetime.now(timezone.utc)


def stamp(dt=None):
    return (dt or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("xb") as handle:
        handle.write(data)
        handle.flush()
    temporary.replace(path)


def atomic_json(path, data):
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def load_config(path):
    path = Path(path)
    raw = path.read_bytes()
    config = json.loads(raw)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    for key in ("study", "time", "geos", "terms"):
        if key not in config:
            raise ValueError(f"{path}: missing '{key}'")
    if not isinstance(config["study"], str) or not config["study"].strip():
        raise ValueError("study must be a nonempty string")
    try:
        start, end = config["time"].split()
        if datetime.strptime(start, "%Y-%m-%d") > datetime.strptime(end, "%Y-%m-%d"):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError("time must be a fixed 'YYYY-MM-DD YYYY-MM-DD' window, start <= end") from None
    for field in ("geos", "terms"):
        if not isinstance(config[field], list) or not config[field]:
            raise ValueError(f"{field} must be a nonempty list")
    codes, labels, names = [], [], []
    for geo in config["geos"]:
        code = geo.get("code") if isinstance(geo, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]+)*", code):
            raise ValueError("Each geo needs a safe nonempty code such as US-CA")
        codes.append(code)
    for term in config["terms"]:
        if not isinstance(term, dict):
            raise ValueError("Each term must have label and query")
        label, query = term.get("label"), term.get("query")
        if not isinstance(label, str) or not label.strip() or not slug(label):
            raise ValueError("Each term needs a nonempty label with ASCII letters or digits")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{label}: query must be a nonempty string")
        labels.append(label)
        names.append(slug(label))
    if len(set(codes)) != len(codes):
        raise ValueError("Geography codes must be unique")
    if len(set(labels)) != len(labels) or len(set(names)) != len(names):
        raise ValueError("Term labels and their output filenames must be unique")
    config.setdefault("category", 0)
    config.setdefault("property", "")
    config.setdefault("hl", "en-US")
    config.setdefault("delay_seconds", [8, 20])
    if type(config["category"]) is not int or config["category"] < 0:
        raise ValueError("category must be a nonnegative integer")
    if config["property"] not in ("", "images", "news", "youtube", "froogle"):
        raise ValueError("Unknown Google Trends search property")
    if not isinstance(config["hl"], str) or not config["hl"].strip():
        raise ValueError("hl must be a nonempty language string")
    delay = config["delay_seconds"]
    if (not isinstance(delay, (list, tuple)) or len(delay) != 2
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                       and math.isfinite(x) and x >= 0 for x in delay)
            or delay[0] > delay[1]):
        raise ValueError("delay_seconds must be finite nonnegative [minimum, maximum]")
    config["_sha256"], config["_text"] = sha256_bytes(raw), raw.decode("utf-8")
    return config


def parse_google_json(text):
    start = text.find("{")
    if start < 0:
        raise ValueError(f"No JSON object in response: {text[:120]!r}")
    return json.loads(text[start:])


def timeline_rows(text):
    timeline = parse_google_json(text)["default"]["timelineData"]
    if not isinstance(timeline, list) or not timeline:
        raise ValueError("Google returned an empty timeline")
    rows = []
    for point in timeline:
        value = point["value"][0]
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not 0 <= value <= 100 or int(value) != value):
            raise ValueError("Expected integer Google Trends indices in [0, 100]")
        has_data, partial = point.get("hasData", [True])[0], point.get("isPartial", False)
        if not isinstance(has_data, bool) or not isinstance(partial, bool):
            raise ValueError("Google data-quality flags must be booleans")
        formatted = point.get("formattedValue", [str(value)])[0]
        if not isinstance(formatted, str):
            raise ValueError("Google formattedValue must be a string")
        rows.append(dict(week=datetime.fromtimestamp(int(point["time"]), timezone.utc).strftime("%Y-%m-%d"),
                         value=int(value), formatted_value=formatted, has_data=has_data,
                         is_partial=partial, low_volume=value < 1 or formatted.strip() == "<1"))
    dates = [r["week"] for r in rows]
    if dates != sorted(set(dates)):
        raise ValueError("Timeline dates must be unique and increasing")
    return rows


class TrendsClient:
    """Website explore -> chart token -> timeline; not the official API."""

    def __init__(self, hl="en-US", tz=0, delay=(8, 20), max_attempts=6):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.hl, self.tz, self.delay, self.max_attempts = hl, tz, delay, max_attempts
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": hl,
                                     "Referer": f"{BASE}/explore"})
        self._warm()

    def close(self):
        self.session.close()

    def _warm(self):
        try:
            response = self.session.get(COOKIE_URL, timeout=30)
            if response.status_code != 200:
                print(f"  warning: session warmup HTTP {response.status_code}; trying chart endpoints")
        except requests.RequestException as error:
            print(f"  warning: session warmup failed: {error}")

    def fetch(self, url, params):
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=60)
            except requests.RequestException as error:
                status, reason = None, str(error)
            else:
                if response.status_code == 200:
                    return response.text
                status, reason = response.status_code, response.reason
                if status != 429 and status < 500:
                    raise RuntimeError(f"HTTP {status} ({reason}): {url}")
            if attempt == self.max_attempts:
                break
            wait = min(900, 30 * 2 ** (attempt - 1)) + random.uniform(0, 15)
            print(f"  HTTP {status or 'error'} ({reason}); attempt {attempt}/{self.max_attempts}, waiting {wait:.0f}s")
            time.sleep(wait)
            if status == 429:
                self.session.cookies.clear()
                self._warm()
        raise RuntimeError(f"Gave up after {self.max_attempts} attempts (last: {status}, {reason}): {url}")

    def interest_over_time(self, query, geo, time_range, category=0, prop=""):
        req = {"comparisonItem": [{"keyword": query, "geo": geo, "time": time_range}],
               "category": category, "property": prop}
        explore = self.fetch(EXPLORE_URL, {"hl": self.hl, "tz": self.tz, "req": json.dumps(req)})
        widget = next((w for w in parse_google_json(explore)["widgets"] if w.get("id") == "TIMESERIES"), None)
        if widget is None:
            raise RuntimeError("No TIMESERIES widget in the Explore response")
        time.sleep(random.uniform(2, 5))
        multiline = self.fetch(MULTILINE_URL, {"hl": self.hl, "tz": self.tz,
                                              "req": json.dumps(widget["request"]), "token": widget["token"]})
        return explore, multiline, timeline_rows(multiline)

    def pause(self):
        time.sleep(random.uniform(*self.delay))


def read_raw(path):
    return timeline_rows(json.loads(Path(path).read_text(encoding="utf-8"))["multiline"])


def verified_raw(pull_dir, entry):
    relative = Path(entry["file"])
    raw_path = (pull_dir / relative).resolve()
    if relative.is_absolute() or pull_dir.resolve() not in raw_path.parents:
        raise ValueError("Raw response path escapes its pull directory")
    if sha256_bytes(raw_path.read_bytes()) != entry["sha256"]:
        raise ValueError(f"Hash mismatch: {raw_path}")
    rows = read_raw(raw_path)
    if len(rows) != entry["weeks"]:
        raise ValueError(f"Timeline count differs from manifest: {raw_path}")
    return rows


def one_pull(config, out, client):
    pull_id = utc_now().strftime("%Y-%m-%d")
    pull_dir = Path(out) / "raw" / pull_id
    manifest_path = pull_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "pull_id": pull_id, "study": config["study"], "config_sha256": config["_sha256"],
        "tool_version": TOOL_VERSION, "python": platform.python_version(),
        "requests": requests.__version__, "numpy": np.__version__, "pandas": pd.__version__,
        "source_sha256": sha256_bytes(Path(__file__).read_bytes()), "started_utc": stamp(), "series": {}}
    if manifest["config_sha256"] != config["_sha256"]:
        raise ValueError(f"{pull_dir} has a different config; use a new --out folder")
    snapshot = pull_dir / "config.json"
    if snapshot.exists() and sha256_bytes(snapshot.read_bytes()) != config["_sha256"]:
        raise ValueError(f"Configuration snapshot changed: {snapshot}")
    if not snapshot.exists():
        atomic_write(snapshot, config["_text"].encode("utf-8"))
    atomic_json(manifest_path, manifest)
    jobs = [(g, t) for g in config["geos"] for t in config["terms"]]
    for n, (geo, term) in enumerate(jobs, 1):
        if utc_now().strftime("%Y-%m-%d") != pull_id:
            print("UTC date changed; stopping this pull rather than assigning later requests to its starting day")
            return False
        key = f"{geo['code']}|{term['label']}"
        previous = manifest["series"].get(key, {})
        if previous.get("status") == "ok":
            try:
                verified_raw(pull_dir, previous)
            except (OSError, ValueError, KeyError, TypeError) as error:
                print(f"  re-fetching {key}: {error}")
            else:
                continue
        print(f"[{pull_id}] {n}/{len(jobs)} {key}")
        entry = dict(geo=geo["code"], label=term["label"], query=term["query"],
                     requested_utc=stamp(), tool_version=TOOL_VERSION)
        try:
            explore, multiline, _ = client.interest_over_time(
                term["query"], geo["code"], config["time"], config["category"], config["property"])
            rows = timeline_rows(multiline)
            raw = json.dumps({"explore": explore, "multiline": multiline}).encode("utf-8")
            raw_path = pull_dir / geo["code"] / f"{slug(term['label'])}.json"
            atomic_write(raw_path, raw)
            entry.update(status="ok", file=str(raw_path.relative_to(pull_dir)),
                         sha256=sha256_bytes(raw), weeks=len(rows), completed_utc=stamp())
        except Exception as error:
            entry.update(status="failed", error=str(error)[:300])
            print(f"  failed: {error}")
        manifest["series"][key] = entry
        manifest["updated_utc"] = stamp()
        atomic_json(manifest_path, manifest)
        client.pause()
    ok = sum(manifest["series"].get(f"{g['code']}|{t['label']}", {}).get("status") == "ok" for g, t in jobs)
    print(f"[{pull_id}] {ok}/{len(jobs)} series saved in {pull_dir}")
    return ok == len(jobs)


def cmd_check(args):
    config = load_config(args.config)
    term, geo = config["terms"][0], config["geos"][0]["code"]
    client = TrendsClient(hl=config["hl"], delay=config["delay_seconds"])
    try:
        _, _, rows = client.interest_over_time(term["query"], geo, config["time"], config["category"], config["property"])
    finally:
        client.close()
    print(f"OK: '{term['label']}' in {geo}, {len(rows)} points, {rows[0]['week']} to {rows[-1]['week']}")
    print("First points:", ", ".join(f"{r['week']}={r['formatted_value']}" for r in rows[:5]))


def cmd_pull(args):
    config = load_config(args.config)
    for k in range(args.repeat):
        if k:
            now = utc_now()
            wake = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            wake += timedelta(minutes=random.uniform(10, 60))
            print(f"Pull {k + 1}/{args.repeat} starts after {stamp(wake)}; sample independence is unknown")
            time.sleep(max(0, (wake - utc_now()).total_seconds()))
        client = TrendsClient(hl=config["hl"], delay=config["delay_seconds"])
        try:
            complete = one_pull(config, args.out, client)
        finally:
            client.close()
        if not complete:
            raise SystemExit("Incomplete pull (see manifest.json); retry today to resume. Later repeat days were not started.")


def archive_records(config, out):
    records = []
    expected = {f"{g['code']}|{t['label']}": (g["code"], t["label"], t["query"])
                for g in config["geos"] for t in config["terms"]}
    for manifest_path in sorted((out / "raw").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["config_sha256"] != config["_sha256"]:
            raise ValueError(f"Different config in {manifest_path}; do not combine studies")
        if manifest["pull_id"] != manifest_path.parent.name:
            raise ValueError(f"Pull ID does not match directory: {manifest_path}")
        snapshot = manifest_path.parent / "config.json"
        if snapshot.exists() and sha256_bytes(snapshot.read_bytes()) != config["_sha256"]:
            raise ValueError(f"Configuration snapshot changed: {snapshot}")
        if set(manifest["series"]) != set(expected):
            raise ValueError(f"Incomplete or unexpected series in {manifest_path}")
        for key, entry in manifest["series"].items():
            if entry["status"] != "ok":
                raise ValueError(f"Incomplete pull: {key} in {manifest_path}")
            if (entry["geo"], entry["label"], entry["query"]) != expected[key]:
                raise ValueError(f"Series specification differs from config: {key}")
            if entry["file"] != f"{entry['geo']}/{slug(entry['label'])}.json":
                raise ValueError(f"Unexpected raw filename for {key}")
            for row in verified_raw(manifest_path.parent, entry):
                records.append(dict(pull_id=manifest["pull_id"], geo=entry["geo"],
                                    label=entry["label"], query=entry["query"], **row))
    if not records:
        raise ValueError(f"No pulled series under {out / 'raw'}")
    return pd.DataFrame(records)


def prepare_region(frame):
    series = list(frame.groupby(["label", "pull_id"], sort=True))
    reference = pd.Index(series[0][1]["week"])
    if len(reference) < 2:
        raise ValueError("At least two dates are needed for assembly")
    dates = pd.to_datetime(reference)
    deltas = dates.to_series().diff().dropna().dt.days
    monthly = (dates.day == dates[0].day).all() and set(deltas).issubset({28, 29, 30, 31})
    if not ((deltas == 1).all() or (deltas == 7).all() or monthly):
        raise ValueError("Irregular date grid or unsupported resolution")
    valid = np.ones(len(reference), dtype=bool)
    for _, group in series:
        if not pd.Index(group["week"]).equals(reference):
            raise ValueError("Date grids differ between terms or pulls; missing weeks cannot be silently averaged")
        valid &= (group["has_data"] & ~group["is_partial"]).to_numpy()
    if valid.sum() < 2:
        raise ValueError("Fewer than two common usable dates after excluding unavailable or partial observations")
    return frame[frame.week.isin(set(reference[valid]))].copy(), len(reference) - int(valid.sum())


def write_trends_csv(path, series, label, geo, note):
    index = pd.to_datetime(series.index)
    delta = index.to_series().diff().dropna().dt.days
    header = "Week" if len(delta) and (delta == 7).all() else "Time"
    stream = io.StringIO()
    stream.write(f"Category: {note}\n\n")
    series.rename(f"{label}: ({geo})").to_frame().to_csv(stream, index_label=header)
    atomic_write(path, stream.getvalue().encode("utf-8"))


def cmd_assemble(args):
    config, out = load_config(args.config), Path(args.out)
    floor = getattr(args, "floor", 0.5)
    if not math.isfinite(floor) or not 0 < floor < 1:
        raise ValueError("Assembly --floor must be finite and strictly between 0 and 1")
    tidy = archive_records(config, out)
    prepared = {geo: prepare_region(frame) for geo, frame in tidy.groupby("geo")}
    summary, quality = [], {}
    for geo, (frame, excluded) in prepared.items():
        dates, pull_ids = sorted(frame.week.unique()), sorted(frame.pull_id.unique())
        folders = {"averaged": out / "averaged" / geo}
        folders.update({p: out / "by_pull" / p / geo for p in pull_ids})
        for name, folder in folders.items():
            quality[folder] = dict(schema_version=1, config_sha256=config["_sha256"], geo=geo,
                                   dates=dates, excluded_dates=excluded, log_floor=floor,
                                   aggregation="centered geometric mean" if name == "averaged" else "single pull", terms={})
        for label, group in frame.groupby("label"):
            wide = group.pivot(index="week", columns="pull_id", values="value").sort_index()
            low = group.pivot(index="week", columns="pull_id", values="low_volume").sort_index()
            if wide.isna().any().any():
                raise ValueError("Missing values remain after date alignment")
            logs = np.log(wide.astype(float).mask(low, floor).clip(lower=floor))
            logs -= logs.mean()
            mean_log = logs.mean(axis=1)
            averaged = 100 * np.exp(mean_log - mean_log.max())
            for name, folder in folders.items():
                values = averaged if name == "averaged" else wide[name].astype(float).mask(low[name], floor)
                path = folder / f"{slug(label)}.csv"
                write_trends_csv(path, values, label, geo,
                                 f"mean of {len(pull_ids)} pulls" if name == "averaged" else f"pull {name}")
                included = pull_ids if name == "averaged" else [name]
                quality[folder]["terms"][label] = dict(file=path.name, sha256=sha256_bytes(path.read_bytes()),
                    low_volume_dates_by_pull={p: list(low.index[low[p]]) for p in included})
            summary.append(dict(geo=geo, label=label, pulls=len(pull_ids), weeks=len(wide), excluded_dates=excluded,
                                share_weeks_below_1=float(low.mean().mean()),
                                max_pull_share_weeks_below_1=float(low.mean().max()),
                                median_between_pull_sd_log=float(logs.std(axis=1).median()) if len(pull_ids) > 1 else None))
        print(f"{geo}: {len(dates)} common usable dates; excluded {excluded} unavailable/partial dates")
    for folder, metadata in quality.items():
        atomic_json(folder / "trends_quality.json", metadata)
    atomic_write(out / "tidy_all_pulls.csv", tidy.to_csv(index=False).encode("utf-8"))
    atomic_write(out / "pull_summary.csv", pd.DataFrame(summary).to_csv(index=False).encode("utf-8"))
    print(f"{len(tidy):,} raw rows, {tidy.pull_id.nunique()} pulls, {tidy.geo.nunique()} regions, {tidy.label.nunique()} terms")
    print(f"Wrote tidy data, quality metadata, pull summaries and analysis CSVs under {out}")


def positive_integer(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "pull", "assemble"):
        command = sub.add_parser(name)
        command.add_argument("--config", default="study.json")
        if name != "check":
            command.add_argument("--out", default="data")
        if name == "pull":
            command.add_argument("--repeat", type=positive_integer, default=1)
        if name == "assemble":
            command.add_argument("--floor", type=float, default=0.5,
                                 help="replacement before log averaging; strictly between 0 and 1")
    args = parser.parse_args()
    try:
        {"check": cmd_check, "pull": cmd_pull, "assemble": cmd_assemble}[args.command](args)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
