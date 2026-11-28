#' Install the Python collection backend
#'
#' Run once in a fresh R session. Installs the pinned Python backend into a
#' dedicated environment and selects it for this session. Requires Python 3.11+
#' and network access; loading the R package never installs software.
#' Unset `RETICULATE_PYTHON` before setup to allow selection of the new environment.
#' @param envname Name or path of the Python environment.
#' @param method Environment type: `"auto"`, `"virtualenv"` or `"conda"`.
#' @param python Optional path to Python 3.11+ for creating a virtual environment.
#'   By default, uses `python3` or `python` on PATH. Requires venv and pip support.
#' @return The environment name, invisibly.
#' @export
install_backend <- function(envname = "r-trendspull", method = "auto", python = NULL) {
  method <- match.arg(method, c("auto", "virtualenv", "conda"))
  if (reticulate::py_available(initialize = FALSE)) {
    stop("Restart R before running install_backend().", call. = FALSE)
  }
  if (nzchar(Sys.getenv("RETICULATE_PYTHON"))) {
    stop("Unset RETICULATE_PYTHON before setup, or use its existing environment directly.", call. = FALSE)
  }
  conda <- method == "conda" || (method == "auto" && .Platform$OS.type == "windows")
  if (conda && !is.null(python)) stop("python is only used with method = 'virtualenv'.", call. = FALSE)
  if (!conda && !reticulate::virtualenv_exists(envname)) {
    if (is.null(python)) {
      available <- unname(Sys.which(c("python3", "python")))
      python <- if (any(nzchar(available))) available[nzchar(available)][1] else NULL
    }
    reticulate::virtualenv_create(envname, python = python)
  }
  reticulate::py_install(
    "git+https://github.com/maxwellkonnaris/googletrends.git@d71efd0769107800697ad2585751b0f736b05fee",
    envname = envname, method = method, pip = TRUE
  )
  if (conda) {
    reticulate::use_condaenv(envname, required = TRUE)
  } else {
    reticulate::use_virtualenv(envname, required = TRUE)
  }
  invisible(envname)
}

.backend <- function() {
  module <- tryCatch(reticulate::import("trendspull", convert = FALSE), error = function(e) {
    stop("Python backend unavailable. Run install_backend() in a fresh R session, ",
         "or select an environment containing trendspull.\n", conditionMessage(e), call. = FALSE)
  })
  if (!reticulate::py_has_attr(module, "plot_trends")) {
    stop("Update the Python backend with install_backend() in a fresh R session.", call. = FALSE)
  }
  module
}

.python_data <- function(data) {
  if (!is.data.frame(data) || is.null(attr(data, "trendspull", exact = TRUE))) {
    stop("Use the data.frame from pull_trends(), retaining its trendspull attribute.", call. = FALSE)
  }
  if (!inherits(data$date, "POSIXct")) stop("date must contain the original POSIXct timestamps.", call. = FALSE)
  frame <- reticulate::r_to_py(data, convert = FALSE)
  pandas <- reticulate::import("pandas", convert = FALSE)
  frame$date <- pandas$to_datetime(frame$date, utc = TRUE)
  frame$attrs$update(reticulate::dict(trendspull = attr(data, "trendspull", exact = TRUE)))
  frame
}

.integer_option <- function(x, name, nullable = FALSE) {
  if (nullable && is.null(x)) return(NULL)
  if (!is.numeric(x) || length(x) != 1L || is.na(x) || !is.finite(x) ||
      x != trunc(x) || abs(x) > .Machine$integer.max) {
    stop(name, " must be a finite integer.", call. = FALSE)
  }
  as.integer(x)
}
