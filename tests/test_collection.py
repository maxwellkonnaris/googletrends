import hashlib
import json
from pathlib import Path
import random
from importlib.metadata import version

import pandas as pd
import pytest

import trendspull
from trendspull import pull_trends
from conftest import response


def test_one_public_function():
    assert trendspull.__all__ == ["pull_trends"]


def test_installed_version_matches_metadata():
    assert trendspull.__version__ == version("trendspull")


def test_zero_partial_and_unavailable_rows_are_preserved(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(hasData=[False], isPartial=True), "WEEK")
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31")
    assert data.value.tolist() == [0, 2, 100]
    assert data.formatted_value.tolist() == ["<1", "2", "100"]
    assert not data.has_data.any() and data.is_partial.all()
    assert data.low_volume.tolist() == [True, False, False]
    client.close.assert_called_once()


def test_each_keyword_region_requested_once(fake_client):
    _, client = fake_client
    data = pull_trends(["wildfire", "smoke"], "2021-01-01", "2021-12-31", geo=["US-CA", "US-NY"])
    assert client.timeline.call_count == 4 and len(data) == 12
    assert {(call.args[0],call.args[1]) for call in client.timeline.call_args_list} == {
        ("wildfire","US-CA"),("wildfire","US-NY"),("smoke","US-CA"),("smoke","US-NY")}
    assert len(data.request_id.unique()) == 4


def test_no_automatic_date_alignment(fake_client):
    _, client = fake_client
    client.timeline.side_effect = [("{}",response(start=1609632000),"WEEK"),
                                   ("{}",response(start=1609718400),"WEEK")]
    data = pull_trends(["a","b"], "2021-01-01", "2021-12-31")
    assert len(data) == 6 and len(data.date.unique()) == 6


def test_one_observation_is_valid(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}",response(values=[7]),"DAY")
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31")
    assert data.value.tolist() == [7]


def test_empty_success_is_typed_and_reported(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=[]), "DAY")
    with pytest.warns(RuntimeWarning, match="empty timeline"):
        data = pull_trends("wildfire", "2021-01-01", "2021-12-31")
    assert data.empty and str(data.value.dtype) == "Int64"
    assert data.attrs["trendspull"]["requests"][0]["status"] == "empty"


def test_default_writes_no_files(fake_client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pull_trends("wildfire", "2021-01-01", "2021-12-31")
    assert list(tmp_path.iterdir()) == []


def test_archive_records_exact_responses_and_hashes(fake_client, tmp_path):
    _, client = fake_client
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    run = Path(data.attrs["trendspull"]["archive"])
    manifest = json.loads((run/"manifest.json").read_text())
    entry = manifest["requests"][0]
    raw = (run/entry["file"]).read_bytes()
    assert manifest["status"] == "complete" and manifest["row_count"] == 3
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    assert json.loads(raw)["multiline"] == client.timeline.return_value[1]


def test_existing_archives_never_overwritten(fake_client, tmp_path):
    first = pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    old_path = Path(first.attrs["trendspull"]["archive"])/"manifest.json"
    old_bytes = old_path.read_bytes()
    second = pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    assert first.attrs["trendspull"]["archive"] != second.attrs["trendspull"]["archive"]
    assert old_path.read_bytes() == old_bytes


def test_midway_failure_raises_and_records_failure(fake_client, tmp_path):
    _, client = fake_client
    client.timeline.side_effect = [("{}",response(),"WEEK"),RuntimeError("HTTP 429")]
    with pytest.raises(RuntimeError,match="collection failed.*'b'.*429"):
        pull_trends(["a","b"], "2021-01-01", "2021-12-31", archive=tmp_path)
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    assert [r["status"] for r in manifest["requests"]] == ["ok","failed"]
    client.close.assert_called_once()


def test_malformed_raw_is_archived_before_parse_failure(fake_client, tmp_path):
    _, client = fake_client
    client.timeline.return_value = ("{}", "<html>blocked</html>", None)
    with pytest.raises(RuntimeError,match="no JSON"):
        pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["requests"][0]["file"]
    assert manifest["status"] == "failed"


def test_interrupt_closes_session_and_marks_archive_failed(fake_client, tmp_path):
    _, client = fake_client
    client.timeline.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    client.close.assert_called_once()


def test_archive_failure_does_not_mask_http_failure(fake_client, tmp_path, monkeypatch, caplog):
    import trendspull._api as api
    _, client = fake_client
    client.timeline.side_effect = RuntimeError("HTTP 429")
    original = api._atomic
    def broken_manifest(path, payload):
        if payload.get("status") == "failed":
            raise OSError("disk full")
        return original(path, payload)
    monkeypatch.setattr(api, "_atomic", broken_manifest)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        pull_trends("wildfire", "2021-01-01", "2021-12-31", archive=tmp_path)
    assert "disk full" in caplog.text
    client.close.assert_called_once()


def test_seeded_values_are_never_transformed(fake_client):
    _, client = fake_client
    rng = random.Random(20261126)
    for _ in range(40):
        values = [rng.randrange(101) for _ in range(rng.randrange(1,30))]
        client.timeline.return_value = ("{}",response(values=values),"WEEK")
        data = pull_trends("wildfire", "2021-01-01", "2021-12-31")
        assert data.value.tolist() == values
