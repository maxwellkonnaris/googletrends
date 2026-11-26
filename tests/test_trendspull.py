import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

import trendspull as tp
import trends_sign_regions as sr

ROOT = Path(__file__).resolve().parents[1]
DATES = pd.date_range("2021-01-03", periods=24, freq="7D")


def multiline(values, unavailable=(), partial=()):
    return ")]}'\n" + json.dumps({"default": {"timelineData": [
        dict(time=str(int(date.timestamp())), value=[int(value)],
             formattedValue=["<1" if value == 0 else str(int(value))],
             hasData=[i not in unavailable], isPartial=i in partial)
        for i, (date, value) in enumerate(zip(DATES, values))]}})


class FakeClient:
    def __init__(self, responses=None, **kwargs):
        self.responses = responses or {}
        self.calls = []

    def interest_over_time(self, query, *args):
        self.calls.append(query)
        text = self.responses[query]
        return '{"widgets":[]}', text, []

    def pause(self):
        pass

    def close(self):
        pass


@pytest.fixture
def archive(tmp_path, monkeypatch):
    def build(name="case", pulls=1, values=None, flags=None, labels=("wildfire", "asthma", "cough")):
        folder = tmp_path / name
        folder.mkdir()
        path = folder / "study.json"
        path.write_text(json.dumps(dict(study="synthetic", time="2021-01-01 2021-12-31",
            geos=[dict(code="US-CA")], terms=[dict(label=x, query=x) for x in labels], delay_seconds=[0, 0])))
        config = tp.load_config(path)
        clients = []
        for p in range(pulls):
            responses = {}
            for j, label in enumerate(labels):
                vv = np.arange(24) + 10 + 2*j + p if values is None else values[p][j]
                responses[label] = multiline(vv, **(flags or {}).get(label, {}))
            client = FakeClient(responses)
            monkeypatch.setattr(tp, "utc_now", lambda p=p: datetime(2026, 11, 24+p, tzinfo=timezone.utc))
            assert tp.one_pull(config, folder, client)
            clients.append(client)
        return SimpleNamespace(out=folder, config=path, cfg=config, clients=clients)
    return build


def assemble(case):
    tp.cmd_assemble(case)
    return pd.read_csv(case.out / "tidy_all_pulls.csv")


def cli(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                          capture_output=True, text=True, timeout=20)


def edit_raw(case, operation, label="wildfire", day="2026-11-24"):
    manifest_path = case.out / "raw" / day / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["series"][f"US-CA|{label}"]
    path = manifest_path.parent / entry["file"]
    raw = json.loads(path.read_text())
    data = tp.parse_google_json(raw["multiline"])
    operation(data["default"]["timelineData"])
    raw["multiline"] = json.dumps(data)
    blob = json.dumps(raw).encode()
    path.write_bytes(blob)
    entry["sha256"], entry["weeks"] = tp.sha256_bytes(blob), len(data["default"]["timelineData"])
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.parametrize("script", ["trendspull.py", "trends_sign_regions.py"])
def test_cli_help(script):
    result = cli(script, "--help")
    assert result.returncode == 0, result.stderr


def test_supplied_config():
    cfg = tp.load_config(ROOT / "study.json")
    assert len(cfg["terms"]) * len(cfg["geos"]) == 84


def test_google_json_prefix():
    assert tp.parse_google_json(")]}'\n{\"a\": 3}") == {"a": 3}
    with pytest.raises(ValueError):
        tp.parse_google_json("not JSON")


def test_mock_request_chain(monkeypatch):
    responses = [SimpleNamespace(status_code=200), SimpleNamespace(status_code=200,
        text=json.dumps({"widgets": [{"id": "TIMESERIES", "request": {"x": 1}, "token": "test-token"}]})),
        SimpleNamespace(status_code=200, text=multiline(np.arange(24), partial=(0,)))]
    session = SimpleNamespace(headers={}, get=Mock(side_effect=responses))
    monkeypatch.setattr(tp.requests, "Session", lambda: session)
    monkeypatch.setattr(tp.time, "sleep", Mock())
    client = tp.TrendsClient(max_attempts=1)
    _, _, rows = client.interest_over_time("wildfire", "US-CA", "2021-01-01 2025-12-31")
    calls = session.get.call_args_list
    req = json.loads(calls[1].kwargs["params"]["req"])
    assert req["comparisonItem"] == [dict(keyword="wildfire", geo="US-CA", time="2021-01-01 2025-12-31")]
    assert calls[2].kwargs["params"]["token"] == "test-token"
    assert rows[0]["is_partial"] and rows[0]["low_volume"]


def test_pipeline_and_metadata(archive):
    case = archive(pulls=2)
    tidy = assemble(case)
    assert len(tidy) == 144 and {"has_data", "is_partial", "low_volume"}.issubset(tidy.columns)
    region = case.out / "averaged" / "US-CA"
    result = cli("trends_sign_regions.py", region)
    assert result.returncode == 0, result.stderr
    pairs = pd.read_csv(region / "trends_pair_sign_regions.csv")
    assert len(pairs) == 3 and np.isfinite(pairs.select_dtypes("number")).all().all()
    matrix = pd.read_csv(region / "trends_log_share_covariance.csv", index_col=0)
    assert list(matrix.index) == list(matrix.columns)
    assert matrix.shape == (3, 3)
    assert (case.out / "raw" / "2026-11-24" / "config.json").read_bytes() == case.config.read_bytes()
    manifest = json.loads((case.out / "raw" / "2026-11-24" / "manifest.json").read_text())
    assert {"numpy", "pandas", "requests", "python", "source_sha256"}.issubset(manifest)


def test_resume_checks_raw_files(archive, monkeypatch):
    case = archive()
    monkeypatch.setattr(tp, "utc_now", lambda: datetime(2026, 11, 24, tzinfo=timezone.utc))
    client = case.clients[0]
    assert tp.one_pull(case.cfg, case.out, client)
    assert len(client.calls) == 3
    (case.out / "raw" / "2026-11-24" / "US-CA" / "wildfire.json").write_text("corrupted")
    assert tp.one_pull(case.cfg, case.out, client)
    assert len(client.calls) == 4 and client.calls[-1] == "wildfire"
    assert len(assemble(case)) == 72


def test_same_day_config_guard(archive):
    case = archive()
    case.cfg["_sha256"] = "other"
    with pytest.raises(ValueError, match="different config"):
        tp.one_pull(case.cfg, case.out, case.clients[0])


def test_assembly_rejects_other_study(archive):
    case = archive(pulls=2)
    path = case.out / "raw" / "2026-11-25" / "manifest.json"
    data = json.loads(path.read_text())
    data["config_sha256"] = "other-study"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Different config"):
        assemble(case)
    assert not (case.out / "tidy_all_pulls.csv").exists()


def test_assembly_rejects_tampering(archive):
    case = archive()
    path = next(case.out.rglob("wildfire.json"))
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Hash mismatch"):
        assemble(case)


def test_assembly_rejects_changed_snapshot(archive):
    case = archive()
    (case.out / "raw" / "2026-11-24" / "config.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot changed"):
        assemble(case)


def test_assembly_rejects_missing_series(archive):
    case = archive()
    path = case.out / "raw" / "2026-11-24" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["series"].pop("US-CA|wildfire")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Incomplete"):
        assemble(case)


def test_raw_filter_survives_geometric_average(archive):
    zeros = [0]*12 + [100]*12
    other = list(np.arange(24)+10)
    third = list(np.arange(24)[::-1]+12)
    case = archive(pulls=2, values=[[zeros, other, third], [zeros[::-1], other, third]])
    assemble(case)
    region = case.out / "averaged" / "US-CA"
    data = sr.load_folder(region)
    assert (data.wildfire < 1).mean() == 0
    assert sr.low_volume_share(data)["wildfire"] == 0.5
    result = cli("trends_sign_regions.py", region)
    assert result.returncode == 0, result.stderr
    pairs = pd.read_csv(region / "trends_pair_sign_regions.csv")
    assert len(pairs) == 1 and "wildfire" not in set(pairs.term_i) | set(pairs.term_j)


def test_low_volume_masks_respect_date_window(archive):
    zeros = [0]*4 + list(np.arange(20)+10)
    other = list(np.arange(24)+10)
    case = archive(values=[[zeros, other, other[::-1]]])
    assemble(case)
    data = sr.load_folder(case.out / "averaged" / "US-CA")
    selected = data.iloc[4:].copy()
    selected.attrs = data.attrs.copy()
    assert sr.low_volume_share(data)["wildfire"] == pytest.approx(4/24)
    assert sr.low_volume_share(selected)["wildfire"] == 0


def test_flags_preserved_and_common_dates_excluded(archive):
    case = archive(flags={"wildfire": dict(unavailable=(1,), partial=(2,))})
    tidy = assemble(case)
    assert len(tidy) == 72 and tidy.is_partial.sum() == 1 and (~tidy.has_data).sum() == 1
    data = sr.load_folder(case.out / "averaged" / "US-CA")
    assert len(data) == 22 and DATES[1] not in data.index and DATES[2] not in data.index
    assert data.attrs["quality"]["excluded_dates"] == 2


def test_all_unavailable_rejected(archive):
    case = archive(flags={"wildfire": dict(unavailable=tuple(range(24)))})
    with pytest.raises(ValueError, match="common usable dates"):
        assemble(case)


def test_missing_weeks_not_averaged(archive):
    case = archive(pulls=2)
    edit_raw(case, lambda rows: rows.pop(), day="2026-11-25")
    with pytest.raises(ValueError, match="Date grids differ"):
        assemble(case)


def test_empty_timelines_not_successful(archive, monkeypatch):
    case = archive()
    empty = '{"default":{"timelineData":[]}}'
    cfg = dict(case.cfg)
    target = case.out / "empty"
    client = FakeClient({term["query"]: empty for term in cfg["terms"]})
    assert not tp.one_pull(cfg, target, client)
    manifest = json.loads(next(target.rglob("manifest.json")).read_text())
    assert all(entry["status"] == "failed" for entry in manifest["series"].values())


def test_failed_pull_is_nonzero(archive, monkeypatch):
    case = archive()
    monkeypatch.setattr(tp, "TrendsClient", FakeClient)
    monkeypatch.setattr(tp, "one_pull", lambda *args: False)
    with pytest.raises(SystemExit, match="Incomplete pull"):
        tp.cmd_pull(SimpleNamespace(config=case.config, out=case.out, repeat=1))


def test_midnight_stops_pull(archive, monkeypatch):
    case = archive()
    moments = iter([datetime(2026,11,24,tzinfo=timezone.utc), datetime(2026,11,24,tzinfo=timezone.utc),
                    datetime(2026,11,25,tzinfo=timezone.utc)])
    monkeypatch.setattr(tp, "utc_now", lambda: next(moments))
    assert not tp.one_pull(case.cfg, case.out / "midnight", case.clients[0])


@pytest.mark.parametrize("change, message", [
    (lambda c: c["terms"].extend([dict(label="air-quality",query="x"),dict(label="air quality",query="y")]), "filenames"),
    (lambda c: c["geos"].append(c["geos"][0]), "unique"),
    (lambda c: c.update(delay_seconds=[5,1]), "delay_seconds"),
    (lambda c: c.update(time="today 5-y"), "fixed"),
    (lambda c: c["geos"][0].update(code="../../outside"), "safe"),
])
def test_config_validation(archive, change, message):
    case = archive()
    data = json.loads(case.config.read_text())
    change(data)
    case.config.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=message):
        tp.load_config(case.config)


@pytest.mark.parametrize("statuses, sleeps", [([503],0), ([404],0), ([503,200],1), ([429,200],1)])
def test_bounded_retries(monkeypatch, statuses, sleeps):
    client = object.__new__(tp.TrendsClient)
    client.max_attempts = len(statuses)
    client.session = SimpleNamespace(get=Mock(side_effect=[SimpleNamespace(status_code=s,reason="test",text="ok") for s in statuses]), cookies=Mock())
    client._warm = Mock()
    sleep = Mock()
    monkeypatch.setattr(tp.time, "sleep", sleep)
    if statuses[-1] == 200:
        assert client.fetch("https://example.invalid", {}) == "ok"
    else:
        with pytest.raises(RuntimeError):
            client.fetch("https://example.invalid", {})
    assert sleep.call_count == sleeps


def test_raw_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        tp.verified_raw(tmp_path, dict(file="../outside.json"))


def test_modified_export_rejected(archive):
    case = archive()
    assemble(case)
    folder = case.out / "averaged" / "US-CA"
    path = folder / "wildfire.csv"
    path.write_bytes(path.read_bytes()+b"\n")
    with pytest.raises(ValueError, match="CSV changed"):
        sr.load_folder(folder)


def test_missing_quality_sidecar_rejected(archive):
    case = archive()
    assemble(case)
    folder = case.out / "averaged" / "US-CA"
    (folder / "trends_quality.json").rename(folder / "quality_saved_elsewhere.json")
    with pytest.raises(ValueError, match="require trends_quality"):
        sr.load_folder(folder)


def test_assembly_floor_is_configured(archive):
    case = archive(values=[[[0]+list(np.arange(23)+10), list(np.arange(24)+10), list(np.arange(24)+20)]])
    case.floor = 0.25
    assemble(case)
    frame = sr.read_trends_csv(case.out / "by_pull" / "2026-11-24" / "US-CA" / "wildfire.csv")
    assert frame.iloc[0,0] == 0.25
    quality = json.loads((case.out / "averaged" / "US-CA" / "trends_quality.json").read_text())
    assert quality["log_floor"] == 0.25


def test_mixed_geographies_rejected(tmp_path):
    for label, geo in (("a","US-CA"),("b","US-NY")):
        tp.write_trends_csv(tmp_path/f"{label}.csv",pd.Series(np.arange(24)+10,index=DATES),label,geo,"test")
    with pytest.raises(ValueError, match="same geography"):
        sr.load_folder(tmp_path)


def test_duplicate_terms_rejected(tmp_path):
    for name in ("a","b"):
        tp.write_trends_csv(tmp_path/f"{name}.csv",pd.Series(np.arange(24)+10,index=DATES),"asthma","US-CA","test")
    with pytest.raises(ValueError, match="Duplicate terms"):
        sr.load_folder(tmp_path)


@pytest.mark.parametrize("labels,args,message", [
    (("a",), [], "two terms"),
    (("a","b"), ["--end","2021-01-03"], "20 dates"),
    (("a","b"), ["--floor","0"], "positive"),
    (("a","b"), ["--max-zero-share","2"], "between"),
])
def test_cli_validation(archive, labels, args, message):
    case = archive(labels=labels)
    assemble(case)
    result = cli("trends_sign_regions.py",case.out/"averaged"/"US-CA",*args)
    assert result.returncode != 0 and message in result.stderr and "Traceback" not in result.stderr


def test_constant_terms_explicitly_rejected():
    with pytest.raises(ValueError,match="zero-variance"):
        sr.sign_regions(pd.DataFrame(dict(a=np.ones(24),b=np.arange(24))))


def test_sign_bounds_and_rescaling():
    rng = np.random.default_rng(1226)
    x = rng.normal(size=240)
    logs = pd.DataFrame(dict(a=x,b=-0.7*x+rng.normal(size=240)*0.5,c=0.4*x+rng.normal(size=240)))
    pairs, _ = sr.sign_regions(logs)
    rescaled, _ = sr.sign_regions(logs+np.log([0.2,10,300]))
    assert np.allclose(pairs.select_dtypes("number"),rescaled.select_dtypes("number"))
    for row in pairs.itertuples():
        xx, yy = logs[row.term_i], logs[row.term_j]
        cov, sd_sum = np.cov(xx,yy)[0,1], (xx+yy).std(ddof=1)
        for s in (row.zero_band_lower/2,(row.zero_band_lower+row.zero_band_upper)/2,row.zero_band_upper*1.5):
            extrema = [np.cov(xx+d*s*(xx+yy)/sd_sum,yy+d*s*(xx+yy)/sd_sum)[0,1] for d in (-1,1)]
            assert np.allclose(extrema,[cov+s*s-s*sd_sum,cov+s*s+s*sd_sum])
            if s < row.zero_band_lower:
                assert all(np.sign(v)==np.sign(cov) for v in extrema)
            elif s > row.zero_band_upper:
                assert min(extrema)>0
            else:
                assert min(extrema)<=0<=max(extrema)
