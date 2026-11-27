import json
from pathlib import Path
import random

import pytest

from trendspull import pull_trends
from conftest import response


@pytest.mark.parametrize("gap,indices", [(None, list(range(10))), (1, list(range(10))),
                                       (7, list(range(10))), (8, [0, 2, 4, 6, 8]),
                                       (28, [0, 4, 8]), (10000, [0])])
def test_spacing_selects_whole_comparison_dates_without_rescaling(fake_client, gap, indices):
    _, client = fake_client
    values = [[100 - i * 10, 20 - i] for i in range(10)]
    client.timeline.return_value = ("{}", response(values=values, hasData=[True, False], isPartial=True), "WEEK")
    data = pull_trends(["wildfire", "smoke"], "2021-01-01", "2021-12-31", min_gap_days=gap)
    assert data.value.tolist() == [v for i in indices for v in values[i]]
    assert data.keyword.tolist() == ["wildfire", "smoke"] * len(indices)
    assert data.has_data.tolist() == [True, False] * len(indices) and data.is_partial.all()
    assert data.request_id.nunique() == 1 and client.timeline.call_count == 1
    assert data.attrs["trendspull"]["settings"]["min_gap_days"] == gap
    entry = data.attrs["trendspull"]["requests"][0]
    assert entry["provider_row_count"] == 20 and entry["row_count"] == len(data)


def test_gap_uses_elapsed_time_not_number_of_rows(fake_client):
    _, client = fake_client
    raw = json.loads(response(values=[100, 90, 80, 70, 60]).split("\n", 1)[1])
    days = [0, 1, 29, 30, 59]
    for row, day in zip(raw["default"]["timelineData"], days):
        row["time"] = str(1609632000 + day * 86400)
    client.timeline.return_value = ("{}", json.dumps(raw), "DAY")
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31", min_gap_days=30)
    assert data.value.tolist() == [100, 70]


def test_hourly_values_use_full_24_hour_days(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=list(range(50)), step=3600), "HOUR")
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31", min_gap_days=1)
    assert data.value.tolist() == [0, 24, 48]
    assert data.date.diff().dropna().dt.total_seconds().eq(86400).all()


def test_spacing_is_anchored_separately_for_each_geography(fake_client):
    _, client = fake_client
    client.timeline.side_effect = [("{}", response(values=list(range(10))), "WEEK"),
                                   ("{}", response(values=list(range(10)), start=1609718400), "WEEK")]
    data = pull_trends("wildfire", "2021-01-01", "2021-12-31", geo=["US-CA", "US-NY"], min_gap_days=28)
    assert data.value.tolist() == [0, 4, 8] * 2
    starts = data.groupby("geo").date.min()
    assert (starts["US-NY"] - starts["US-CA"]).total_seconds() == 86400


def test_full_raw_response_is_archived_before_selection(fake_client, tmp_path):
    _, client = fake_client
    text = response(values=[[20, 10], [100, 50], [30, 15], [40, 20], [50, 25]])
    client.timeline.return_value = ("{}", text, "WEEK")
    data = pull_trends(["wildfire", "smoke"], "2021-01-01", "2021-12-31", min_gap_days=28, archive=tmp_path)
    assert data.value.tolist() == [20, 10, 50, 25]  # The omitted peak must not cause rescaling.
    run = Path(data.attrs["trendspull"]["archive"])
    manifest = json.loads((run / "manifest.json").read_text())
    entry = manifest["requests"][0]
    assert json.loads((run / entry["file"]).read_text())["multiline"] == text
    assert entry["provider_row_count"] == 10 and entry["row_count"] == 4
    assert manifest["settings"]["min_gap_days"] == 28 and manifest["row_count"] == 4


def test_spacing_does_not_hide_bad_values_on_omitted_dates(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=[100, 101, 20]), "WEEK")
    with pytest.raises(RuntimeError, match="integer Google index"):
        pull_trends("wildfire", "2021-01-01", "2021-12-31", min_gap_days=28)


def test_empty_timeline_with_spacing_remains_typed_and_reported(fake_client):
    _, client = fake_client
    client.timeline.return_value = ("{}", response(values=[]), "WEEK")
    with pytest.warns(RuntimeWarning, match="empty timeline"):
        data = pull_trends("wildfire", "2021-01-01", "2021-12-31", min_gap_days=28)
    assert data.empty and str(data.value.dtype) == "Int64"
    assert data.attrs["trendspull"]["requests"][0]["provider_row_count"] == 0


def test_seeded_irregular_grids_have_at_least_the_requested_gap(fake_client):
    _, client = fake_client
    rng = random.Random(20261127)
    for _ in range(30):
        gap = rng.randrange(1, 60)
        days = sorted(rng.sample(range(300), 30))
        raw = json.loads(response(values=list(range(30))).split("\n", 1)[1])
        for row, day in zip(raw["default"]["timelineData"], days):
            row["time"] = str(1609632000 + day * 86400)
        client.timeline.return_value = ("{}", json.dumps(raw), "DAY")
        data = pull_trends("wildfire", "2021-01-01", "2021-12-31", min_gap_days=gap)
        assert data.value.iloc[0] == 0
        assert data.date.diff().dropna().dt.total_seconds().ge(gap * 86400).all()
        assert data.value.is_monotonic_increasing
