.groups <- function(terms) {
  if (length(terms) <= 5L) return(list(terms))
  lapply(seq_len(length(terms) - 4L), function(i) terms[i:(i + 4L)])
}

.usable <- function(rows) {
  (is.na(rows$has_data) | rows$has_data) &
    (is.na(rows$is_partial) | !rows$is_partial) & !rows$low_volume
}

.interval <- function(value) {
  cbind(ifelse(value == 100, 100, pmax(0, value - 0.5)), ifelse(value == 100, 100, value + 0.5))
}

.peaks <- function(rows, terms) {
  stats::setNames(vapply(terms, function(term) max(c(0, rows$value[rows$keyword == term & .usable(rows)])), numeric(1)), terms)
}

.bank <- function(comparisons, min_anchor_peak) {
  graph <- sources <- list()
  grid <- resolution <- NULL
  for (comparison in comparisons) {
    rows <- comparison$rows
    dates <- sort(unique(rows$date))
    if (!length(dates)) stop("G-TAB cannot calibrate an empty comparison.", call. = FALSE)
    if (!is.null(grid) && (!identical(grid, dates) || !identical(resolution, comparison$resolution))) {
      stop("G-TAB requires identical timestamps and resolution; no alignment is applied.", call. = FALSE)
    }
    grid <- dates
    resolution <- comparison$resolution
    peaks <- .peaks(rows, comparison$keywords)
    for (term in comparison$keywords) {
      if (!(term %in% names(graph))) graph[term] <- list(list())
      if (peaks[[term]] > if (is.null(sources[[term]])) 0 else sources[[term]]$peak) {
        sources[[term]] <- list(peak = peaks[[term]], rows = rows[rows$keyword == term, , drop = FALSE])
      }
    }
    for (origin in comparison$keywords) for (target in setdiff(comparison$keywords, origin)) {
      if (min(peaks[c(origin, target)]) < min_anchor_peak) next
      a <- .interval(peaks[[target]])
      b <- .interval(peaks[[origin]])
      lo <- a[1] / b[2]
      hi <- a[2] / b[1]
      cost <- log(hi / lo)
      old <- graph[[origin]][[target]]
      if (is.null(old) || cost < old$cost) {
        graph[[origin]][[target]] <- list(cost = cost, ratio = peaks[[target]] / peaks[[origin]],
          lower = lo, upper = hi, request_id = comparison$request_id)
      }
    }
  }
  list(graph = graph, sources = sources)
}

.paths <- function(graph, reference) {
  paths <- stats::setNames(list(list(cost = 0, ratio = 1, lower = 1, upper = 1,
                                   nodes = reference, requests = character())), reference)
  visited <- character()
  repeat {
    remaining <- setdiff(names(paths), visited)
    if (!length(remaining)) break
    costs <- vapply(paths[remaining], function(x) x$cost, numeric(1))
    origin <- remaining[order(costs, remaining, method = "radix")][1]
    path <- paths[[origin]]
    visited <- c(visited, origin)
    for (target in names(graph[[origin]])) {
      edge <- graph[[origin]][[target]]
      cost <- path$cost + edge$cost
      if (is.null(paths[[target]]) || cost < paths[[target]]$cost) {
        paths[[target]] <- list(cost = cost, ratio = path$ratio * edge$ratio,
          lower = path$lower * edge$lower, upper = path$upper * edge$upper,
          nodes = c(path$nodes, target), requests = c(path$requests, edge$request_id))
      }
    }
  }
  paths
}

.next_bridge <- function(comparisons, keywords, reference, min_anchor_peak) {
  bank <- .bank(comparisons, min_anchor_peak)
  paths <- .paths(bank$graph, reference)
  if (all(keywords %in% names(paths))) return(NULL)
  terms <- names(bank$graph)
  missing <- setdiff(terms, names(paths))
  pair_id <- function(pair) .json(as.list(sort(pair, method = "radix")))
  pairs <- Filter(function(x) length(x$keywords) == 2L, comparisons)
  tried <- vapply(pairs, function(x) pair_id(x$keywords), character(1))
  candidates <- list()
  for (comparison in comparisons) {
    peaks <- .peaks(comparison$rows, comparison$keywords)
    for (target in terms[terms %in% missing & terms %in% names(peaks)]) {
      for (anchor in comparison$keywords) {
        if (!(anchor %in% names(paths)) || peaks[[anchor]] <= 0 || pair_id(c(anchor, target)) %in% tried) next
        candidates[[length(candidates) + 1L]] <- data.frame(
          distance = abs(log(max(peaks[[target]], 0.5) / peaks[[anchor]])),
          position = match(target, terms), anchor = anchor, target = target)
      }
    }
  }
  if (!length(candidates)) return(NULL)
  candidates <- do.call(rbind, candidates)
  first <- candidates[order(candidates$distance, candidates$position, candidates$anchor, candidates$target, method = "radix")[1], ]
  c(first$anchor, first$target)
}

.calibrate <- function(comparisons, keywords, reference, min_anchor_peak) {
  bank <- .bank(comparisons, min_anchor_peak)
  paths <- .paths(bank$graph, reference)
  missing <- setdiff(keywords, intersect(names(paths), names(bank$sources)))
  if (length(missing)) stop("G-TAB has no reliable anchor path to ", paste(missing, collapse = ", "),
    "; add anchors of intermediate popularity or change the time/region. Zero or insufficient-volume series cannot be recovered.", call. = FALSE)
  output <- details <- list()
  for (term in keywords) {
    path <- paths[[term]]
    source <- bank$sources[[term]]
    peak <- .interval(source$peak)
    factor <- path$ratio / source$peak
    lower <- path$lower / peak[2]
    upper <- path$upper / peak[1]
    if (any(!is.finite(c(factor, lower, upper))) || min(factor, lower, upper) <= 0) {
      stop("G-TAB calibration overflow or underflow; use a shorter anchor chain.", call. = FALSE)
    }
    details[[term]] <- list(peak_ratio = path$ratio, peak_ratio_lower = path$lower, peak_ratio_upper = path$upper,
      factor = factor, factor_lower = lower, factor_upper = upper, path = as.list(path$nodes),
      path_request_ids = as.list(path$requests), source_request_id = source$rows$request_id[1], source_peak = source$peak)
    rows <- source$rows
    bounds <- .interval(rows$value)
    rows$calibrated_value <- rows$value * factor
    rows$calibrated_lower <- ifelse(.usable(rows), bounds[, 1] * lower, NA_real_)
    rows$calibrated_upper <- ifelse(.usable(rows), bounds[, 2] * upper, NA_real_)
    rows$calibration_factor <- factor
    rows$calibration_reference <- reference
    output[[term]] <- rows
  }
  rows <- do.call(rbind, output)
  rows <- rows[order(rows$date, match(rows$keyword, keywords)), , drop = FALSE]
  rownames(rows) <- NULL
  list(rows = rows, details = list(reference = reference, terms = details, min_anchor_peak = min_anchor_peak,
    uncertainty = "conditional integer-rounding bounds; not sampling confidence intervals"))
}
