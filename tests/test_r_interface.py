import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import trendspull
from conftest import response


@pytest.mark.parametrize("unknown_flags", [False, True])
def test_direct_r_call_returns_data_frame_with_spacing_and_missing_flags(unknown_flags):
    rscript = shutil.which("Rscript")
    if rscript is None:
        if os.environ.get("TRENDSPULL_REQUIRE_R"):
            pytest.fail("R is required in this CI job")
        pytest.skip("R is optional for Python-only installations")
    env = dict(os.environ, RETICULATE_PYTHON=sys.executable, RETICULATE_USE_MANAGED_VENV="no",
               PYTHONPATH=str(Path(trendspull.__file__).parent.parent))
    probe = subprocess.run([rscript, "--vanilla", "-e", "quit(status=if(requireNamespace('reticulate',quietly=TRUE)) 0L else 1L)"],
                           env=env, capture_output=True, text=True, timeout=30)
    if probe.returncode:
        if env.get("TRENDSPULL_REQUIRE_R"):
            pytest.fail("reticulate is required in this CI job: " + probe.stderr)
        pytest.skip("reticulate is optional for Python-only installations")
    raw = json.loads(response(values=[[100 - 10 * i, 20 - i] for i in range(9)]).split("\n", 1)[1])
    for point in raw["default"]["timelineData"]:
        if unknown_flags:
            point.pop("hasData")
            point.pop("isPartial")
        else:
            point.update(hasData=[True, False], isPartial=True)
    setup = "\n".join([
        "from unittest.mock import Mock",
        "import requests, trendspull._api as api",
        "requests.sessions.Session.request = Mock(side_effect=AssertionError('Unexpected network access'))",
        "api.time.sleep = Mock()",
        "client = Mock()",
        f"client.timeline.return_value = ('{{}}', {json.dumps(json.dumps(raw), ensure_ascii=False)}, 'WEEK')",
        "api._TrendsClient = Mock(return_value=client)",
    ])
    script = '''args <- commandArgs(TRUE)
library(reticulate)
py_run_string(args[1])
trends <- import("trendspull")
x <- trends$pull_trends(c('煙, "smoke"', "wildfire"), "2021-01-01", "2021-12-31",
                       geo=c("US-CA", "US-NY"), min_gap_days=28L)
stopifnot(is.data.frame(x), nrow(x)==12, inherits(x$date,"POSIXct"),
          identical(x$value, rep(c(100L,20L,60L,16L,20L,12L),2)),
          identical(x$keyword, rep(c('煙, "smoke"', "wildfire"),6)),
          length(unique(x$request_id))==2)
for (g in unique(x$geo)) {
  dates <- unique(x$date[x$geo==g])
  stopifnot(as.numeric(dates[1])==1609632000,
            all(as.numeric(diff(dates),units="days")>=28))
}
if (args[2]=="unknown") {
  stopifnot(all(is.na(x$has_data)),all(is.na(x$is_partial)))
  calibrated <- trends$pull_trends(c("wildfire","smoke"),"2021-01-01","2021-12-31",
                                   min_gap_days=28L, calibration="gtab")
  stopifnot(is.numeric(calibrated$calibrated_value),
            isTRUE(all.equal(calibrated$calibrated_value, calibrated$value / 100)),
            all(calibrated$calibrated_lower <= calibrated$calibrated_value),
            all(calibrated$calibrated_upper >= calibrated$calibrated_value),
            all(calibrated$calibration_reference=="wildfire"))
} else {
  stopifnot(identical(x$has_data,rep(c(TRUE,FALSE),6)),all(x$is_partial))
}
trends_raw <- import("trendspull", convert=FALSE)
result <- trends_raw$pull_trends(c("wildfire","smoke"),"2021-01-01","2021-12-31",min_gap_days=28L)
metadata <- py_to_r(result$attrs$get("trendspull"))
stopifnot(metadata$settings$min_gap_days==28L, metadata$requests[[1]]$provider_row_count==18L,
          metadata$requests[[1]]$row_count==6L)
proportions <- as.matrix(py_to_r(trends_raw$selected_proportions(result)))
stopifnot(identical(dim(proportions),c(2L,3L)),
          identical(rownames(proportions),c("wildfire","smoke")),
          isTRUE(all.equal(as.numeric(colSums(proportions)),rep(1,3))),
          isTRUE(all.equal(as.numeric(proportions[1,]),c(100/120,60/76,20/32))))
cat("R direct call OK: data.frame, UTC instants, shared scale, spacing and flags\\n")'''
    result = subprocess.run([rscript, "--vanilla", "-e", script, setup, "unknown" if unknown_flags else "known"],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "R direct call OK" in result.stdout
