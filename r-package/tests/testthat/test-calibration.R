test_that("seven terms recover the known relative amplitudes", {
  amplitudes <- c(a = 200, b = 100, c = 80, d = 50, e = 40, f = 20, g = 10)
  offline_backend(provider = amplitude_provider(amplitudes))
  data <- pull_trends(names(amplitudes), "2021-01-01", "2021-12-31", delay = c(0, 0))
  meta <- attr(data, "trendspull")
  expect_length(meta$requests, 3)
  expect_equal(nrow(data), 35)
  for (term in names(amplitudes)) {
    expect_lte(max(abs(data$calibrated_value[data$keyword == term] - c(.5, 1, .75, .25, .5) * amplitudes[[term]] / 200)), .006)
  }
  expect_equal(as.numeric(colSums(selected_proportions(data))), rep(1, 5))
  expect_equal(max(trendspull:::.plot_data(data)$display_value), 100)
  expect_equal(meta$calibration$geographies[[1]]$terms$g$source_peak, 12)
  expect_true(all(data$calibrated_lower <= data$calibrated_value))
  expect_true(all(data$calibrated_upper >= data$calibrated_value))
})

test_that("adaptive pairs recover terms hidden by dominant terms", {
  amplitudes <- c(a = 59, b = 55, c = 100, d = 7, e = 4, f = 40, g = 20)
  offline_backend(provider = amplitude_provider(amplitudes))
  data <- pull_trends(names(amplitudes), "2021-01-01", "2021-12-31", delay = c(0, 0))
  expect_gt(length(attr(data, "trendspull")$requests), 3)
  for (term in names(amplitudes)) expect_equal(
    max(data$calibrated_value[data$keyword == term]), amplitudes[[term]] / amplitudes[[1]], tolerance = .06)
  expect_error(pull_trends(names(amplitudes), "2021-01-01", "2021-12-31", max_comparisons = 3), "reached max_comparisons")
})

test_that("unusable peaks and incompatible grids fail without partial data", {
  zero <- c(a = 100, b = 10, c = 0)
  offline_backend(provider = amplitude_provider(zero))
  expect_error(pull_trends(names(zero), "2021-01-01", "2021-12-31", calibration = "gtab"), "no reliable anchor path")
  provider <- amplitude_provider(stats::setNames(seq(70, 10, -10), letters[1:7]))
  index <- 0L
  offline_backend(provider = function(...) {
    response <- provider(...)
    index <<- index + 1L
    if (index == 2L) response$resolution <- "DAY"
    response
  })
  expect_error(pull_trends(letters[1:7], "2021-01-01", "2021-12-31"), "identical timestamps and resolution")
})

test_that("spacing does not alter the full-period calibration", {
  offline_backend(provider = amplitude_provider(c(a = 100, b = 20)))
  full <- pull_trends(c("a", "b"), "2021-01-01", "2021-12-31", calibration = "gtab")
  sparse <- pull_trends(c("a", "b"), "2021-01-01", "2021-12-31", calibration = "gtab", min_gap_days = 14)
  expect_equal(sparse$calibrated_value, full$calibrated_value[full$date %in% sparse$date])
  expect_equal(unique(sparse$calibration_factor), unique(full$calibration_factor))
})
