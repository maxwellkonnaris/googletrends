#' Collect Google Trends timelines
#'
#' Calls the same collector as Python. Up to five terms share one raw comparison;
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
#' @export
pull_trends <- function(keywords, start, end, geo = "", search_type = "web",
                        category = 0, language = "en-US", min_gap_days = NULL,
                        archive = NULL, delay = c(8, 20), max_attempts = 3,
                        timeout = 60, calibration = "auto", reference = NULL,
                        anchors = NULL, min_anchor_peak = 10, max_comparisons = 100) {
  result <- .backend()$pull_trends(
    keywords, start, end, geo = geo, search_type = search_type,
    category = .integer_option(category, "category"), language = language,
    min_gap_days = .integer_option(min_gap_days, "min_gap_days", nullable = TRUE),
    archive = archive, delay = delay, max_attempts = .integer_option(max_attempts, "max_attempts"),
    timeout = timeout, calibration = calibration, reference = reference, anchors = anchors,
    min_anchor_peak = .integer_option(min_anchor_peak, "min_anchor_peak"),
    max_comparisons = .integer_option(max_comparisons, "max_comparisons")
  )
  data <- reticulate::py_to_r(result)
  attr(data, "trendspull") <- reticulate::py_to_r(result$attrs$get("trendspull"))
  data
}

#' Calculate proportions among selected terms
#'
#' Uses calibrated values for G-TAB, otherwise the shared raw scale. Keeps zeros
#' without filling missing cells or adding pseudocounts. Rejects mixed scales,
#' incomplete grids and dates whose selected-term total is zero.
#' @param data Original data.frame from [pull_trends()], retaining its metadata;
#'   select one geography first if the collection includes several.
#' @return A numeric matrix with terms as rows and UTC dates as columns. Each
#'   column sums to one among the supplied terms, not among all Google searches.
#' @export
selected_proportions <- function(data) {
  as.matrix(reticulate::py_to_r(.backend()$selected_proportions(.python_data(data))))
}
