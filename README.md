# trendspull

Collect Google Trends interest over time as a pandas DataFrame.

## Installation

Requires Python 3.9+ and GitHub SSH access while this repository is private.

```bash
python -m pip install "git+ssh://git@github.com/maxwellkonnaris/trendspull.git@codex/collection-package"
```

## Example

```python
from trendspull import pull_trends

data = pull_trends(
    ["wildfire", "smoke"],
    start="2021-01-01", end="2025-12-31", geo="US-CA",
)
data[["date", "keyword", "value"]].head()
data.to_csv("trends.csv", index=False)
```

Returns one row per timestamp, keyword and region. Read the CSV in R with
`read.csv("trends.csv")`.

Up to five keywords share a 0–100 scale within each region and request. Values are
relative search interest, not search counts. Separate requests have separate scales.
See [options and output fields](docs/data-contract.md) for details.
