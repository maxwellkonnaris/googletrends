# trendspull

Collect Google Trends interest over time for Python or [R](docs/r-usage.Rmd).

## Installation

Requires Python 3.9+ and GitHub SSH access while this repository is private.

```bash
python -m pip install "git+ssh://git@github.com/maxwellkonnaris/trendspull.git@main"
```

## Example

```python
from trendspull import pull_trends

data = pull_trends(
    ["wildfire", "smoke"],
    start="2021-01-01", end="2025-12-31", geo="US-CA",
    min_gap_days=28,  # Change this value, or use None to keep every date.
)
data[["date", "keyword", "value"]].head()
data.to_csv("trends.csv", index=False)
```

Returns one row per timestamp, keyword and region. Read the CSV in R with
`read.csv("trends.csv")`.

Up to five keywords share a 0–100 scale within each region and request. Values are
relative search interest, not search counts. Separate requests have separate scales.
Use `min_gap_days=28` to retain dates at least 28 days apart; this does not guarantee
uncorrelated observations. All dates are kept by default.
See [options and output fields](docs/data-contract.md) for details.
