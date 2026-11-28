# trendspull

Collect Google Trends timelines as a pandas DataFrame. Up to five terms share
one Google comparison; larger sets use G-TAB calibration. Raw values, dates,
quality flags and request metadata are preserved.

```python
from trendspull import pull_trends, selected_proportions, plot_trends

data = pull_trends(
    ["wildfire", "smoke", "air quality", "asthma", "inhaler", "cough"],
    start="2021-01-01", end="2025-12-31", geo="US-CA",
)
proportions = selected_proportions(data)  # Terms × dates; each column sums to 1.
figure = plot_trends(data)  # Requires the optional plot extra.
```

Python 3.11+ is required. Install the plotting extra with
`python -m pip install 'trendspull[plot]'`.

Values measure relative search interest, not search counts. G-TAB's
`calibrated_value` uses the reference term's peak as 1; selected-term proportions
have a different denominator at each date. Plots use one common maximum across
all supplied terms and dates. Select one geography before using either helper.

Collection uses undocumented Google website endpoints, which can change or block
access. Offline tests do not establish live availability. See the
[README](https://github.com/maxwellkonnaris/googletrends#readme) and
[data contract](https://github.com/maxwellkonnaris/googletrends/blob/main/docs/data-contract.md)
for options, interpretation and limitations. A separate native R package is in
the same repository.

G-TAB calculation: West (2020), *Calibration of Google Trends Time Series*,
[doi:10.1145/3340531.3412075](https://doi.org/10.1145/3340531.3412075).

MIT license. Source and issues:
[github.com/maxwellkonnaris/googletrends](https://github.com/maxwellkonnaris/googletrends).
