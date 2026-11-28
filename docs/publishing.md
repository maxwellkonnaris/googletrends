# Publishing a release

The Python distribution and native R package both use the name `trendspull`.
Keep their versions in `pyproject.toml`, `src/trendspull/_api.py`,
`r-package/DESCRIPTION` and `r-package/R/collect.R` synchronized. The R package
requires no Python. Keep data, notebooks, build files and credentials out of Git.

Before tagging, run the installed-wheel tests and the native R checks in CI.
The R-versus-Python comparisons use identical synthetic Google responses,
including rounding, flagged observations and adaptive calibration. A passing
suite validates those cases; it does not establish live Google availability.

## PyPI

Configure a pending Trusted Publisher in the maintainer's
[PyPI publishing settings](https://pypi.org/manage/account/publishing/):

| Field | Value |
|---|---|
| Project | `trendspull` |
| GitHub owner | `maxwellkonnaris` |
| Repository | `googletrends` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

This uses short-lived GitHub credentials; no API token belongs in the repository.
See [PyPI's instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
A pending publisher does not reserve the package name.

After checks pass, tag the reviewed commit `v0.1.0` and run **Publish Python
package** on that tag from GitHub Actions. The workflow checks the version,
builds both distributions, validates their metadata, runs the installed-wheel
tests and uploads through Trusted Publishing. Confirm installation in a fresh
environment with `python -m pip install 'trendspull[plot]==0.1.0'` and
`python -c 'from trendspull import pull_trends, selected_proportions, plot_trends; print("OK")'`.
The expected smoke-test output is `OK`; it does not contact Google.

## CRAN

Build with `R CMD build r-package` and check the resulting archive using
`R CMD check --as-cran --no-manual trendspull_0.1.0.tar.gz`.
Review the Linux, macOS and Windows checks and any incoming notes. The initial
submission naturally identifies a new package and its maintainer.

Submit that archive through the [CRAN submission form](https://cran.r-project.org/submit.html)
using the public contact in DESCRIPTION. The maintainer must receive and act on
CRAN's verification email. Submission is not acceptance: resolve reviewer
requests before advertising `install.packages("trendspull")` as available.
Once accepted, verify a fresh installation and run
`Rscript -e 'library(trendspull); stopifnot(is.function(pull_trends)); cat("OK\\n")'`.
The expected smoke-test output is `OK`.

Update the README installation instructions only when the registry installations
have been verified. Keep submission-specific check notes with the submission,
not in the user walkthrough.
