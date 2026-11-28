# Working on trendspull

This is a Google Trends collection package. The public functions are pull_trends
and the user-authorized selected_proportions transformation helper. Keep collection
and transformation separate; selected_proportions returns a terms-by-dates matrix
normalized across the supplied terms within each date, for one geography and call.
Preserve provider values, timestamps, zeros, displayed values and quality flags.
Only apply date selection when the user supplies min_gap_days; keep all dates by default.
Archive the full provider response before selection. G-TAB calibration is explicitly
authorized: preserve raw value and flags, put derived estimates and conditional rounding
bounds in separate columns, and record anchor paths and reference units. Use raw joint
comparisons for up to five terms by default and G-TAB for larger sets. Do not add other
filtering, imputation, averaging or statistical analyses beyond the explicitly
authorized selected-term normalization. Spacing is not a guarantee
of uncorrelated or independent observations.
Do not describe the package as reproducing a published study until that study's
request, scaling and data conventions have been verified against its sources.

Keep production code small and readable under src/trendspull. Test the installed
package, not only imports from the checkout. Use python -m pytest -q with synthetic
responses and blocked network access; test malicious/malformed inputs, empty data,
rate limits, retries, interrupted requests, preservation and archive failure paths.

Keep new public API/output choices provisional until the user reviews their meaning.
Do not publish a release or upload to PyPI without explicit user approval.
The repository is public. Use reviewable changes on codex/ branches.

Git tracks source, package metadata, tests, CI and documentation. Research data,
archives, logs, builds and credentials stay outside Git. A curated README figure
is permitted under docs/figures; keep its source data and plotting notebook local. Add DVC, containers or
MLflow only when a concrete need exists. Do not use sudo, force-push or delete
unrelated user files.
