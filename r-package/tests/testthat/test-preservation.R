test_that("invalid inputs fail before transport or archive creation", {
  testthat::local_mocked_bindings(.new_client = function(...) stop("NETWORK"), .package = "trendspull")
  cases <- list(list(keywords = c("a", "a")), list(keywords = character()), list(start = "2021-02-30"),
    list(end = "2020-01-01"), list(geo = "us"), list(category = TRUE), list(search_type = "invalid"),
    list(language = "not a tag"), list(delay = c(1, 0)), list(timeout = Inf), list(max_attempts = 0),
    list(calibration = "unknown"), list(reference = "b"), list(min_anchor_peak = 1),
    list(keywords = letters[1:7], calibration = "none"), list(keywords = letters[1:7], max_comparisons = 2))
  for (bad in cases) {
    archive <- tempfile()
    args <- utils::modifyList(list(keywords = "a", start = "2021-01-01", end = "2021-12-31", archive = archive), bad)
    error <- tryCatch(do.call(pull_trends, args), error = identity)
    expect_s3_class(error, "error")
    expect_false(grepl("NETWORK", conditionMessage(error)))
    expect_false(dir.exists(archive))
  }
})

test_that("archives retain raw responses, checksums and failure status", {
  offline_backend()
  root <- tempfile()
  data <- pull_trends(c("a", "b"), "2021-01-01", "2021-12-31", archive = root, min_gap_days = 14)
  meta <- attr(data, "trendspull")
  manifest <- jsonlite::fromJSON(file.path(meta$archive, "manifest.json"), simplifyVector = FALSE)
  expect_equal(manifest$status, "complete")
  expect_equal(manifest$requests[[1]]$provider_row_count, 6)
  expect_equal(manifest$requests[[1]]$row_count, 4)
  raw <- file.path(meta$archive, manifest$requests[[1]]$file)
  expect_equal(digest::digest(file = raw, algo = "sha256"), manifest$requests[[1]]$sha256)
  expect_length(jsonlite::fromJSON(raw, simplifyVector = FALSE), 2)
  offline_backend(provider = function(...) stop("provider failed"))
  root <- tempfile()
  expect_error(pull_trends(c("a", "b"), "2021-01-01", "2021-12-31", archive = root), "provider failed")
  path <- list.files(root, "manifest.json", recursive = TRUE, full.names = TRUE)
  manifest <- jsonlite::fromJSON(path, simplifyVector = FALSE)
  expect_equal(manifest$status, "failed")
  expect_equal(manifest$requests[[1]]$status, "failed")
})

test_that("helpers reject incomplete grids and mixed scales, without mutating input", {
  offline_backend()
  data <- pull_trends(c("a", "b"), "2021-01-01", "2021-12-31")
  expect_error(selected_proportions(data[-1, ]), "same dates")
  expect_error(selected_proportions(rbind(data, data[1, ])), "once per date")
  broken <- data
  broken$request_id[1] <- "unrelated"
  expect_error(selected_proportions(broken), "one pull_trends call")
  for (bad in c(-1, Inf, NaN)) {
    broken <- data
    broken$value[1] <- bad
    expect_error(selected_proportions(broken))
  }
  data$value[] <- 1e308
  before <- serialize(data, NULL)
  proportions <- selected_proportions(data)
  expect_equal(as.numeric(proportions), rep(.5, 6))
  expect_equal(serialize(data, NULL), before)
})
