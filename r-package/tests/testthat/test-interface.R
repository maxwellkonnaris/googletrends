test_that("collection keeps metadata, UTC instants, zeros and missing flags", {
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31", geo = "US-CA")
  expect_s3_class(data, "data.frame")
  expect_equal(dim(data), c(6, 15))
  expect_equal(data$value, c(100L, 20L, 50L, 0L, 25L, 5L))
  expect_true(all(is.na(data$has_data)))
  expect_true(all(is.na(data$is_partial)))
  expect_s3_class(data$date, "POSIXct")
  expect_equal(as.numeric(data$date[1]), 1609632000)
  expect_equal(attr(data, "trendspull")$status, "complete")
  path <- tempfile(fileext = ".rds")
  saveRDS(data, path)
  result <- selected_proportions(readRDS(path))
  expect_equal(dim(result), c(2, 3))
  expect_identical(rownames(result), c("smoke", "wildfire"))
  expect_equal(as.numeric(colSums(result)), rep(1, 3))
  expect_equal(as.numeric(result[2, ]), c(1/6, 0, 1/6))
  expect_equal(nrow(pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31", min_gap_days = 14)), 4)
})

test_that("G-TAB and proportions use the reference peak", {
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31", calibration = "gtab")
  expect_equal(data$calibrated_value, data$value / 100)
  expect_equal(as.numeric(selected_proportions(data)[1, ]), c(5/6, 1, 5/6))
  usable <- !is.na(data$calibrated_lower) & !is.na(data$calibrated_upper)
  expect_true(all(data$calibrated_lower[usable] <= data$calibrated_value[usable]))
  expect_true(all(data$calibrated_upper[usable] >= data$calibrated_value[usable]))
  expect_true(all(is.na(data$calibrated_lower[data$value == 0])))
})

test_that("R plot has one shared scale and preserves input", {
  grDevices::pdf(file = NULL)
  on.exit(grDevices::dev.off(), add = TRUE)
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31")
  before <- serialize(data, NULL)
  figure <- plot_trends(data)
  expect_s3_class(figure, "patchwork")
  overview <- figure[[1]]
  detail <- figure[[2]]
  expect_equal(overview$data$display_value, c(100, 50, 25, 20, 0, 5))
  expect_equal(detail$data$display_value, overview$data$display_value)
  expect_equal(overview$scales$get_scales("y")$limits, c(0, 100))
  expect_equal(detail$scales$get_scales("y")$limits, c(0, 100))
  expect_equal(serialize(data, NULL), before)
  file <- tempfile(fileext = ".pdf")
  ggplot2::ggsave(file, figure, width = 11, height = 7)
  expect_gt(file.info(file)$size, 1000)
})

test_that("R rejects missing metadata, mixed geographies and invalid integers", {
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31", geo = c("US", "GB"))
  expect_error(selected_proportions(data), "one geography")
  expect_error(plot_trends(data), "one geography")
  expect_equal(dim(selected_proportions(data[data$geo == "GB", ])), c(2, 3))
  attr(data, "trendspull") <- NULL
  expect_error(selected_proportions(data), "original pull_trends metadata")
  for (bad in list(NA_real_, Inf, 2.5, TRUE, c(1, 2))) {
    expect_error(pull_trends("smoke", "2021-01-01", "2021-12-31", min_gap_days = bad), "finite integer")
  }
})

test_that("R keeps zeros and supports one-date plots", {
  grDevices::pdf(file = NULL)
  on.exit(grDevices::dev.off(), add = TRUE)
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31")
  one <- data[1:2, ]
  expect_s3_class(plot_trends(one), "patchwork")
  expect_no_warning(ggplot2::ggplotGrob(plot_trends(one)[[1]]))
  data$value[] <- 0L
  expect_error(plot_trends(data), "entirely zero")
  expect_error(selected_proportions(data), "positive total")
  data$date <- as.Date(data$date)
  expect_error(plot_trends(data), "UTC timestamps")
})

test_that("R plots retain separate hourly timestamps", {
  grDevices::pdf(file = NULL)
  on.exit(grDevices::dev.off(), add = TRUE)
  offline_backend()
  data <- pull_trends(c("smoke", "wildfire"), "2021-01-01", "2021-12-31")
  data$date <- data$date[1] + rep(c(0, 3600, 7200), each = 2)
  drawn <- plot_trends(data)[[1]]$data
  expect_equal(length(unique(drawn$date)), 3)
  expect_equal(as.numeric(diff(sort(unique(drawn$date))), units = "hours"), c(1, 1))
  expect_no_warning(ggplot2::ggplotGrob(plot_trends(data)[[1]]))
})
