#' Collect Google Trends timelines
#'
#' Uses the same collection rules as the Python package. Up to five terms share one raw comparison;
#' larger sets use G-TAB automatically. Retains zeros, provider timestamps, raw
#' indices, quality flags and provenance. A failed collection raises an error.
#' @param keywords Search terms or Google Topic IDs.
#' @param start,end Fixed dates as `"YYYY-MM-DD"` strings.
#' @param geo Geography code(s); `""` means worldwide.
#' @param search_type One of `"web"`, `"images"`, `"news"`, `"youtube"`, `"shopping"`.
#' @param category Google category ID; zero means all categories.
#' @param language Interface language; does not filter searches by language.
#' @param min_gap_days Minimum elapsed days between retained dates, or `NULL`
#'   to keep all dates. Spacing does not guarantee independence.
#' @param archive Optional directory for raw responses and provenance.
#' @param delay Two numbers giving the minimum/maximum pause in seconds.
#' @param max_attempts Maximum attempts per chart request.
#' @param timeout Timeout in seconds per request.
#' @param calibration `"auto"`, `"none"` or `"gtab"`.
#' @param reference G-TAB reference term; defaults to the first keyword.
#' @param anchors Optional additional G-TAB bridge terms.
#' @param min_anchor_peak Minimum usable raw peak for calibration links.
#' @param max_comparisons Maximum number of comparison charts across geographies.
#' @return A data.frame with one row per date, keyword and geography. Dates are
#'   POSIXct UTC. The `trendspull` attribute holds collection metadata. G-TAB adds
#'   `calibrated_value` and conditional rounding bounds; raw `value` is preserved.
#' @examples
#' \dontrun{
#' data <- pull_trends(c("wildfire", "smoke"),
#'                     "2025-01-01", "2025-12-31", geo = "US-CA")
#' head(data)
#' }
#' @export
pull_trends <- function(keywords, start, end, geo = "", search_type = "web",
                        category = 0, language = "en-US", min_gap_days = NULL,
                        archive = NULL, delay = c(8, 20), max_attempts = 3,
                        timeout = 60, calibration = "auto", reference = NULL,
                        anchors = NULL, min_anchor_peak = 10, max_comparisons = 100) {
  keywords <- .strings(keywords, "keywords")
  geos <- .strings(geo, "geo", allow_empty = TRUE)
  fixed_date <- function(x) {
    if (!.scalar(x, "character") || !grepl("^[0-9]{4}-[0-9]{2}-[0-9]{2}$", x)) return(FALSE)
    parsed <- as.Date(x, format = "%Y-%m-%d")
    !is.na(parsed) && identical(format(parsed, "%Y-%m-%d"), x)
  }
  if (!fixed_date(start) || !fixed_date(end) || start > end) stop("start and end must be valid ordered YYYY-MM-DD dates.", call. = FALSE)
  if (any(!grepl("^([A-Z]{2}(-[A-Z0-9]+)*)?$", geos))) stop("Invalid geography code.", call. = FALSE)
  category <- .integer_option(category, "category")
  if (category < 0) stop("category must be nonnegative.", call. = FALSE)
  if (!.scalar(search_type, "character") || !(search_type %in% c("web", "images", "news", "youtube", "shopping"))) stop("Invalid search_type.", call. = FALSE)
  if (!.scalar(language, "character") || !grepl("^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$", language)) stop("Invalid language tag.", call. = FALSE)
  if (!is.numeric(delay) || length(delay) != 2L || anyNA(delay) || any(!is.finite(delay)) || min(delay) < 0 || delay[1] > delay[2]) stop("delay must be an ordered finite nonnegative pair.", call. = FALSE)
  max_attempts <- .integer_option(max_attempts, "max_attempts")
  if (max_attempts < 1) stop("max_attempts must be positive.", call. = FALSE)
  if (!.scalar(timeout, "numeric") || !is.finite(timeout) || timeout <= 0) stop("timeout must be finite and positive.", call. = FALSE)
  min_gap_days <- .integer_option(min_gap_days, "min_gap_days", nullable = TRUE)
  if (!is.null(min_gap_days) && min_gap_days < 1) stop("min_gap_days must be positive.", call. = FALSE)
  if (!.scalar(calibration, "character") || !(calibration %in% c("auto", "none", "gtab"))) stop("calibration must be auto, none or gtab.", call. = FALSE)
  calibrated <- calibration == "gtab" || (calibration == "auto" && length(keywords) > 5L)
  if (!calibrated && length(keywords) > 5L) stop("At most five keywords are allowed without G-TAB.", call. = FALSE)
  bridges <- if (is.null(anchors)) character() else .strings(anchors, "anchors")
  if (!calibrated && (!is.null(reference) || !is.null(anchors))) stop("reference and anchors require G-TAB.", call. = FALSE)
  terms <- unique(c(keywords, bridges))
  if (!is.null(reference) && (!.scalar(reference, "character") || !(reference %in% terms))) stop("reference must be a keyword or anchor.", call. = FALSE)
  if (is.null(reference)) reference <- keywords[1]
  min_anchor_peak <- .integer_option(min_anchor_peak, "min_anchor_peak")
  if (min_anchor_peak < 2 || min_anchor_peak > 100) stop("min_anchor_peak must be between 2 and 100.", call. = FALSE)
  max_comparisons <- .integer_option(max_comparisons, "max_comparisons")
  if (max_comparisons < 1) stop("max_comparisons must be positive.", call. = FALSE)
  groups <- if (calibrated) .groups(terms) else list(keywords)
  if (length(groups) * length(geos) > max_comparisons) stop("Planned comparisons exceed max_comparisons.", call. = FALSE)
  if (!is.null(archive) && (!.scalar(archive, "character") || !nzchar(archive))) stop("archive must be a directory path or NULL.", call. = FALSE)
  manifest <- list(version = "0.1.0", source = "Google Trends website", started_at = .now(), status = "running",
    settings = list(keywords = as.list(keywords), start = start, end = end, geo = as.list(geos), category = category,
      search_type = search_type, language = language, tz = 0, delay = as.list(delay), max_attempts = max_attempts,
      timeout = timeout, min_gap_days = min_gap_days, calibration = calibration,
      reference = if (calibrated) reference else NULL, anchors = as.list(bridges),
      min_anchor_peak = min_anchor_peak, max_comparisons = max_comparisons),
    normalization = if (calibrated) "G-TAB: fractions of reference usable period peak, separately per geography" else "shared keyword scale within each geography request",
    calibration = list(method = if (calibrated) "gtab" else "none", geographies = list(),
      citation = if (calibrated) "https://doi.org/10.1145/3340531.3412075" else NULL),
    runtime = list(R = as.character(getRversion()), curl = as.character(utils::packageVersion("curl")),
      jsonlite = as.character(utils::packageVersion("jsonlite"))), requests = list())
  run_dir <- NULL
  if (!is.null(archive)) {
    dir.create(archive, recursive = TRUE, showWarnings = FALSE)
    run_dir <- file.path(archive, paste0("run-", .id()))
    if (!dir.create(run_dir)) stop("Cannot create archive run directory.", call. = FALSE)
    run_dir <- normalizePath(run_dir, winslash = "/", mustWork = TRUE)
    .atomic(file.path(run_dir, "manifest.json"), manifest)
  }
  current <- 0L
  client <- NULL
  on.exit(if (!is.null(client)) client$close(), add = TRUE)
  save_manifest <- function() if (!is.null(run_dir)) .atomic(file.path(run_dir, "manifest.json"), manifest)
  fetch <- function(group, region) {
    if (length(manifest$requests) >= max_comparisons) stop("G-TAB reached max_comparisons; calibration is incomplete.", call. = FALSE)
    if (length(manifest$requests)) .pause(delay[1], delay[2])
    current <<- length(manifest$requests) + 1L
    entry <- list(request_id = .id(), keywords = as.list(group), geo = region, requested_at = .now(), status = "running")
    manifest$requests[[current]] <<- entry
    response <- client$timeline(group, region, start, end, category, search_type)
    retrieved <- Sys.time()
    if (!is.null(run_dir)) {
      entry$file <- paste0(entry$request_id, ".json")
      entry$sha256 <- .atomic(file.path(run_dir, entry$file), response[c("explore", "multiline")])
      manifest$requests[[current]] <<- entry
    }
    rows <- .timeline(response$multiline, group)
    entry$provider_row_count <- nrow(rows)
    if (!calibrated) rows <- .space_dates(rows, min_gap_days)
    entry$status <- if (nrow(rows)) "ok" else "empty"
    entry$row_count <- nrow(rows)
    entry$retrieved_at <- format(retrieved, "%Y-%m-%dT%H:%M:%OS6Z", tz = "UTC")
    entry$resolution <- response$resolution
    rows$geo <- rep(region, nrow(rows))
    rows$start <- rep(start, nrow(rows))
    rows$end <- rep(end, nrow(rows))
    rows$category <- rep(category, nrow(rows))
    rows$search_type <- rep(search_type, nrow(rows))
    rows$language <- rep(language, nrow(rows))
    rows$retrieved_at <- rep(as.POSIXct(retrieved, tz = "UTC"), nrow(rows))
    rows$request_id <- rep(entry$request_id, nrow(rows))
    manifest$requests[[current]] <<- entry
    if (!nrow(rows)) warning("Google returned an empty timeline for ", paste(group, collapse = ", "), " in ", region, call. = FALSE)
    save_manifest()
    list(request_id = entry$request_id, keywords = group, resolution = response$resolution, rows = rows)
  }
  fail <- function(error) {
    manifest$status <<- "failed"
    manifest$completed_at <<- .now()
    manifest$error <<- conditionMessage(error)
    if (current > 0L && identical(manifest$requests[[current]]$status, "running")) {
      manifest$requests[[current]]$status <<- "failed"
      manifest$requests[[current]]$error <<- conditionMessage(error)
    }
    tryCatch(save_manifest(), error = function(e) warning("Could not record archive failure: ", conditionMessage(e), call. = FALSE))
    if (inherits(error, "interrupt")) stop(error)
    stop("Google Trends collection failed: ", conditionMessage(error), call. = FALSE)
  }
  data <- tryCatch({
    client <- .new_client(language, max_attempts, timeout, geo = geos[1])
    records <- list()
    for (region in geos) {
      comparisons <- lapply(groups, fetch, region = region)
      if (calibrated) {
        repeat {
          pair <- .next_bridge(comparisons, keywords, reference, min_anchor_peak)
          if (is.null(pair)) break
          comparisons[[length(comparisons) + 1L]] <- fetch(pair, region)
        }
        result <- .calibrate(comparisons, keywords, reference, min_anchor_peak)
        records[[length(records) + 1L]] <- .space_dates(result$rows, min_gap_days)
        manifest$calibration$geographies[region] <- list(result$details)
      } else records[[length(records) + 1L]] <- comparisons[[1]]$rows
    }
    output <- do.call(rbind, records)
    if (calibrated) for (i in seq_along(manifest$requests)) {
      manifest$requests[[i]]$row_count <- sum(output$request_id == manifest$requests[[i]]$request_id)
    }
    output <- output[names(.empty_table(calibrated))]
    rownames(output) <- NULL
    manifest$status <- "complete"
    manifest$completed_at <- .now()
    manifest$row_count <- nrow(output)
    save_manifest()
    output
  }, error = fail, interrupt = fail)
  attr(data, "trendspull") <- c(manifest, list(archive = run_dir, timezone = "UTC"))
  data
}

.space_dates <- function(rows, gap) {
  if (is.null(gap) || !nrow(rows)) return(rows)
  dates <- unique(rows$date)
  selected <- dates[1]
  for (date in dates[-1]) if (as.numeric(date) - as.numeric(utils::tail(selected, 1)) >= gap * 86400) selected <- c(selected, date)
  rows[rows$date %in% selected, , drop = FALSE]
}
