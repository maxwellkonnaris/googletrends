provider_text <- function(values, flags = TRUE, start = 1609632000, step = 604800) {
  points <- lapply(seq_len(nrow(values)), function(i) {
    point <- list(time = as.character(start + (i - 1L) * step), value = as.list(unname(values[i, ])),
                  formattedValue = as.list(ifelse(values[i, ] == 0, "<1", as.character(values[i, ]))))
    if (flags) { point$hasData <- rep(list(TRUE), ncol(values)); point$isPartial <- FALSE }
    point
  })
  trendspull:::.json(list(default = list(timelineData = points)))
}

offline_backend <- function(env = parent.frame(), provider = NULL) {
  if (is.null(provider)) provider <- function(keywords, ...) {
    list(explore = "{}", multiline = provider_text(matrix(c(100, 20, 50, 0, 25, 5), ncol = 2, byrow = TRUE), flags = FALSE), resolution = "WEEK")
  }
  testthat::local_mocked_bindings(
    .new_client = function(...) list(timeline = provider, close = function() NULL),
    .http_get = function(...) stop("Unexpected network access"),
    .pause = function(...) NULL, .package = "trendspull", .env = env)
}

amplitude_provider <- function(amplitudes, fractions = c(.5, 1, .75, .25, .5)) {
  function(keywords, ...) {
    peaks <- unname(amplitudes[keywords])
    values <- round(100 * outer(fractions, peaks) / max(peaks))
    list(explore = "{}", multiline = provider_text(values), resolution = "WEEK")
  }
}
