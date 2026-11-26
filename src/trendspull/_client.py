"""Google website requests and validation of unmodified provider observations."""
import json
import math
import random
import time

import pandas as pd
import requests

_BASE = "https://trends.google.com/trends"
_SEARCH_TYPES = {"web": "", "images": "images", "news": "news", "youtube": "youtube", "shopping": "froogle"}


def _google_json(text):
    start = text.find("{")
    if start < 0:
        raise ValueError("Google returned no JSON object")
    return json.loads(text[start:])


def _single(point, field, default=None):
    if field not in point:
        return default
    values = point[field]
    if not isinstance(values, list) or len(values) != 1:
        raise ValueError(f"Expected exactly one {field} entry per timeline observation")
    return values[0]


def _timeline(text):
    points = _google_json(text)["default"]["timelineData"]
    if not isinstance(points, list):
        raise ValueError("Google timelineData must be a list")
    rows, times = [], []
    for point in points:
        value = _single(point, "value")
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100 or int(value) != value:
            raise ValueError("Expected an integer Google index in [0, 100]")
        available, partial = _single(point, "hasData"), point.get("isPartial")
        if any(flag is not None and type(flag) is not bool for flag in (available, partial)):
            raise ValueError("Data-quality flags must be booleans when supplied")
        formatted = _single(point, "formattedValue")
        if formatted is not None and not isinstance(formatted, str):
            raise ValueError("Google formattedValue must be a string")
        timestamp = point["time"]
        if type(timestamp) not in (str, int) or isinstance(timestamp, bool):
            raise ValueError("Google time must be an integer Unix timestamp")
        timestamp = int(timestamp)
        times.append(timestamp)
        rows.append(dict(date=pd.to_datetime(timestamp, unit="s", utc=True), value=int(value),
                         formatted_value=formatted, has_data=available, is_partial=partial,
                         low_volume=value < 1 or (formatted is not None and formatted.strip() == "<1")))
    if times != sorted(set(times)):
        raise ValueError("Google timestamps must be unique and increasing")
    return rows


class _TrendsClient:
    def __init__(self, language, max_attempts, timeout):
        self.language, self.max_attempts, self.timeout = language, max_attempts, timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
            "Accept-Language": language, "Referer": f"{_BASE}/explore"})
        try:
            self._warm()
        except BaseException:
            self.session.close()
            raise

    def close(self):
        self.session.close()

    def _warm(self):
        try:
            self.session.get(f"{_BASE}/explore?geo=US", timeout=self.timeout)
        except requests.RequestException:
            pass

    def _fetch(self, url, params):
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as error:
                status, reason = None, str(error)
            else:
                if response.status_code == 200:
                    return response.text
                status, reason = response.status_code, response.reason
                if status != 429 and status < 500:
                    raise RuntimeError(f"Google HTTP {status}: {reason}")
            if attempt == self.max_attempts:
                break
            time.sleep(min(900, 30 * 2 ** (attempt - 1)) + random.uniform(0, 15))
            if status == 429:
                self.session.cookies.clear()
                self._warm()
        raise RuntimeError(f"Google request failed after {self.max_attempts} attempts: HTTP {status}, {reason}")

    def timeline(self, keyword, geo, start, end, category, search_type):
        req = dict(comparisonItem=[dict(keyword=keyword, geo=geo, time=f"{start} {end}")],
                   category=category, property=_SEARCH_TYPES[search_type])
        explore = self._fetch(f"{_BASE}/api/explore", dict(hl=self.language, tz=0, req=json.dumps(req)))
        widget = next((w for w in _google_json(explore)["widgets"] if w.get("id") == "TIMESERIES"), None)
        if widget is None:
            raise ValueError("Google returned no TIMESERIES widget")
        time.sleep(random.uniform(2, 5))
        multiline = self._fetch(f"{_BASE}/api/widgetdata/multiline",
                                dict(hl=self.language, tz=0, req=json.dumps(widget["request"]), token=widget["token"]))
        return explore, multiline, widget["request"].get("resolution")

