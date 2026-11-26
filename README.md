# trendspull

One function to collect Google Trends interest-over-time data. Development prototype.

**Keywords + dates + region → `pull_trends()` → pandas DataFrame → CSV for Python or R**

```bash
python -m pip install .
```

```python
from trendspull import pull_trends

data = pull_trends(["wildfire", "smoke"], start="2021-01-01", end="2025-12-31", geo="US-CA")
data.to_csv("trends.csv", index=False)
```

| Input | Meaning |
|---|---|
| `keywords` | One to five search strings/Topic IDs, compared together |
| `start`, `end` | Fixed `YYYY-MM-DD` dates |
| `geo=""` | Worldwide; use a code such as `US-CA`, or a list of codes |
| `search_type="web"` | Web, images, news, YouTube or shopping |
| `category=0`, `language="en-US"` | Google category ID and interface language |

| Output | Contents |
|---|---|
| pandas DataFrame | One row per returned timestamp, keyword and region |
| Observations | Google's 0–100 index, displayed value, and availability/partial-period flags |
| Provenance | Request settings, retrieval time and request ID; optional raw-response archive |
| CSV | Ordinary tabular export readable in Python, R and spreadsheet tools |

```r
data <- read.csv("trends.csv", stringsAsFactors = FALSE)
```

It requests Google's chart definition and temporary token, then retrieves the timeline
through the unofficial website endpoints. Keywords share Google's 0–100 scale within
each geography request; separate geographies or calls have separate scales. These
are search-interest indices, not counts or percentages. More than five keywords
raises an error; requests are never silently split. Values, zeros and flagged periods
are retained unchanged. Google chooses the time resolution.
See the [data contract](docs/data-contract.md) for fields, failure handling and limits.

Tests: `python -m pip install '.[test]'` then `python -m pytest -q` (offline).
