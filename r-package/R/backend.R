.integer_option <- function(x, name, nullable = FALSE) {
  if (nullable && is.null(x)) return(NULL)
  if (!is.numeric(x) || length(x) != 1L || is.na(x) || !is.finite(x) ||
      x != trunc(x) || abs(x) > .Machine$integer.max) stop(name, " must be a finite integer.", call. = FALSE)
  as.integer(x)
}

.strings <- function(x, name, allow_empty = FALSE) {
  if (!is.character(x) || !length(x) || anyNA(x) || anyDuplicated(x) ||
      (!allow_empty && any(!nzchar(trimws(x))))) stop(name, " must contain unique, nonmissing strings.", call. = FALSE)
  unname(x)
}

.scalar <- function(x, type) is.vector(x, mode = type) && length(x) == 1L && !is.na(x)
.json <- function(x) {
  if (!is.list(x)) return(as.character(jsonlite::toJSON(x, auto_unbox = TRUE, null = "null", na = "null", digits = NA)))
  values <- vapply(x, .json, character(1))
  if (is.null(names(x))) return(paste0("[", paste(values, collapse = ","), "]"))
  # jsonlite otherwise renames the empty geography key (worldwide) to "1".
  keys <- vapply(names(x), .json, character(1))
  paste0("{", paste(paste0(keys, ":", values), collapse = ","), "}")
}
.id <- function() digest::digest(paste(Sys.time(), Sys.getpid(), tempfile()), algo = "sha256", serialize = FALSE)
.now <- function() format(Sys.time(), "%Y-%m-%dT%H:%M:%OS6Z", tz = "UTC")
.pause <- function(minimum, maximum = minimum) Sys.sleep(stats::runif(1, minimum, maximum))

.atomic <- function(path, payload) {
  temporary <- tempfile(".write-", tmpdir = dirname(path))
  writeBin(charToRaw(enc2utf8(.json(payload))), temporary)
  fs::file_move(temporary, path)
  digest::digest(file = path, algo = "sha256")
}

.google_json <- function(text) {
  begin <- regexpr("{", text, fixed = TRUE)[1]
  if (begin < 1L) stop("Google returned no JSON object.", call. = FALSE)
  jsonlite::fromJSON(substring(text, begin), simplifyVector = FALSE)
}

.entries <- function(point, name, count) {
  if (!(name %in% names(point))) return(rep(list(NULL), count))
  x <- point[[name]]
  if (!is.list(x) || !is.null(names(x)) || length(x) != count) {
    stop("Expected ", count, " ", name, " entries per timeline observation.", call. = FALSE)
  }
  x
}

.empty_table <- function(calibrated = FALSE) {
  result <- data.frame(date = as.POSIXct(character(), tz = "UTC"), keyword = character(), geo = character(),
    value = integer(), formatted_value = character(), has_data = logical(), is_partial = logical(),
    low_volume = logical(), start = character(), end = character(), category = integer(),
    search_type = character(), language = character(), retrieved_at = as.POSIXct(character(), tz = "UTC"),
    request_id = character(), stringsAsFactors = FALSE)
  if (calibrated) {
    for (name in c("calibrated_value", "calibrated_lower", "calibrated_upper", "calibration_factor")) result[[name]] <- numeric()
    result$calibration_reference <- character()
  }
  result
}

.timeline <- function(text, keywords) {
  points <- .google_json(text)$default$timelineData
  if (!is.list(points) || !is.null(names(points))) stop("Google timelineData must be an array.", call. = FALSE)
  output <- vector("list", length(points))
  times <- numeric(length(points))
  for (i in seq_along(points)) {
    point <- points[[i]]
    if (!is.list(point) || is.null(names(point))) stop("Google timeline entries must be objects.", call. = FALSE)
    values <- .entries(point, "value", length(keywords))
    flags <- .entries(point, "hasData", length(keywords))
    formatted <- .entries(point, "formattedValue", length(keywords))
    partial <- point$isPartial
    if (!is.null(partial) && !.scalar(partial, "logical")) stop("Data-quality flags must be booleans.", call. = FALSE)
    timestamp <- point$time
    if (!(.scalar(timestamp, "character") && grepl("^[+-]?[0-9]+$", timestamp)) &&
        !(.scalar(timestamp, "numeric") && is.finite(timestamp) && timestamp == trunc(timestamp))) {
      stop("Google time must be an integer Unix timestamp.", call. = FALSE)
    }
    times[i] <- as.numeric(timestamp)
    date <- as.POSIXct(times[i], origin = "1970-01-01", tz = "UTC")
    if (!is.finite(times[i]) || is.na(date)) stop("Invalid Google timestamp.", call. = FALSE)
    for (j in seq_along(keywords)) {
      value <- values[[j]]
      if (!.scalar(value, "numeric") || !is.finite(value) || value < 0 || value > 100 || value != trunc(value)) {
        stop("Expected an integer Google index in [0, 100].", call. = FALSE)
      }
      if (!is.null(flags[[j]]) && !.scalar(flags[[j]], "logical")) stop("Data-quality flags must be booleans.", call. = FALSE)
      if (!is.null(formatted[[j]]) && !.scalar(formatted[[j]], "character")) stop("Google formattedValue must be a string.", call. = FALSE)
    }
    raw <- vapply(values, as.integer, integer(1))
    display <- vapply(formatted, function(x) if (is.null(x)) NA_character_ else x, character(1))
    output[[i]] <- data.frame(date = rep(date, length(keywords)), keyword = keywords, value = raw,
      formatted_value = display, has_data = vapply(flags, function(x) if (is.null(x)) NA else x, logical(1)),
      is_partial = if (is.null(partial)) NA else partial,
      low_volume = raw == 0L | (!is.na(display) & trimws(display) == "<1"), stringsAsFactors = FALSE)
  }
  if (any(diff(times) <= 0)) stop("Google timestamps must be unique and increasing.", call. = FALSE)
  if (!length(output)) return(.empty_table()[c("date", "keyword", "value", "formatted_value", "has_data", "is_partial", "low_volume")])
  do.call(rbind, output)
}

.http_get <- function(url, params, handle) {
  query <- paste(names(params), vapply(params, function(x) curl::curl_escape(as.character(x)), character(1)), sep = "=", collapse = "&")
  response <- curl::curl_fetch_memory(paste0(url, "?", query), handle = handle)
  list(status = response$status_code, text = rawToChar(response$content))
}

.new_client <- function(language, max_attempts, timeout, geo = "") {
  base <- "https://trends.google.com/trends"
  handle <- curl::new_handle(cookiefile = "", timeout = timeout,
    useragent = paste("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"))
  curl::handle_setheaders(handle, "Accept-Language" = language, Referer = paste0(base, "/explore"))
  warm <- function() tryCatch(.http_get(paste0(base, "/explore"), list(geo = geo), handle), error = function(e) NULL)
  warm()
  fetch <- function(url, params) {
    for (attempt in seq_len(max_attempts)) {
      response <- tryCatch(.http_get(url, params, handle), error = identity)
      status <- if (inherits(response, "error")) NA_integer_ else response$status
      reason <- if (inherits(response, "error")) conditionMessage(response) else paste("HTTP", status)
      if (!is.na(status) && status == 200L) return(response$text)
      if (!is.na(status) && status != 429L && status < 500L) stop("Google ", reason, call. = FALSE)
      if (attempt == max_attempts) break
      .pause(min(900, 30 * 2^(attempt - 1)), min(900, 30 * 2^(attempt - 1)) + 15)
      if (!is.na(status) && status == 429L) {
        curl::handle_setopt(handle, cookielist = "ALL")
        warm()
      }
    }
    stop("Google request failed after ", max_attempts, " attempts: ", reason, call. = FALSE)
  }
  timeline <- function(keywords, region, start, end, category, search_type) {
    geo <<- region
    types <- c(web = "", images = "images", news = "news", youtube = "youtube", shopping = "froogle")
    request <- list(comparisonItem = lapply(keywords, function(k) list(keyword = k, geo = region, time = paste(start, end))),
                    category = category, property = unname(types[[search_type]]))
    explore <- fetch(paste0(base, "/api/explore"), list(hl = language, tz = 0, req = .json(request)))
    definition <- .google_json(explore)
    returned <- vapply(definition$keywords, function(x) x$keyword, character(1))
    if (!identical(returned, keywords)) stop("Google returned different keywords or keyword order.", call. = FALSE)
    widgets <- Filter(function(w) identical(w$id, "TIMESERIES"), definition$widgets)
    if (!length(widgets)) stop("Google returned no TIMESERIES widget.", call. = FALSE)
    widget <- widgets[[1]]
    if (!.scalar(widget$token, "character") || !is.list(widget$request)) stop("Invalid Google widget.", call. = FALSE)
    .pause(2, 5)
    multiline <- fetch(paste0(base, "/api/widgetdata/multiline"),
                      list(hl = language, tz = 0, req = .json(widget$request), token = widget$token))
    list(explore = explore, multiline = multiline, resolution = widget$request$resolution)
  }
  list(timeline = timeline, close = function() curl::handle_reset(handle))
}
