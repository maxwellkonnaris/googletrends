Collect Google Trends data in Python or [R](docs/r-usage.Rmd).

![Wildfire, smoke, air quality, asthma, inhaler and cough in California. Every panel uses the same 0–100 scale.](docs/figures/data-overview.svg)

*California · requested 2021–2025 · six terms · 262 weekly dates.
For display, all calibrated values share one rescaling: 100 is the highest
interest across all terms and dates, not each term's own peak.*

## Install

Python 3.9+:

```bash
python -m pip install "git+https://github.com/maxwellkonnaris/googletrends.git@main"
```

## Pull

```python
from trendspull import pull_trends

data = pull_trends(
    ["wildfire", "smoke", "air quality", "asthma", "inhaler", "cough"],
    start="2021-01-01", end="2025-12-31", geo="US-CA",
    min_gap_days=None,  # Keep all dates; use e.g. 28 to space them.
)
data[["date", "keyword", "calibrated_value"]].head()
data.to_csv("trends.csv", index=False)
```

Returns a pandas DataFrame: one row per date, term and region. Up to five terms
share Google's 0–100 scale; larger sets automatically use G-TAB calibration.[^gtab]
`value` preserves the raw index; `calibrated_value` is relative to the first term's
peak (1), so other terms can exceed 1.
Values describe relative search interest, not counts or disease incidence.
Date spacing does not guarantee independence. See [options and output](docs/data-contract.md).

## From Google search counts to compositional covariance

How Google Trends data relate to absolute search counts, what calibration recovers, and what remains unknown.

Here the system includes all Google queries: the scale is total Google searches,
and the selected terms are a subset of that full composition. Normalizing only
the selected terms to sum to 1 instead defines their within-subset composition.
The covariance identity describes the ideal calibrated signal; sampling,
rounding and suppression affect its estimation from observed indices.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/legend-dark.png">
  <img src="docs/figures/search-counts/legend.png" width="820" alt="Color key: blue = measured or estimated from data; red = not identified from data; uncolored = definitions and constants.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-1-dark.png">
  <img src="docs/figures/search-counts/step-1.png" width="820" alt="Step 1. Absolute abundance: W_qn, the true number of searches for query q in week n (not reported by Google).">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-2-dark.png">
  <img src="docs/figures/search-counts/step-2.png" width="820" alt="Step 2. Scale: W^tot_n, total Google searches in week n, summed over all queries (not reported).">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-3-dark.png">
  <img src="docs/figures/search-counts/step-3.png" width="820" alt="Step 3. Relative abundance: W^comp_qn = W_qn / W^tot_n, each query's share of all searches.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-4-dark.png">
  <img src="docs/figures/search-counts/step-4.png" width="820" alt="Step 4. Google Trends index: I^(r)_qn = s_r W^comp_qn, the share rescaled to 0 to 100 within request r.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-5-dark.png">
  <img src="docs/figures/search-counts/step-5.png" width="820" alt="Step 5. G-TAB calibration: I~_qn = k W^comp_qn, with one constant k shared by every query and week.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-6-dark.png">
  <img src="docs/figures/search-counts/step-6.png" width="820" alt="Step 6. Compositional covariance: on the log scale k drops out, so cov(log I~_in, log I~_jn) = Sigma^comp_ij.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-7-dark.png">
  <img src="docs/figures/search-counts/step-7.png" width="820" alt="Step 7. Missing scale: log W_qn = log W^comp_qn + log W^tot_n; the total is not identified.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-8-dark.png">
  <img src="docs/figures/search-counts/step-8.png" width="820" alt="Step 8. Absolute covariance: Sigma_ij = Sigma^comp_ij + sigma^tot (sigma^comp_i rho_i + sigma^comp_j rho_j) + (sigma^tot)^2.">
</picture>

### References

1. Google. *FAQ about Google Trends data.* Google Trends Help. <https://support.google.com/trends/answer/4365533>
2. West, R. (2020). Calibration of Google Trends time series. *Proceedings of the 29th ACM International Conference on Information and Knowledge Management (CIKM '20).* <https://arxiv.org/abs/2007.13861>
3. Nixon, M. P., McGovern, K. C., Konnaris, M. A., Letourneau, J., David, L. A., Lazar, N. A., Mukherjee, S., & Silverman, J. D. (2026). Scale reliant inference. *The Annals of Applied Statistics*, 20(3), 2125–2147. <https://doi.org/10.1214/26-AOAS2230>
4. Konnaris, M. A., Lazar, N. A., & Silverman, J. D. Scale reliant covariance estimation: with applications in genomic survey data. Manuscript in preparation.

[^gtab]: Robert West (2020). [*Calibration of Google Trends Time Series*](https://doi.org/10.1145/3340531.3412075). CIKM, 2257–2260.
