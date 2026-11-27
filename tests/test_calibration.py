import hashlib
import json
from pathlib import Path
import random

import pandas as pd
import pytest

from trendspull import pull_trends
from trendspull._gtab import _paths
from conftest import response


TERMS = list("abcdefg")
AMPLITUDES = dict(zip(TERMS, [200, 100, 80, 50, 40, 20, 10]))


def provider(amplitudes, **overrides):
    def timeline(terms, *args):
        peak = max(amplitudes[term] for term in terms)
        values = [[round(100 * amplitudes[term] * fraction / peak) for term in terms]
                  for fraction in (0.5, 1, 0.75, 0.25, 0.5)]
        return "{}", response(values=values, **overrides), "WEEK"
    return timeline


def collect(fake_client, terms=TERMS, **options):
    _, client = fake_client
    client.timeline.side_effect = provider(AMPLITUDES)
    return pull_trends(terms, "2021-01-01", "2021-12-31", delay=(0, 0), **options)


def test_auto_up_to_five_preserves_the_existing_raw_contract(fake_client):
    data = collect(fake_client, TERMS[:5])
    assert "calibrated_value" not in data
    assert data.attrs["trendspull"]["calibration"]["method"] == "none"
    assert fake_client[1].timeline.call_count == 1


def test_more_than_five_uses_connected_gtab_peak_ratios(fake_client, tmp_path):
    data = collect(fake_client, archive=tmp_path)
    assert len(data) == 35 and not data.duplicated(["date", "keyword"]).any()
    assert data.groupby("date").keyword.apply(list).tolist() == [TERMS] * 5
    assert fake_client[1].timeline.call_count == 3
    assert all(len(call.args[0]) <= 5 for call in fake_client[1].timeline.call_args_list)
    for term, series in data.groupby("keyword", sort=False):
        target = AMPLITUDES[term] / AMPLITUDES["a"]
        assert series.calibrated_value.max() == pytest.approx(target, abs=0.005)
        assert series.calibrated_lower.le(series.calibrated_value).all()
        assert series.calibrated_upper.ge(series.calibrated_value).all()
        assert (series.value * series.calibration_factor).equals(series.calibrated_value)
    meta = data.attrs["trendspull"]
    assert meta["calibration"]["method"] == "gtab"
    details = meta["calibration"]["geographies"][""]["terms"]
    assert len(details["g"]["path"]) > 2  # a and g never appeared together.
    assert data.calibration_reference.eq("a").all()
    run = Path(meta["archive"])
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["calibration"] == meta["calibration"]
    assert sum(r["row_count"] for r in manifest["requests"]) == len(data)
    assert sum(r["provider_row_count"] for r in manifest["requests"]) == 75
    for entry in meta["requests"]:
        payload = (run / entry["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        points = json.loads(json.loads(payload)["multiline"].split("\n", 1)[1])["default"]["timelineData"]
        for row in data.loc[data.request_id.eq(entry["request_id"])].itertuples():
            i = entry["keywords"].index(row.keyword)
            point = next(p for p in points if int(p["time"]) == int(row.date.timestamp()))
            assert row.value == point["value"][i]


def test_forced_small_gtab_comparison_matches_direct_scaling(fake_client):
    data = collect(fake_client, TERMS[:5], calibration="gtab")
    assert fake_client[1].timeline.call_count == 1
    assert data.calibrated_value.tolist() == pytest.approx((data.value / 100).tolist())


def test_custom_reference_can_produce_values_above_one(fake_client):
    data = collect(fake_client, reference="d")
    assert data.calibration_reference.eq("d").all()
    assert data.loc[data.keyword.eq("d"), "calibrated_value"].max() == pytest.approx(1)
    assert data.calibrated_value.max() == pytest.approx(4)


def test_single_reference_and_unicode_terms(fake_client):
    _, client = fake_client
    client.timeline.side_effect = provider({'煙, "fire"': 20})
    data = pull_trends('煙, "fire"', "2021-01-01", "2021-12-31", calibration="gtab")
    assert data.calibrated_value.max() == 1
    assert data.calibration_reference.eq('煙, "fire"').all()


def test_extra_anchors_are_used_but_not_returned(fake_client):
    _, client = fake_client
    client.timeline.side_effect = provider(dict(AMPLITUDES, bridge=60))
    data = pull_trends(TERMS, "2021-01-01", "2021-12-31", anchors=["bridge", "a"], reference="bridge")
    assert set(data.keyword) == set(TERMS)
    assert data.calibration_reference.eq("bridge").all()
    assert client.timeline.call_args.args[0][-1] == "bridge"


def test_minimum_rounding_error_path_can_have_more_edges():
    graph = {"ref": {"target": (1, 0.1, 0.05, 0.2, "bad"),
                      "bridge": (0.1, 0.5, 0.48, 0.52, "one")},
             "bridge": {"target": (0.1, 0.2, 0.19, 0.21, "two")}, "target": {}}
    path = _paths(graph, "ref")["target"]
    assert path[1] == pytest.approx(0.1)
    assert path[4] == ["ref", "bridge", "target"]
    assert path[5] == ["one", "two"]


def test_calibration_precedes_spacing_even_when_the_peak_is_omitted(fake_client):
    full = collect(fake_client)
    spaced = collect(fake_client, min_gap_days=28)
    assert len(spaced) == 14
    retained = full.loc[full.date.isin(spaced.date)].reset_index(drop=True)
    pd.testing.assert_frame_equal(spaced.drop(columns=["retrieved_at", "request_id"]),
                                  retained.drop(columns=["retrieved_at", "request_id"]))
    assert spaced.loc[spaced.keyword.eq("a"), "calibrated_value"].max() == 0.5


@pytest.mark.parametrize("overrides", [dict(isPartial=True), dict(hasData=[False] * 5)])
def test_known_bad_quality_cannot_supply_calibration_peaks(fake_client, overrides):
    _, client = fake_client
    client.timeline.side_effect = provider(AMPLITUDES, **overrides)
    with pytest.raises(RuntimeError, match="no reliable anchor path"):
        pull_trends(TERMS, "2021-01-01", "2021-12-31")
    client.close.assert_called_once()


def test_zero_partial_and_unavailable_rows_keep_raw_flags_but_no_bounds(fake_client):
    _, client = fake_client
    raw = json.loads(response(values=[[100, 20], [0, 10], [40, 8], [20, 4]]).split("\n", 1)[1])
    raw["default"]["timelineData"][1]["hasData"] = [False, False]
    raw["default"]["timelineData"][2]["isPartial"] = True
    client.timeline.return_value = ("{}", json.dumps(raw), "WEEK")
    data = pull_trends(["a", "b"], "2021-01-01", "2021-12-31", calibration="gtab")
    assert data.value.tolist() == [100, 20, 0, 10, 40, 8, 20, 4]
    assert data.iloc[2:6].calibrated_lower.isna().all()
    assert data.iloc[2].calibrated_value == 0
    assert data.iloc[0].calibrated_lower == 1


def test_all_zero_term_fails_with_a_failed_archive(fake_client, tmp_path):
    _, client = fake_client
    client.timeline.side_effect = provider(dict(AMPLITUDES, g=0))
    with pytest.raises(RuntimeError, match="no reliable anchor path.*g"):
        pull_trends(TERMS, "2021-01-01", "2021-12-31", archive=tmp_path)
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "failed" and len(manifest["requests"]) > 3
    client.close.assert_called_once()


def test_very_different_popularities_fail_instead_of_inventing_a_scale(fake_client):
    _, client = fake_client
    client.timeline.side_effect = provider(dict(AMPLITUDES, g=0.1))
    with pytest.raises(RuntimeError, match="no reliable anchor path"):
        pull_trends(TERMS, "2021-01-01", "2021-12-31")


def test_adaptive_pairs_rescue_terms_rounded_small_in_five_term_charts(fake_client):
    _, client = fake_client
    amplitudes = dict(zip(TERMS, [59, 55, 100, 7, 4, 40, 20]))
    client.timeline.side_effect = provider(amplitudes)
    data = pull_trends(TERMS, "2021-01-01", "2021-12-31")
    assert client.timeline.call_count > 3
    assert any(len(c.args[0]) == 2 for c in client.timeline.call_args_list)
    for term in ("d", "e"):
        assert data.loc[data.keyword.eq(term), "calibrated_value"].max() == pytest.approx(amplitudes[term] / 59, rel=0.06)


def test_adaptive_requests_obey_the_total_budget_and_archive_failure(fake_client, tmp_path):
    _, client = fake_client
    client.timeline.side_effect = provider(dict(AMPLITUDES, g=0.1))
    with pytest.raises(RuntimeError, match="reached max_comparisons=3"):
        pull_trends(TERMS, "2021-01-01", "2021-12-31", max_comparisons=3, archive=tmp_path)
    assert client.timeline.call_count == 3
    manifest = json.loads(next(tmp_path.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "failed"


@pytest.mark.parametrize("kind", ["dates", "resolution", "empty"])
def test_inconsistent_timelines_are_not_silently_aligned(fake_client, kind):
    _, client = fake_client
    normal = provider(AMPLITUDES)
    def changed(terms, *args):
        explore, text, resolution = normal(terms)
        if terms[0] == "b":
            raw = json.loads(text.split("\n", 1)[1])
            if kind == "dates":
                raw["default"]["timelineData"].pop()
            elif kind == "empty":
                raw["default"]["timelineData"] = []
            else:
                resolution = "DAY"
            text = json.dumps(raw)
        return explore, text, resolution
    client.timeline.side_effect = changed
    if kind == "empty":
        with pytest.warns(RuntimeWarning, match="empty timeline"), pytest.raises(RuntimeError, match="empty comparison"):
            pull_trends(TERMS, "2021-01-01", "2021-12-31")
    else:
        with pytest.raises(RuntimeError, match="identical timestamps and resolution"):
            pull_trends(TERMS, "2021-01-01", "2021-12-31")


def test_each_geography_has_its_own_bank_and_reference_peak(fake_client):
    data = collect(fake_client, geo=["US-CA", "US-NY"])
    assert len(data) == 70 and fake_client[1].timeline.call_count == 6
    assert set(data.attrs["trendspull"]["calibration"]["geographies"]) == {"US-CA", "US-NY"}
    assert data.groupby(["geo", "keyword"]).request_id.nunique().eq(1).all()


def test_seeded_latent_series_fall_in_conditional_rounding_bounds(fake_client):
    _, client = fake_client
    rng = random.Random(20261127)
    for _ in range(20):
        amplitudes = dict(zip(TERMS, [rng.randrange(20, 90) for _ in TERMS]))
        fractions = [rng.uniform(0.3, 0.9) for _ in range(9)] + [1.0]
        def timeline(terms, *args):
            peak = max(amplitudes[t] for t in terms)
            values = [[round(100 * amplitudes[t] * f / peak) for t in terms] for f in fractions]
            return "{}", response(values=values), "WEEK"
        client.timeline.side_effect = timeline
        data = pull_trends(TERMS, "2021-01-01", "2021-12-31")
        truth = [amplitudes[row.keyword] * fractions[i // len(TERMS)] / amplitudes["a"]
                 for i, row in enumerate(data.itertuples())]
        assert (data.calibrated_lower <= pd.Series(truth) + 1e-12).all()
        assert (data.calibrated_upper >= pd.Series(truth) - 1e-12).all()
