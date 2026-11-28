from copy import deepcopy

import pandas as pd
import pytest

from trendspull import pull_trends, selected_proportions
from conftest import response
from test_calibration import collect


@pytest.fixture
def data(fake_client):
    fake_client[1].timeline.return_value = ("{}", response(values=[[100, 20], [50, 0], [25, 5]]), "WEEK")
    return pull_trends(["smoke", "wildfire"], "2021-01-01", "2021-12-31", geo="US-CA")


def test_raw_matrix_values_order_dates_zeros_and_input_preservation(data):
    before, attrs = data.copy(deep=True), deepcopy(data.attrs)
    result = selected_proportions(data)
    assert result.shape == (2, 3) and result.index.tolist() == ["smoke", "wildfire"]
    assert result.index.dtype == object
    assert result.columns.equals(pd.DatetimeIndex(data.date.unique(), name="date"))
    assert result.loc["smoke"].tolist() == pytest.approx([5 / 6, 1, 5 / 6])
    assert result.loc["wildfire"].tolist() == pytest.approx([1 / 6, 0, 1 / 6])
    assert result.sum().tolist() == pytest.approx([1, 1, 1])
    assert result.attrs["selected_proportions"]["value_column"] == "value"
    pd.testing.assert_frame_equal(data, before)
    assert data.attrs == attrs


def test_gtab_uses_calibrated_values_across_source_charts(fake_client):
    data = collect(fake_client)
    result = selected_proportions(data)
    expected = data.pivot(index="keyword", columns="date", values="calibrated_value")
    expected = expected.div(expected.sum(axis=0), axis=1)
    expected.index = pd.Index(list(expected.index), dtype=object, name="keyword")
    assert data.request_id.nunique() > 1
    pd.testing.assert_frame_equal(result, expected, check_dtype=False)
    assert result.attrs["selected_proportions"]["value_column"] == "calibrated_value"


def test_explicit_subset_and_single_geography(data):
    one = data.loc[data.keyword.eq("wildfire") & data.value.gt(0)].copy()
    result = selected_proportions(one)
    assert result.shape == (1, 2) and result.eq(1).all().all()


def test_multiple_geographies_require_explicit_selection(fake_client):
    fake_client[1].timeline.return_value = ("{}", response(values=[[100, 20], [50, 10]]), "WEEK")
    data = pull_trends(["a", "b"], "2021-01-01", "2021-12-31", geo=["US", "GB"])
    with pytest.raises(ValueError, match="one geography"):
        selected_proportions(data)
    assert selected_proportions(data.loc[data.geo.eq("GB")]).shape == (2, 2)


def test_fixed_rescaling_cancels_and_large_sums_do_not_overflow(data):
    first = selected_proportions(data)
    scaled = data.copy()
    scaled["value"] = scaled.value.astype(float) * 1e305
    result = selected_proportions(scaled)
    pd.testing.assert_frame_equal(result, first)
    scaled["value"] = 1e308
    assert selected_proportions(scaled).eq(0.5).all().all()


@pytest.mark.parametrize("field", ["date", "keyword", "geo", "request_id", "value"])
def test_missing_columns_rejected(data, field):
    with pytest.raises(ValueError, match="requires nonmissing"):
        selected_proportions(data.drop(columns=field))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, "20", True, complex(1, 2)])
def test_invalid_values_rejected(data, bad):
    data["value"] = data.value.astype(object)
    data.loc[data.index[0], "value"] = bad
    with pytest.raises(ValueError):
        selected_proportions(data)


def test_numeric_nonfinite_and_negative_values_rejected(data):
    for bad in (float("inf"), float("-inf"), -1.0):
        candidate = data.copy()
        candidate["value"] = candidate.value.astype(float)
        candidate.loc[candidate.index[0], "value"] = bad
        with pytest.raises(ValueError, match="finite nonnegative"):
            selected_proportions(candidate)


def test_missing_grid_and_duplicates_are_not_aggregated(data):
    with pytest.raises(ValueError, match="same dates"):
        selected_proportions(data.iloc[1:])
    repeated = pd.concat([data, data.iloc[:1]])
    with pytest.raises(ValueError, match="once per date"):
        selected_proportions(repeated)


def test_all_zero_date_fails_without_modifying_input(data):
    data.loc[data.date.eq(data.date.iloc[0]), "value"] = 0
    before = data.copy(deep=True)
    with pytest.raises(ValueError, match="positive total"):
        selected_proportions(data)
    pd.testing.assert_frame_equal(data, before)


def test_shuffled_input_sorts_dates_and_preserves_encountered_term_order(data):
    shuffled = data.iloc[::-1]
    result = selected_proportions(shuffled)
    assert result.index.tolist() == ["wildfire", "smoke"]
    assert result.columns.is_monotonic_increasing


def test_missing_provenance_and_foreign_requests_rejected(data):
    lost = data.copy()
    lost.attrs.clear()
    with pytest.raises(ValueError, match="metadata"):
        selected_proportions(lost)
    data.loc[data.index[0], "request_id"] = "another-call"
    with pytest.raises(ValueError, match="one pull_trends call"):
        selected_proportions(data)


@pytest.mark.parametrize("key, value", [("calibration", None), ("requests", None), ("requests", [{}])])
def test_malformed_metadata_rejected(data, key, value):
    data.attrs["trendspull"][key] = value
    with pytest.raises(ValueError):
        selected_proportions(data)


def test_flagged_observations_are_not_silently_dropped(data):
    data["is_partial"] = True
    data["has_data"] = False
    assert selected_proportions(data).shape == (2, 3)


def test_empty_frame_and_non_frame_rejected(data):
    with pytest.raises(ValueError, match="nonempty"):
        selected_proportions(data.iloc[:0])
    with pytest.raises(TypeError, match="DataFrame"):
        selected_proportions([[1, 2]])


def test_naive_dates_and_duplicate_columns_rejected(data):
    naive = data.copy()
    naive["date"] = naive.date.dt.tz_localize(None)
    with pytest.raises(ValueError, match="UTC"):
        selected_proportions(naive)
    with pytest.raises(ValueError, match="unique column"):
        selected_proportions(pd.concat([data, data[["value"]]], axis=1))
