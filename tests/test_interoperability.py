import json
import shutil
import subprocess

import pandas as pd
import pytest

from trendspull import pull_trends
from conftest import response


@pytest.mark.parametrize("unknown_flags", [False, True])
@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R is optional for CSV interoperability checks")
def test_csv_readable_by_base_r(fake_client, tmp_path, unknown_flags):
    _, client = fake_client
    raw = json.loads(response().split("\n", 1)[1])
    if unknown_flags:
        for row in raw["default"]["timelineData"]:
            row.pop("hasData")
            row.pop("isPartial")
    client.timeline.return_value = ("{}",json.dumps(raw),"WEEK")
    keyword = '煙, "smoke"'
    data = pull_trends(keyword,"2021-01-01","2021-12-31",geo="US-CA")
    path = tmp_path/"trends.csv"
    data.to_csv(path,index=False)
    r = '''args <- commandArgs(TRUE)
x <- read.csv(args[1], stringsAsFactors=FALSE, check.names=FALSE, na.strings="", fileEncoding="UTF-8")
stopifnot(nrow(x)==3, all(x$keyword==args[2]), all(x$geo=="US-CA"),
          identical(as.integer(x$value),c(0L,2L,100L)), x$formatted_value[1]=="<1")
if(args[3]=="unknown") {
  stopifnot(all(is.na(x$has_data)),all(is.na(x$is_partial)))
} else {
  stopifnot(all(as.logical(x$has_data)),!any(as.logical(x$is_partial)))
}
cat("R roundtrip OK\\n")'''
    result = subprocess.run([shutil.which("Rscript"),"--vanilla","-e",r,str(path),keyword,
                             "unknown" if unknown_flags else "known"],capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stderr
    assert "R roundtrip OK" in result.stdout


def test_csv_values_read_back_in_python(fake_client,tmp_path):
    data=pull_trends("wildfire","2021-01-01","2021-12-31",geo="US-CA")
    path=tmp_path/"trends.csv"
    data.to_csv(path,index=False)
    restored=pd.read_csv(path)
    assert restored.value.tolist()==data.value.tolist()
    assert restored.formatted_value.tolist()==data.formatted_value.tolist()
    assert restored.keyword.tolist()==data.keyword.tolist()
