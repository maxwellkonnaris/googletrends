"""Compare installed, independent R and Python implementations on the same charts."""
import json
import os
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from trendspull import pull_trends, selected_proportions
from trendspull._plot import _plot_data
from conftest import response


@pytest.mark.parametrize("amplitudes", [
    [200, 100, 80, 50, 40, 20, 10],
    [59, 55, 100, 7, 4, 40, 20],
    [80, 80, 80, 80, 80, 80, 80],
])
@pytest.mark.parametrize("gap", [None, 14])
def test_native_r_matches_python(fake_client, tmp_path, amplitudes, gap):
    rscript = shutil.which("Rscript")
    probe = subprocess.run([rscript, "--vanilla", "-e",
        'quit(status=if(requireNamespace("trendspull",quietly=TRUE) && '
        '!"reticulate" %in% names(getNamespaceImports("trendspull"))) 0L else 1L)'],
        capture_output=True, text=True, timeout=30) if rscript else None
    if probe is None or probe.returncode:
        if os.environ.get("TRENDSPULL_REQUIRE_NATIVE_R"):
            pytest.fail("The installed native R package is required: " + (probe.stderr if probe else "no Rscript"))
        pytest.skip("native R is optional for Python-only installations")
    terms = list("abcdefg")
    peaks = dict(zip(terms, amplitudes))
    fractions = [.5, 1, .75, .25, .5]
    charts = {}

    def provider(group, *args):
        values = [[round(100 * peaks[t] * f / max(peaks[g] for g in group)) for t in group] for f in fractions]
        payload = response(values=values)
        # Include a flagged observation that must be retained, with missing bounds.
        raw = json.loads(payload.split("\n", 1)[1])
        raw["default"]["timelineData"][0]["isPartial"] = True
        payload = json.dumps(raw)
        charts[",".join(group)] = dict(explore="{}", multiline=payload, resolution="WEEK")
        return "{}", payload, "WEEK"

    _, client = fake_client
    client.timeline.side_effect = provider
    data = pull_trends(terms, "2021-01-01", "2021-12-31", min_gap_days=gap)
    fixture = tmp_path / "charts.json"
    fixture.write_text(json.dumps(charts))
    script = '''args <- commandArgs(TRUE)
library(trendspull)
charts <- jsonlite::fromJSON(args[1], simplifyVector=FALSE)
testthat::with_mocked_bindings({
  data <- pull_trends(letters[1:7], "2021-01-01", "2021-12-31",
    min_gap_days=if(args[3]=="none") NULL else as.integer(args[3]))
  utils::write.csv(data, file.path(args[2],"r-data.csv"),row.names=FALSE,na="")
  utils::write.csv(unname(selected_proportions(data)),file.path(args[2],"r-proportions.csv"),row.names=FALSE)
  utils::write.csv(trendspull:::.plot_data(data),file.path(args[2],"r-plot.csv"),row.names=FALSE)
  writeLines(trendspull:::.json(attr(data,"trendspull")), file.path(args[2],"r-meta.json"))
}, .new_client=function(...) list(timeline=function(keywords,...) {
    result <- charts[[paste(keywords,collapse=",")]]
    if(is.null(result)) stop("Unplanned comparison")
    result
  },close=function() NULL),
  .http_get=function(...) stop("Unexpected network"), .pause=function(...) NULL,
  .package="trendspull")'''
    env = dict(os.environ, RETICULATE_PYTHON="/nonexistent/python")
    result = subprocess.run([rscript, "--vanilla", "-e", script, str(fixture), str(tmp_path),
                             "none" if gap is None else str(gap)], env=env,
                             capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    native = pd.read_csv(tmp_path / "r-data.csv", keep_default_na=False, na_values=[""])
    assert native.keyword.tolist() == data.keyword.tolist()
    assert native.value.tolist() == data.value.tolist()
    for column in ("calibrated_value", "calibrated_lower", "calibrated_upper", "calibration_factor"):
        np.testing.assert_allclose(native[column], data[column].to_numpy(dtype=float), rtol=1e-13, equal_nan=True)
    np.testing.assert_allclose(pd.read_csv(tmp_path / "r-proportions.csv"), selected_proportions(data), rtol=1e-13)
    np.testing.assert_allclose(pd.read_csv(tmp_path / "r-plot.csv").display_value, _plot_data(data).display_value, rtol=1e-13)
    meta = json.loads((tmp_path / "r-meta.json").read_text())
    assert len(meta["requests"]) == len(data.attrs["trendspull"]["requests"])
    r_terms = meta["calibration"]["geographies"][""]["terms"]
    py_terms = data.attrs["trendspull"]["calibration"]["geographies"][""]["terms"]
    for term in terms:
        assert r_terms[term]["path"] == py_terms[term]["path"]
