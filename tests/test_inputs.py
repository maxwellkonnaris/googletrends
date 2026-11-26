from pathlib import Path

import pytest

from trendspull import pull_trends


@pytest.mark.parametrize("changes", [
    {"keywords": None}, {"keywords": []}, {"keywords": ""}, {"keywords": "  "},
    {"keywords": ["fire", "fire"]}, {"keywords": ["fire", 3]}, {"keywords": {"fire"}},
    {"start": "today"}, {"start": "2021-1-01"}, {"start": "2021-02-30"},
    {"end": None}, {"end": "2020-01-01"},
    {"geo": []}, {"geo": ["US", "US"]}, {"geo": "../../outside"}, {"geo": "us-ca"},
    {"geo": [None]}, {"category": True}, {"category": -1}, {"category": 2.5},
    {"search_type": "books"}, {"search_type": []}, {"language": ""}, {"language": None},
    {"language": "en-US\r\nAuthorization: bad"},
    {"delay": 3}, {"delay": [1]}, {"delay": [-1, 1]}, {"delay": [2, 1]},
    {"delay": [0, float("inf")]}, {"delay": [0, True]},
    {"max_attempts": 0}, {"max_attempts": True}, {"max_attempts": 1.5},
    {"timeout": 0}, {"timeout": float("nan")}, {"timeout": float("inf")}, {"timeout": True},
])
def test_invalid_inputs_fail_before_network_or_files(changes, fake_client, tmp_path):
    factory, _ = fake_client
    args = dict(keywords="wildfire", start="2021-01-01", end="2021-12-31", archive=tmp_path / "archive")
    args.update(changes)
    with pytest.raises(ValueError):
        pull_trends(**args)
    factory.assert_not_called()
    assert not (tmp_path / "archive").exists()


@pytest.mark.parametrize("keyword", ["wildfire", "air quality", "/m/0abc12", "煙", "a,b", "2021-01-01", "NA"])
def test_keyword_is_sent_as_one_exact_string(keyword, fake_client):
    _, client = fake_client
    pull_trends(keyword, "2021-01-01", "2021-12-31")
    assert client.timeline.call_args.args[0] == keyword
    assert client.timeline.call_count == 1


def test_parameters_reach_client_unchanged(fake_client):
    factory, client = fake_client
    pull_trends("smoke", "2021-01-01", "2021-12-31", geo="US-CA", search_type="news", category=45,
                language="fr-FR", timeout=12, max_attempts=2)
    factory.assert_called_once_with("fr-FR", 2, 12)
    client.timeline.assert_called_once_with("smoke", "US-CA", "2021-01-01", "2021-12-31", 45, "news")
