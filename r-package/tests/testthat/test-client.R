test_that("native R loads without Python", {
  expect_false("reticulate" %in% names(getNamespaceImports("trendspull")))
  expect_setequal(getNamespaceExports("trendspull"), c("pull_trends", "plot_trends", "selected_proportions"))
})

test_that("timeline parser rejects malformed provider values", {
  parse <- trendspull:::.timeline
  for (bad in list(TRUE, -1, 101, 1.5, "10", NULL)) {
    payload <- list(default = list(timelineData = list(list(time = "1609632000", value = list(bad)))))
    expect_error(parse(trendspull:::.json(payload), "a"), "integer Google index")
  }
  for (bad in list(NULL, list(), list(TRUE, FALSE))) {
    payload <- list(default = list(timelineData = list(list(time = "1609632000", value = list(10), hasData = bad))))
    expect_error(parse(trendspull:::.json(payload), "a"), "hasData entries")
  }
  text <- provider_text(matrix(c(100, 50), ncol = 1), step = 0)
  expect_error(parse(text, "a"), "unique and increasing")
  expect_error(parse('{"default":{"timelineData":{}}}', "a"), "array")
  expect_error(parse("not JSON", "a"), "no JSON")
})

test_that("HTTP retries are bounded and warm the requested geography", {
  calls <- list()
  statuses <- c(200L, 429L, 200L, 200L, 200L)
  index <- 0L
  definition <- trendspull:::.json(list(keywords = list(list(keyword = "a")),
    widgets = list(list(id = "TIMESERIES", token = "token", request = list(resolution = "WEEK")))))
  testthat::local_mocked_bindings(.http_get = function(url, params, handle) {
    index <<- index + 1L
    calls[[index]] <<- list(url = url, params = params)
    list(status = statuses[index], text = if (grepl("/api/explore$", url)) definition else provider_text(matrix(100)))
  }, .pause = function(...) NULL, .package = "trendspull")
  client <- trendspull:::.new_client("en-US", 2L, 60, "GB")
  on.exit(client$close(), add = TRUE)
  result <- client$timeline("a", "GB", "2021-01-01", "2021-12-31", 0L, "web")
  expect_equal(result$resolution, "WEEK")
  expect_equal(length(calls), 5)
  expect_identical(calls[[1]]$params$geo, "GB")
  expect_identical(calls[[3]]$params$geo, "GB")
  statuses[] <- 403L
  index <- 0L
  expect_error(client$timeline("a", "GB", "2021-01-01", "2021-12-31", 0L, "web"), "HTTP 403")
  expect_equal(index, 1L)
  statuses[] <- 503L
  index <- 0L
  expect_error(client$timeline("a", "GB", "2021-01-01", "2021-12-31", 0L, "web"), "after 2 attempts")
  expect_equal(index, 2L)
})
