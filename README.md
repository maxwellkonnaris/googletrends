Collect and plot Google Trends data in Python or [R](docs/r-usage.Rmd).

![Wildfire, smoke, air quality, asthma, inhaler and cough in California. Every panel uses the same 0–100 scale.](docs/figures/data-overview.svg)

*California · requested 2021–2025 · six terms · 262 weekly dates.
For display, all calibrated values share one rescaling: 100 is the highest
interest across all terms and dates, not each term's own peak.*

## Install

Python 3.11+ · [MIT license](LICENSE). Development snapshot; no release has been tagged.

**Python** (includes the optional plotting dependency):

```bash
python -m pip install "trendspull[plot] @ git+https://github.com/maxwellkonnaris/googletrends.git@d71efd0769107800697ad2585751b0f736b05fee"
```

**R** (R 4.1+, Python 3.11+ and Git; run setup in a fresh R session):

```r
install.packages("remotes")
remotes::install_github("maxwellkonnaris/googletrends@893b6d66f6fafcf88fad67316cc2e0b9cbb56466", subdir = "r-package")
trendspull::install_backend()
```

The R package uses the same Python collector through reticulate. Setup installs
the pinned backend; loading the package does not download software.

## Pull

```python
from trendspull import pull_trends, selected_proportions, plot_trends

# Step 1: Collect the data, preserving raw and calibrated values.
data = pull_trends(
    ["wildfire", "smoke", "air quality", "asthma", "inhaler", "cough"],
    start="2021-01-01", end="2025-12-31", geo="US-CA",
    min_gap_days=None,  # Keep all dates; use e.g. 28 to space them.
)

# Step 2: Transform to a terms × weeks matrix; each column sums to 1.
proportions = selected_proportions(data)
proportions.iloc[:, :3]

# Plot the collected interest with the README layout and one common 0–100 scale.
figure = plot_trends(data)
figure.savefig("trends.pdf")
```

The same functions are available in R; `data` is a data frame, `proportions` is a
matrix, and `figure` is a ggplot/patchwork object:

```r
library(trendspull)
data <- pull_trends(
  c("wildfire", "smoke", "air quality", "asthma", "inhaler", "cough"),
  start = "2021-01-01", end = "2025-12-31", geo = "US-CA"
)
proportions <- selected_proportions(data)
figure <- plot_trends(data)
ggplot2::ggsave("trends.pdf", figure, width = 11, height = 9.5,
                device = grDevices::cairo_pdf)
```

`pull_trends` returns a pandas DataFrame: one row per date, term and region. Up to five terms
share Google's 0–100 scale; larger sets automatically use G-TAB calibration
([West, 2020](https://doi.org/10.1145/3340531.3412075)).
`value` preserves the raw index; `calibrated_value` is relative to the first term's
peak (1), so other terms can exceed 1.
Values describe relative search interest, not counts or disease incidence.
Date spacing does not guarantee independence. See [options and output](docs/data-contract.md).

`selected_proportions(data)` returns a separate pandas DataFrame: terms as rows,
dates as columns, normalized among the supplied terms. It uses calibrated values
when applicable, otherwise the shared raw scale. The collected `data` is unchanged.
Use the original object with its metadata and select one geography at a time.

`plot_trends(data, ncol=3)` draws the overview and one panel per term. It divides
every raw or calibrated value by the maximum across the supplied data and
multiplies by 100; each panel uses the same scale. It retains zeros and flagged
observations without smoothing. It does not change `data` or calculate proportions.
See [plotting details](docs/data-contract.md#plotting-helper).

This collector uses undocumented Google Trends website endpoints, which can change
or stop working. Google's [official API alpha](https://developers.google.com/search/apis/trends)
offers consistent scaling across requests and a rolling five-year window, with
limited access. It is not implemented here; with access, it could replace the
website comparisons and their calibration. Both sources measure search interest,
not absolute counts. See [data access](docs/data-contract.md#data-access-and-official-api).

## What Google Trends data identify

Search counts can be written as a share of all Google searches times the week's total.
The cards below write Google's transformation as a known function, decompose each count
into returned data and unknown numbers, and show which quantities the data identify:
the composition of the selected terms is recovered, but no total is.
The example uses made-up numbers for two terms and two weeks and ignores rounding.

The shared scale applies within one geography and one `pull_trends` call with
fixed request settings. Up to five terms use one raw Google comparison by default;
larger sets use G-TAB. Sampling, rounding and suppression limit precision.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/legend-dark.png">
  <img src="docs/figures/search-counts/legend.png" width="820" alt="Color key: blue = identified from Google Trends data; red = not identified; uncolored = constants and definitions.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-1-dark.png">
  <img src="docs/figures/search-counts/step-1.png" width="820" alt="Step 1. Absolute abundance equals proportion times total, with all Google searches as the system: W_qn = W^comp_qn x W^tot_n. Wildfire 1% x 10,000 = 100 and 2% x 20,000 = 400; smoke 3% x 10,000 = 300 and 2% x 20,000 = 400. None of these is reported.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-2-dark.png">
  <img src="docs/figures/search-counts/step-2.png" width="820" alt="Step 2. What Google computes: I_qn = (100 / m_r) x W^comp_qn, where m_r is the largest share across all terms and dates in the request (3%). Wildfire 33.3 and 66.7; smoke 100 and 66.7.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-3-dark.png">
  <img src="docs/figures/search-counts/step-3.png" width="820" alt="Step 3. Inverting Google's function: W_qn = I_qn x theta_n, with theta_n = m_r x W^tot_n / 100 searches per index point (3 in week 1, 6 in week 2).">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-4-dark.png">
  <img src="docs/figures/search-counts/step-4.png" width="820" alt="Step 4. Three-part decomposition: W_qn = P_qn x S_n x W^tot_n, where P_qn = I_qn / sum of I over selected terms is returned and S_n = (m_r/100) x sum of I is not.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-5-dark.png">
  <img src="docs/figures/search-counts/step-5.png" width="820" alt="Step 5. Selected-term composition and total: with the selected terms as the system, W_qn = P_qn x T_n. The composition P_qn (25%/75%, 50%/50%) is identified; the total T_n (400, 800) is not. This mirrors microbiome sequencing.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-6-dark.png">
  <img src="docs/figures/search-counts/step-6.png" width="820" alt="Step 6. With G-TAB calibration: request A (wildfire, smoke) and request B (smoke, cough) are scaled separately; smoke peaks at 100 in A and 50 in B, so B is multiplied by 2 to match A, then all values are divided by wildfire's peak (66.7) so the reference peak is 1. Calibrated values equal k times shares of all searches, with k = 50.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-7-dark.png">
  <img src="docs/figures/search-counts/step-7.png" width="820" alt="Step 7. What the data identify: the selected-term composition and ratios of shares need nothing extra; shares of all searches need one number (m_r); the selected-term total and search counts need one number per week (theta_n); all Google searches are not in the data.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-8-dark.png">
  <img src="docs/figures/search-counts/step-8.png" width="820" alt="Step 8. Why only these are identified: two worlds with different counts and totals (World A: 100/300 and 400/400 with totals 10,000 and 20,000; World B: 200/600 and 400/400 with totals 10,000 and 10,000) produce identical Google values.">
</picture>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/search-counts/step-9-dark.png">
  <img src="docs/figures/search-counts/step-9.png" width="820" alt="Step 9. What would recover the rest: one true share recovers all shares; weekly counts for one reference term give theta_n = W_ref,n / I_ref,n and recover all counts.">
</picture>

### Example table

**Rows are terms; columns are weeks.** The full California example has **6 × 262**
values. Below are three weeks from that pull, rounded for display. `pull_trends`
returns a long DataFrame; pivoting changes its layout without changing its values.
As in the cards, $q$ indexes terms, $n$ indexes weeks, and $S$ is the set of six
selected terms.

**1. Calibrated matrix — $\widetilde I_{qn}$ (Step 6)**

`interest` contains the package's `calibrated_value` output. In the cards' idealized
notation, $\widetilde I_{qn} = k W^{\mathrm{comp}}_{qn}$: each term's share of all
Google searches multiplied by the same unknown constant $k$.

```python
interest = data.pivot(index="keyword", columns="date", values="calibrated_value")
```

| Term $q$ / week $n$ | 2021-01-03 | 2021-01-10 | 2021-01-17 |
|---|---:|---:|---:|
| wildfire | 0.0169 | 0.0169 | 0.0339 |
| smoke | 0.6441 | 0.6102 | 0.6271 |
| air quality | 0.0508 | 0.0508 | 0.0508 |
| asthma | 0.0830 | 0.0795 | 0.0772 |
| inhaler | 0.0415 | 0.0461 | 0.0403 |
| cough | 0.2441 | 0.2237 | 0.2169 |

Google scales each comparison separately. G-TAB uses overlapping terms to connect
those charts onto one reference scale. Here, 1 means the estimated peak interest
in `wildfire` over the full requested period. For example, smoke's 0.6441 on
January 3 means about 64.41% of that reference peak. It is not a percentage of all
searches or of that week's six-term total. Columns need not sum to 1.

**2. Figure rescaling — the same $\widetilde I_{qn}$ in display units**

Every cell is multiplied by one common factor:

$$
\frac{100}{\max_{d \in S,\,m}\widetilde I_{dm}}\,\widetilde I_{qn}.
$$

Here $d$ and $m$ range over all selected terms and weeks.

```python
plot_interest = 100 * interest / interest.to_numpy().max()
```

This uses the maximum across **all terms and all 262 weeks**, not just the preview.
For this pull it multiplies every cell by 59: smoke's 0.644068 becomes 38.0.
Every term/date ratio is preserved. `plot_trends(data)` applies this display
rescaling internally; the collected values remain unchanged.

**3. Optional selected-term proportions — $P_{qn}$ (Steps 4–5)**

`proportions` contains the selected-term composition:

$$
P_{qn} = \frac{\widetilde I_{qn}}{\sum_{d \in S}\widetilde I_{dn}}.
$$

This is the cards' $P_{qn}$, computed from calibrated values; the common $k$ cancels.

```python
proportions = selected_proportions(data)
```

| Term $q$ / week $n$ | 2021-01-03 | 2021-01-10 | 2021-01-17 |
|---|---:|---:|---:|
| wildfire | 0.0157 | 0.0165 | 0.0324 |
| smoke | 0.5961 | 0.5939 | 0.5993 |
| air quality | 0.0471 | 0.0495 | 0.0486 |
| asthma | 0.0768 | 0.0774 | 0.0738 |
| inhaler | 0.0384 | 0.0449 | 0.0386 |
| cough | 0.2259 | 0.2178 | 0.2073 |
| **Column sum** | **1.0000** | **1.0000** | **1.0000** |

On January 3, the six calibrated values sum to 1.080407, so smoke's proportion is
0.644068 / 1.080407 = 0.5961. On another week the divisor changes. These proportions
sum to 1 **among the six selected terms**, not among all Google searches; changing
the selected terms changes the result. Even an unchanged term's proportion can
fall if another term increases.

Use `interest` ($\widetilde I_{qn}$) for the comparable search-interest matrix obtained
from the package.
Call the optional `selected_proportions(data)` helper only when the question concerns
the distribution of interest among your chosen terms ($P_{qn}$). Collection does not normalize
across terms automatically.
Fresh pulls may differ.

### References

1. Google. *FAQ about Google Trends data.* Google Trends Help. <https://support.google.com/trends/answer/4365533>
2. West, R. (2020). Calibration of Google Trends time series. *Proceedings of the 29th ACM International Conference on Information and Knowledge Management (CIKM '20)*, 2257–2260. <https://doi.org/10.1145/3340531.3412075>
3. Nixon, M. P., McGovern, K. C., Konnaris, M. A., Letourneau, J., David, L. A., Lazar, N. A., Mukherjee, S., & Silverman, J. D. (2026). Scale reliant inference. *The Annals of Applied Statistics*, 20(3), 2125–2147. <https://doi.org/10.1214/26-AOAS2230>
