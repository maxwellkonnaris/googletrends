# Collection contract — development draft

The package collects interest over time with fixed dates, all categories and web
search unless the caller changes those options. Up to five keywords are requested
together per geography; larger sets use the G-TAB calibration described below.
This is not a claim of matching a particular published wildfire study.

## Values and request settings

`pull_trends(keywords, start, end, *, geo="", search_type="web", category=0,
language="en-US", min_gap_days=None, archive=None, delay=(8,20), max_attempts=3,
timeout=60, calibration="auto", reference=None, anchors=None, min_anchor_peak=10,
max_comparisons=100)`
returns a pandas DataFrame. One to five keywords are requested together, preserving
their input order and sharing Google's comparison scale within each geography.
One request ID identifies all keyword rows from that comparison. Multiple geographies
produce separate comparisons with separate scales; different calls also have separate
scales. Request IDs therefore identify the comparison boundaries in CSV exports.

Google scales the highest search-interest point across the compared keywords and
periods to 100. The other values retain their relative scale within that comparison;
they are neither absolute search counts nor percentages of all searches. Sampling,
rounding and low-volume suppression limit precision, especially for rare keywords
compared with very popular ones. See [Google's explanation](https://newsinitiative.withgoogle.com/resources/trainings/google-trends/basics-of-google-trends/).
With `calibration="none"`, more than five keywords raises ValueError before network
or file access. `"auto"` calibrates larger sets; `"gtab"` also calibrates smaller sets.
Changing the keyword set or dates can change returned values.

`language` controls Google's interface language, not a language-restricted population
of searches. Google selects time resolution and period boundaries; requests use tz=0
and timestamps are returned in UTC. Actual period timestamps are preserved, including
boundary buckets outside the nominal date labels. Hourly values retain their hours.

The observations are [Google's sampled and normalized indices](https://support.google.com/trends/answer/4365533).
Raw `value` is never rescaled or replaced; no smoothing or date alignment is performed.
All provider dates are kept unless the caller requests the explicit date selection
described below. A zero can indicate low volume, not a known absence of searches.
Unknown provider flags remain missing, rather than being replaced with true or false.

## G-TAB calibration

This implementation uses the peak-ratio graph and minimum-rounding-error paths in
[West (CIKM 2020)](https://arxiv.org/html/2007.13861#S2). The finite anchor bank consists
of the requested keywords followed by optional `anchors` (duplicates of requested
keywords are included once). It is rebuilt for every geography and call. There is no
external precomputed bank, upstream `gtab` dependency, candidate corpus or binary-search
deployment phase: all target terms are already bank candidates. This is a local
implementation of the published graph calculation, not a wrapper around that software.

Candidates are initially queried in overlapping groups of five, in input order.
For N > 5 candidates there are N-4 initial charts per geography; N <= 5 needs one.
Disconnected terms trigger targeted two-term comparisons with connected anchors.
The closest observed peak ratio selects the next pair; ratios below the reliability
threshold only guide new requests and are never used as calibration edges. A pair is
not retried as a new comparison within the same call. Bridge candidates can themselves
be connected first. If no remaining pair connects the requested terms, calibration fails.

Each chart requires Google explore and timeline requests plus bounded retries. The
initial plan must fit `max_comparisons` (default 100), checked before network or files.
Adaptive comparisons count toward the same total cap across all geographies. Reaching
the cap fails without a partial table; completed raw responses remain in the archive.
`delay` pauses between comparison charts, including within a geography.

For each pair sharing a chart, estimate the ratio of their usable period maxima.
Known partial, unavailable and low-volume observations do not define those maxima;
unknown flags remain eligible. Both maxima must be at least `min_anchor_peak`
(default 10; integer 2-100). Integer rounding gives peak intervals m +/- 0.5;
following the paper, a maximum of 100 is treated as exact. Ratio bounds are obtained
by dividing opposite endpoints. An edge's cost is log(upper/lower); Dijkstra's
algorithm finds a path minimizing accumulated multiplicative rounding error from
`reference` (default first keyword) to each requested keyword. Edge estimates and
bounds are multiplied along that path.

If R is a term's calibrated peak ratio and m is its raw usable peak in the selected
source chart, each observation is `calibrated_value = value * R/m`. The source chart
with the largest usable peak is selected for each term to limit rounding loss;
ties use the first chart. Raw columns, flags and request IDs are retained from that
source. A term appears once per date, even if it occurred in several chart requests.
Bridge-only anchors do not appear as output rows. No averaging is performed.

The derived unit is a fraction of the reference's usable period peak (defined as 1),
not Google's 0-100 index. Values can exceed 1 when another term is more popular than
the reference. Separate geographies and calls have separate reference peaks, so this
does not establish a scale across geographies or calls. All chart timestamps and
resolutions must match exactly; mismatches fail instead of being aligned.

`calibrated_lower` and `calibrated_upper` propagate rounding intervals for the path,
source peak and observation. They are conditional rounding bounds, not confidence
intervals. They omit sampling variation, privacy suppression and query instability.
Known partial, unavailable and low-volume rows retain their raw/derived values but
have missing bounds. Zeros still do not establish zero population search interest.

A disconnected bank fails with RuntimeError and no partial table. This can happen
for empty/all-zero series, very different popularity levels or absent usable peaks.
Optional intermediate-popularity anchors or a different candidate ordering may
connect the bank; calibration cannot recover information absent from Google's data.
Paths, source chart IDs, peak ratios, factors and bounds are recorded under
`data.attrs["trendspull"]["calibration"]["geographies"]` and in optional manifests.

## Optional time spacing

`min_gap_days=28` retains the first provider timestamp in each geography, then the
earliest timestamp at least 28 elapsed days after the previously retained timestamp.
All keywords at a retained timestamp stay together. Selection uses actual UTC time
differences, not row numbers; 28 is an example, not a scientifically chosen default.
`None` keeps every provider date. A supplied gap must be a positive integer.

Spacing is applied after collecting, validating and, when requested, calibrating the
entire timelines. Calibration uses full timelines even if the gap omits a peak. It does
not make separate Google requests for selected dates, interpolate, aggregate, or rescale
the values. Thus the returned subset need not contain the original chart's peak of
100. Optional archives retain the full unselected response. Settings record the gap;
each request records `provider_row_count` before selection and `row_count` afterward.
The anchor is the first returned timestamp, which can precede the requested start
because Google labels whole buckets.

The target of this option is a minimum timestamp separation, not zero autocorrelation.
For a process whose dependence decays with lag, larger gaps may reduce correlation,
but trends, seasonality and persistent events can preserve dependence at long lags.
Even zero correlation would not generally establish independence. A suitable gap
cannot be determined from the request settings alone. Assess dependence in the
downstream analysis; the collector neither estimates autocorrelation nor chooses a gap.
See [NIST's autocorrelation reference](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35c.htm).

## Current draft table

| Fields | Type and meaning |
|---|---|
| `date` | UTC timestamp for the returned period |
| `keyword`, `geo` | Exact keyword and geography requested; empty geo means worldwide |
| `value` | Google's integer 0–100 index, unchanged, shared within `request_id` |
| `formatted_value` | Displayed string, including `<1`; missing when not supplied |
| `has_data`, `is_partial` | Provider booleans; nullable when not supplied |
| `low_volume` | True for value zero or a displayed `<1`; this does not remove the row |
| `start`, `end` | Requested ISO dates |
| `category`, `search_type`, `language` | Request settings |
| `retrieved_at`, `request_id` | UTC retrieval timestamp and ID linking observations to their request |
| `calibrated_value` | G-TAB only: derived relative interest, reference usable period peak = 1 |
| `calibrated_lower`, `calibrated_upper` | G-TAB only: conditional rounding bounds; missing for known quality limitations |
| `calibration_factor`, `calibration_reference` | G-TAB only: multiplier applied to raw value and the reference term |

Additional run metadata, normalization scope, keyword order and per-request observation
row counts are in `data.attrs["trendspull"]` and the optional archive manifest.
CSV preserves the columns but not pandas attrs; an archive preserves full metadata.
Python can also be called directly from R using reticulate, returning a regular R
data.frame; see the [R walkthrough](r-usage.Rmd). Python remains the collection engine.
R conversion preserves values, missing flags and timestamp instants. R may display
times in its local timezone, and pandas attrs do not automatically become R attributes.
Use the optional archive for complete metadata or copy attrs as shown in the walkthrough.
This is an ordinary DataFrame/CSV, not a custom binary file type. The precise table
layout and reference-study compatibility remain open for user review.

## Failures, empty data and optional archives

Inputs are validated before network access or archive creation. Invalid parameters
raise ValueError. Request/response failures raise RuntimeError with query context;
no successful-looking partial DataFrame is returned. Sessions close on success,
failure and interruption.

A valid empty timeline contributes zero rows and emits a warning; request metadata
records its empty status. A single returned observation is valid. Dates are not
intersected across series; unavailable or partial observations at selected dates are
not discarded based on their flags.

`max_attempts` is a per-chart-request bound, not a total wall-clock limit. Retries apply
to connection errors, HTTP 429 and server failures. Other HTTP errors fail immediately.
There is no sleep after the last failed attempt. `delay` controls pauses between
comparison charts; chart-token and timeline requests also have a short pause.

`archive="data"` creates a fresh run subfolder containing response texts, checksums,
request settings, runtime versions and a manifest. Existing runs are never reused or
overwritten. Collection can leave an explicitly failed archive for inspection; it does
not resume that archive. No files are created unless archive is supplied.

## Review before a release

Agree the output schema and verify any claimed reference study's acquisition protocol;
compare a bounded live pull with an equivalent Google export; check Python/R roundtrips;
run installed-wheel tests across supported Python/dependency versions; choose a license.
These are release criteria, not claims already established by passing unit tests.
No PyPI upload or release is authorized by this development work.

No DVC, containers or MLflow were added: current validation uses small synthetic data
and needs neither dataset distribution nor computational experiment tracking.
