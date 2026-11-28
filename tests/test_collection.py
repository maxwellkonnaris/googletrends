import hashlib
import json
from pathlib import Path
import random
from importlib.metadata import version

import pytest

import trendspull
from trendspull import pull_trends
from conftest import response


def test_public_functions():
    assert trendspull.__all__ == ["pull_trends", "selected_proportions", "plot_trends"]


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


def test_keywords_share_one_request_and_scale_per_region(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=[[100, 20], [50, 0], [25, 5]]), "WEEK")
    data = pull_trends(["wildfire", "smoke"], "2021-01-01", "2021-12-31", geo=["US-CA", "US-NY"])
    assert client.timeline.call_count == 2 and len(data) == 12
    assert [(call.args[0], call.args[1]) for call in client.timeline.call_args_list] == [
        (["wildfire", "smoke"], "US-CA"), (["wildfire", "smoke"], "US-NY")]
    assert len(data.request_id.unique()) == 2
    for _, comparison in data.groupby("request_id"):
        assert comparison.keyword.tolist() == ["wildfire", "smoke"] * 3
        assert comparison.value.tolist() == [100, 20, 50, 0, 25, 5]
        assert comparison.groupby("keyword").request_id.nunique().tolist() == [1, 1]
    assert "shared keyword scale" in data.attrs["trendspull"]["normalization"]


def test_no_automatic_date_alignment(fake_client):
    _, client = fake_client
    client.timeline.side_effect = [("{}",response(start=1609632000),"WEEK"),
                                   ("{}",response(start=1609718400),"WEEK")]
    data = pull_trends("a", "2021-01-01", "2021-12-31", geo=["US-CA", "US-NY"])
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
    with pytest.raises(RuntimeError,match="collection failed.*US-NY.*429"):
        pull_trends("a", "2021-01-01", "2021-12-31", geo=["US-CA", "US-NY"], archive=tmp_path)
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


def test_comparison_values_order_and_flags_survive_archive(fake_client, tmp_path):
    _, client = fake_client
    keywords = ['煙, "smoke"', "wildfire", "/m/0abc12", "asthma", "air quality"]
    rng = random.Random(20261126)
    values = [[rng.randrange(101) for _ in keywords] for _ in range(40)]
    values[0] = [0, 100, 20, 1, 5]
    client.timeline.return_value = ("{}", response(values=values, hasData=[False, True, True, True, False],
                                                  isPartial=True), "WEEK")
    data = pull_trends(keywords, "2021-01-01", "2021-12-31", archive=tmp_path)
    client.timeline.assert_called_once_with(keywords, "", "2021-01-01", "2021-12-31", 0, "web")
    assert data.value.tolist() == [v for point in values for v in point]
    assert data.keyword.tolist() == keywords * len(values)
    assert data.has_data.tolist() == [False, True, True, True, False] * len(values)
    assert data.is_partial.all() and data.request_id.nunique() == 1
    assert data.formatted_value.iloc[0] == "<1"
    manifest = json.loads((Path(data.attrs["trendspull"]["archive"]) / "manifest.json").read_text())
    assert manifest["requests"][0]["keywords"] == keywords
    assert manifest["requests"][0]["row_count"] == 200
    assert "shared keyword scale" in manifest["normalization"]


def test_empty_joint_comparison_does_not_fall_back_to_individual_requests(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=[]), "WEEK")
    with pytest.warns(RuntimeWarning, match="empty timeline"):
        data = pull_trends(["wildfire", "smoke"], "2021-01-01", "2021-12-31")
    assert data.empty and client.timeline.call_count == 1
    assert data.attrs["trendspull"]["requests"][0]["keywords"] == ["wildfire", "smoke"]
