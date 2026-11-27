# Collection contract — development draft

The package collects interest over time: **one comparison containing all supplied
keywords per geography**, with fixed dates, all categories and web search unless the
caller changes those options. Unlike the original ZIP, keywords are compared together.
This is not a claim of matching a particular published wildfire study.

## Values and request settings

`pull_trends(keywords, start, end, *, geo="", search_type="web", category=0,
language="en-US", archive=None, delay=(8,20), max_attempts=3, timeout=60)`
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
More than five keywords raises ValueError before any network or file access, matching
the website comparison limit. No separate batching, calibration, stitching or local
rescaling is performed. Changing the keyword set or dates can change returned values.

`language` controls Google's interface language, not a language-restricted population
of searches. Google selects time resolution and period boundaries; requests use tz=0
and timestamps are returned in UTC. Actual period timestamps are preserved, including
boundary buckets outside the nominal date labels. Hourly values retain their hours.

The observations are [Google's sampled and normalized indices](https://support.google.com/trends/answer/4365533).
No logarithms, replacements, filtering, smoothing, alignment or other data modification
is performed. A zero can indicate low volume, not a known absence of searches.
Unknown provider flags remain missing, rather than being replaced with true or false.

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

Additional run metadata, normalization scope, keyword order and per-request observation
row counts are in `data.attrs["trendspull"]` and the optional archive manifest.
CSV preserves the columns but not pandas attrs; an archive preserves full metadata.
This is an ordinary DataFrame/CSV, not a custom binary file type. The precise table
layout and reference-study compatibility remain open for user review.

## Failures, empty data and optional archives

Inputs are validated before network access or archive creation. Invalid parameters
raise ValueError. Request/response failures raise RuntimeError with query context;
no successful-looking partial DataFrame is returned. Sessions close on success,
failure and interruption.

A valid empty timeline contributes zero rows and emits a warning; request metadata
records its empty status. A single returned observation is valid. Dates are not
intersected across series, and unavailable or partial observations are not discarded.

`max_attempts` is a per-chart-request bound, not a total wall-clock limit. Retries apply
to connection errors, HTTP 429 and server failures. Other HTTP errors fail immediately.
There is no sleep after the last failed attempt. `delay` controls pauses between
geography comparisons; chart-token and timeline requests also have a short pause.

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
