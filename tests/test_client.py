import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import trendspull._client as module
from conftest import response


def client_with(statuses):
    client = object.__new__(module._TrendsClient)
    client.max_attempts, client.timeout = len(statuses), 12
    client.session = SimpleNamespace(get=Mock(side_effect=statuses), cookies=Mock())
    client._warm = Mock()
    return client


@pytest.mark.parametrize("statuses, pauses", [([200], 0), ([503, 200], 1), ([429, 200], 1)])
def test_retries_only_before_another_attempt(statuses, pauses):
    client = client_with([SimpleNamespace(status_code=s, reason="test", text="ok") for s in statuses])
    assert client._fetch("https://example.invalid", {}) == "ok"
    assert module.time.sleep.call_count == pauses
    assert client._warm.call_count == (1 if 429 in statuses else 0)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_final_failure_never_sleeps(status):
    client = client_with([SimpleNamespace(status_code=status, reason="test")])
    with pytest.raises(RuntimeError):
        client._fetch("https://example.invalid", {})
    module.time.sleep.assert_not_called()


def test_timeout_is_retried_and_bounded():
    client = client_with([requests.Timeout("test"), requests.Timeout("test")])
    with pytest.raises(RuntimeError, match="2 attempts"):
        client._fetch("https://example.invalid", {})
    assert client.session.get.call_count == 2
    assert module.time.sleep.call_count == 1
    assert all(call.kwargs["timeout"] == 12 for call in client.session.get.call_args_list)


def test_request_chain_and_search_property(monkeypatch):
    keywords = ["wildfire", "smoke"]
    widget = dict(id="TIMESERIES", token="test-token", request=dict(resolution="WEEK"))
    responses = [SimpleNamespace(status_code=429), SimpleNamespace(status_code=200,
        text=")]}'\n" + json.dumps(dict(widgets=[widget], keywords=[dict(keyword=k) for k in keywords]))),
        SimpleNamespace(status_code=200, text=response(values=[[100, 20], [40, 0]]))]
    session = SimpleNamespace(headers={}, get=Mock(side_effect=responses), close=Mock())
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    client = module._TrendsClient("en-US", 1, 12)
    explore, multiline, resolution = client.timeline(keywords, "US-CA", "2021-01-01", "2021-12-31", 0, "shopping")
    calls = session.get.call_args_list
    payload = json.loads(calls[1].kwargs["params"]["req"])
    assert payload["comparisonItem"] == [dict(keyword=k, geo="US-CA", time="2021-01-01 2021-12-31") for k in keywords]
    assert payload["property"] == "froogle"
    assert calls[2].kwargs["params"]["token"] == "test-token"
    assert calls[2].kwargs["params"]["tz"] == 0
    assert json.loads(calls[2].kwargs["params"]["req"]) == widget["request"]
    assert resolution == "WEEK" and len(module._timeline(multiline, keywords)) == 4
    client.close()
    session.close.assert_called_once()


def test_session_closed_if_warmup_interrupted(monkeypatch):
    session = SimpleNamespace(headers={}, get=Mock(side_effect=KeyboardInterrupt), close=Mock())
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    with pytest.raises(KeyboardInterrupt):
        module._TrendsClient("en-US", 1, 12)
    session.close.assert_called_once()


def test_hourly_timestamps_are_not_collapsed_to_dates():
    rows = module._timeline(response(step=3600), ["wildfire"])
    assert len({row["date"] for row in rows}) == 3
    assert (rows[1]["date"] - rows[0]["date"]).total_seconds() == 3600


def test_missing_flags_remain_unknown():
    raw = module._google_json(response())
    for row in raw["default"]["timelineData"]:
        for key in ("hasData", "isPartial", "formattedValue"):
            row.pop(key)
    rows = module._timeline(json.dumps(raw), ["wildfire"])
    assert all(row["has_data"] is None and row["is_partial"] is None and row["formatted_value"] is None for row in rows)


@pytest.mark.parametrize("change", [
    lambda rows: rows[0].update(value=[]),
    lambda rows: rows[0].update(value=[1, 2]),
    lambda rows: rows[0].update(value=[True]),
    lambda rows: rows[0].update(value=[-1]),
    lambda rows: rows[0].update(value=[101]),
    lambda rows: rows[0].update(value=[0.5]),
    lambda rows: rows[0].update(value=[None]),
    lambda rows: rows[0].update(value=[float("nan")]),
    lambda rows: rows[0].update(hasData=["true"]),
    lambda rows: rows[0].update(isPartial="false"),
    lambda rows: rows[0].update(formattedValue=[3]),
    lambda rows: rows[0].update(time=True),
    lambda rows: rows[0].update(time="not-a-time"),
    lambda rows: rows[1].update(time=rows[0]["time"]),
    lambda rows: rows.reverse(),
])
def test_malformed_timeline_rejected(change):
    raw = module._google_json(response())
    change(raw["default"]["timelineData"])
    with pytest.raises((ValueError, TypeError, KeyError)):
        module._timeline(json.dumps(raw), ["wildfire"])


@pytest.mark.parametrize("text", ["<html>blocked</html>", "", ")]}'\n{bad json}"])
def test_non_json_provider_responses_rejected(text):
    with pytest.raises(ValueError):
        module._google_json(text)


@pytest.mark.parametrize("field", ["value", "hasData", "formattedValue"])
@pytest.mark.parametrize("entries", [[], [1], [1, 2, 3]])
def test_comparison_array_lengths_must_match_keywords(field, entries):
    raw = response(values=[[100, 20]], **{field: entries})
    with pytest.raises(ValueError, match=f"Expected 2 {field} entries"):
        module._timeline(raw, ["wildfire", "smoke"])


@pytest.mark.parametrize("changes", [dict(value=[100, True]), dict(value=[100, 101]),
                                     dict(hasData=[True, "false"]), dict(formattedValue=["100", 20])])
def test_invalid_second_keyword_is_not_silently_accepted(changes):
    with pytest.raises(ValueError):
        module._timeline(response(values=[[100, 20]], **changes), ["wildfire", "smoke"])


def test_missing_comparison_flags_remain_unknown():
    raw = module._google_json(response(values=[[100, 20]]))
    point = raw["default"]["timelineData"][0]
    for field in ("hasData", "formattedValue", "isPartial"):
        point.pop(field)
    rows = module._timeline(json.dumps(raw), ["wildfire", "smoke"])
    assert [r["value"] for r in rows] == [100, 20]
    assert all(r["has_data"] is None and r["is_partial"] is None for r in rows)


@pytest.mark.parametrize("returned", [["smoke", "wildfire"], ["wildfire"], ["wildfire", "other"]])
def test_unexpected_keyword_order_or_membership_rejected(returned):
    client = object.__new__(module._TrendsClient)
    client.language = "en-US"
    client._fetch = Mock(return_value=json.dumps(dict(keywords=[dict(keyword=k) for k in returned])))
    with pytest.raises(ValueError, match="different keywords or keyword order"):
        client.timeline(["wildfire", "smoke"], "US", "2021-01-01", "2021-12-31", 0, "web")
    assert client._fetch.call_count == 1
