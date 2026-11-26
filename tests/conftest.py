import json
from unittest.mock import Mock

import pytest

import trendspull._api as api
import trendspull._client as client


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(client.requests.sessions.Session, "request",
                        Mock(side_effect=AssertionError("Unexpected network access in an offline test")))
    monkeypatch.setattr(client.time, "sleep", Mock())


def response(values=(0, 2, 100), start=1609632000, step=604800, **overrides):
    rows = []
    for i, value in enumerate(values):
        row = dict(time=str(start + i * step), value=[value], formattedValue=["<1" if value == 0 else str(value)],
                   hasData=[True], isPartial=False)
        row.update(overrides)
        rows.append(row)
    return ")]}'\n" + json.dumps({"default": {"timelineData": rows}})


@pytest.fixture
def fake_client(monkeypatch):
    obj = Mock()
    obj.timeline.return_value = ('{"widgets":[]}', response(), "WEEK")
    factory = Mock(return_value=obj)
    monkeypatch.setattr(api, "_TrendsClient", factory)
    return factory, obj
