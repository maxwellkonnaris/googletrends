from copy import deepcopy
import io
import sys
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
import numpy as np
import pandas as pd
import pytest

from trendspull import pull_trends, plot_trends
from trendspull._plot import _plot_data
from conftest import response
from test_calibration import collect


@pytest.fixture
def data(fake_client):
    fake_client[1].timeline.return_value = ("{}", response(values=[[100, 20], [50, 0], [25, 5]]), "WEEK")
    return pull_trends(["smoke", "wildfire"], "2021-01-01", "2021-12-31", geo="US-CA")


def test_common_scale_preserves_values_zeros_flags_dates_and_input(data):
    before, attrs = data.copy(deep=True), deepcopy(data.attrs)
    data["is_partial"] = True
    fig = plot_trends(data)
    try:
        assert len(fig.axes) == 3
        assert [x.get_label() for x in fig.axes[0].lines] == ["smoke", "wildfire"]
        assert list(fig.axes[0].lines[0].get_ydata()) == [100, 50, 25]
        assert list(fig.axes[0].lines[1].get_ydata()) == [20, 0, 5]
        for ax in fig.axes:
            assert ax.get_ylim() == (0, 104)
        assert [ax.get_title(loc="left") for ax in fig.axes[1:]] == ["smoke", "wildfire"]
        assert len(fig.axes[0].lines[0].get_xdata()) == 3
        assert "all supplied terms and dates" in fig.texts[-1].get_text()
        stream = io.BytesIO()
        fig.savefig(stream, format="pdf")
        assert stream.getvalue().startswith(b"%PDF")
    finally:
        plt.close(fig)
    pd.testing.assert_frame_equal(data.drop(columns="is_partial"), before.drop(columns="is_partial"))
    assert data.attrs == attrs and data.is_partial.all()


def test_gtab_uses_calibrated_values_and_one_global_maximum(fake_client):
    data = collect(fake_client)
    result = _plot_data(data)
    expected = data.calibrated_value / data.calibrated_value.max() * 100
    actual = result.set_index(["keyword", "date"]).display_value
    for row, target in zip(data.itertuples(), expected):
        assert actual.loc[row.keyword, row.date] == pytest.approx(target)
    assert result.attrs["value_column"] == "calibrated_value"
    assert result.display_value.max() == 100
    fig = plot_trends(data)
    try:
        assert len(fig.axes) == 8
        first, seventh = fig.axes[0].lines[0], fig.axes[0].lines[6]
        assert first.get_color() == seventh.get_color()
        assert first.get_linestyle() != seventh.get_linestyle()
        fig.canvas.draw()
    finally:
        plt.close(fig)


def test_extreme_values_do_not_overflow_or_collapse_small_peak(data):
    for scale in (1e305, 1e-310):
        changed = data.copy()
        changed["value"] = changed.value.astype(float) * scale
        display = _plot_data(changed).display_value
        assert np.isfinite(display).all() and display.max() == 100
        assert display.tolist() == pytest.approx([100, 50, 25, 20, 0, 5])


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, None])
def test_invalid_panel_columns(data, bad):
    with pytest.raises(ValueError, match="positive integer"):
        plot_trends(data, ncol=bad)


def test_all_zero_data_rejected_but_zero_week_is_retained(data):
    data.loc[data.date.eq(data.date.iloc[0]), "value"] = 0
    assert (_plot_data(data).display_value == 0).sum() == 3
    data["value"] = 0
    with pytest.raises(ValueError, match="positive value"):
        plot_trends(data)


def test_missing_provenance_incomplete_grid_and_mixed_geography_rejected(data):
    for altered in (data.iloc[1:].copy(), pd.concat([data, data.iloc[:1]])):
        with pytest.raises(ValueError):
            plot_trends(altered)
    data.loc[data.index[0], "geo"] = "GB"
    with pytest.raises(ValueError, match="one geography"):
        plot_trends(data)
    data.attrs.clear()
    with pytest.raises(ValueError, match="metadata"):
        plot_trends(data)


def test_single_date_single_term_has_visible_marker(data):
    one = data.iloc[:1]
    fig = plot_trends(one)
    try:
        assert len(fig.axes) == 2
        assert fig.axes[0].lines[0].get_marker() == "o"
        fig.canvas.draw()
    finally:
        plt.close(fig)


def test_missing_optional_matplotlib_is_actionable(data):
    with patch.dict(sys.modules, {"matplotlib": None}):
        with pytest.raises(ImportError, match=r"trendspull\[plot\]"):
            plot_trends(data)
