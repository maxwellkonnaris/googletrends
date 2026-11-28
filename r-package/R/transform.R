.interest_matrix <- function(data) {
  if (!is.data.frame(data) || !nrow(data) || anyDuplicated(names(data))) stop("data must be a nonempty pull_trends data.frame with unique columns.", call. = FALSE)
  meta <- attr(data, "trendspull", exact = TRUE)
  if (!is.list(meta) || !identical(meta$status, "complete")) stop("Keep the original pull_trends metadata; CSV exports omit it.", call. = FALSE)
  method <- meta$calibration$method
  if (!identical(method, "gtab") && !identical(method, "none")) stop("data must describe one raw or G-TAB collection.", call. = FALSE)
  field <- if (method == "gtab") "calibrated_value" else "value"
  required <- c("keyword", "date", "geo", "request_id", field)
  if (!all(required %in% names(data)) || anyNA(data[required])) stop("data requires nonmissing ", paste(required, collapse = ", "), call. = FALSE)
  if (length(unique(data$geo)) != 1L) stop("Select one geography first.", call. = FALSE)
  if (!inherits(data$date, "POSIXct") || !identical(attr(data$date, "tzone"), "UTC")) stop("date must contain the original UTC timestamps.", call. = FALSE)
  requests <- meta$requests
  if (!is.list(requests) || any(!vapply(requests, function(r) is.list(r) && .scalar(r$request_id, "character"), logical(1)))) stop("Collection request metadata is incomplete.", call. = FALSE)
  matching <- Filter(function(r) identical(r$geo, data$geo[1]), requests)
  allowed <- vapply(matching, function(r) r$request_id, character(1))
  if (!all(data$request_id %in% allowed) || (method == "none" && length(unique(data$request_id)) != 1L)) stop("Use one pull_trends call; separate raw comparisons have different scales.", call. = FALSE)
  if (anyDuplicated(data[c("keyword", "date")])) stop("Each term must occur once per date.", call. = FALSE)
  values <- data[[field]]
  if (!is.numeric(values) || is.complex(values) || any(!is.finite(values)) || any(values < 0)) stop(field, " must contain finite nonnegative numeric values.", call. = FALSE)
  terms <- unique(data$keyword)
  dates <- sort(unique(data$date))
  matrix <- matrix(NA_real_, length(terms), length(dates), dimnames = list(terms,
    format(dates, "%Y-%m-%dT%H:%M:%OS6Z", tz = "UTC")))
  matrix[cbind(match(data$keyword, terms), match(data$date, dates))] <- values
  if (anyNA(matrix)) stop("Every selected term must have the same dates; missing cells are not filled.", call. = FALSE)
  list(matrix = matrix, dates = dates, field = field)
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
#' @examples
#' \dontrun{
#' data <- pull_trends(c("wildfire", "smoke"), "2025-01-01", "2025-12-31")
#' proportions <- selected_proportions(data)
#' colSums(proportions)
#' }
#' @export
selected_proportions <- function(data) {
  interest <- .interest_matrix(data)
  matrix <- interest$matrix
  peaks <- apply(matrix, 2, max)
  if (any(peaks <= 0)) stop("Each date must have a positive total across the selected terms.", call. = FALSE)
  scaled <- sweep(matrix, 2, peaks, "/")
  result <- sweep(scaled, 2, colSums(scaled), "/")
  attr(result, "selected_proportions") <- list(geo = data$geo[1], value_column = interest$field,
    keywords = rownames(matrix), request_ids = sort(unique(data$request_id)),
    denominator = "sum across the supplied terms at each date")
  result
}

.plot_data <- function(data) {
  interest <- .interest_matrix(data)
  matrix <- interest$matrix
  peak <- max(matrix)
  if (peak <= 0) stop("Cannot plot entirely zero interest.", call. = FALSE)
  display <- matrix / peak * 100
  data.frame(keyword = rep(rownames(matrix), each = ncol(matrix)),
    date = rep(interest$dates, times = nrow(matrix)), display_value = as.vector(t(display)))
}
