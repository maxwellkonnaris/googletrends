# Working on trendspull

This is a collection-only Python package. Its sole public function is pull_trends.
Preserve provider values, timestamps, zeros, displayed values and quality flags.
Do not add filtering, imputation, normalization, averaging or statistical analyses.
Do not describe the package as reproducing a published study until that study's
request, scaling and data conventions have been verified against its sources.

Keep production code small and readable under src/trendspull. Test the installed
package, not only imports from the checkout. Use python -m pytest -q with synthetic
responses and blocked network access; test malicious/malformed inputs, empty data,
rate limits, retries, interrupted requests, preservation and archive failure paths.

Keep new public API/output choices provisional until the user reviews their meaning.
Do not publish a release or upload to PyPI without explicit user approval.
Preserve the private repository and use reviewable changes on codex/ branches.

Git tracks source, package metadata, tests, CI and documentation. Research data,
archives, logs, builds and credentials stay outside Git. Add DVC, containers or
MLflow only when a concrete need exists. Do not use sudo, force-push or delete
unrelated user files.
