# Working on trendspull

Preserve the CLI names, study config, and output paths unless a change is justified.
Keep Google website responses immutable after collection; verify hashes and study
specifications before assembly. Preserve low-volume, unavailable, and partial flags.
Do not infer raw censoring from averaged, rescaled indices.

Use offline synthetic fixtures for tests: `python -m pytest -q`. Keep tests independent
of Google access. Do not run the full 84-series collection or upload research data
as part of a code change. Run one bounded live query only when access testing is in scope.

Distinguish sample moments, sensitivity parameters, population claims, and causal
effects. Do not claim independent daily Google samples without evidence. Log-floor
choices and complete-date exclusions are analysis assumptions, not known truths.

Keep raw data and generated analysis outputs out of Git. Use Git for source,
configuration, tests, CI, and documentation. Add DVC, containers, or MLflow only
when the actual data scale, portability, or experiment tracking need justifies them.
Do not delete user files, use sudo, force-push, or commit credentials.
