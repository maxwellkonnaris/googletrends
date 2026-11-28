#' Plot Google Trends interest on one common display scale
#'
#' Draws an overview above one panel per term, matching the README layout. Uses
#' calibrated values for G-TAB, otherwise the shared raw scale. Divides every
#' value by the maximum over all supplied terms and dates and multiplies by 100.
#' All panels share the same y-axis. Keeps supplied dates, zeros and flagged
#' observations without smoothing. Inspect quality flags before interpretation.
#' @param data Original data.frame from [pull_trends()], retaining its metadata;
#'   select one geography first. Missing cells and entirely zero data raise errors.
#' @param ncol Positive integer number of term-panel columns.
#' @return A patchwork/ggplot object. Print to display, or save with
#'   `ggplot2::ggsave()`. Does not fetch data, modify input or write files.
#' @importFrom rlang .data
#' @export
plot_trends <- function(data, ncol = 3) {
  ncol <- .integer_option(ncol, "ncol")
  if (ncol < 1L) stop("ncol must be positive.", call. = FALSE)
  .backend()
  plotting <- reticulate::import("trendspull._plot", convert = FALSE)
  values <- reticulate::py_to_r(plotting$`_plot_data`(.python_data(data)))
  terms <- unique(values$keyword)
  values$keyword <- factor(values$keyword, levels = terms)
  ncol <- min(ncol, length(terms))
  colors <- stats::setNames(rep(c("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#7B5B3A", "#E69F00"),
                               length.out = length(terms)), terms)
  i <- seq_along(terms) - 1L
  lines <- stats::setNames(c("solid", "22", "42", "13", "73", "3313")[(i + i %/% 6) %% 6 + 1L], terms)
  legend_rows <- ceiling(length(terms) / if (max(nchar(terms)) > 16) 3 else 6)
  legend_labels <- function(x) vapply(x, function(s) paste(strwrap(s, width = 24), collapse = "\n"), character(1))
  style <- ggplot2::theme_minimal(base_size = 14, base_family = "sans") +
    ggplot2::theme(text = ggplot2::element_text(colour = "#26333F"),
      axis.text = ggplot2::element_text(colour = "#596773", size = 12),
      axis.title.y = ggplot2::element_text(margin = ggplot2::margin(r = 12)),
      axis.title.x = ggplot2::element_text(margin = ggplot2::margin(t = 10)),
      panel.grid.minor = ggplot2::element_blank(), panel.grid.major.x = ggplot2::element_blank(),
      panel.grid.major.y = ggplot2::element_line(colour = "#E4E9ED", linewidth = 0.35),
      panel.spacing = grid::unit(1.1, "lines"),
      strip.text = ggplot2::element_text(face = "bold", hjust = 0, size = 14),
      legend.position = "top", legend.justification = "center", legend.direction = "horizontal",
      legend.title = ggplot2::element_blank(), legend.text = ggplot2::element_text(size = 13),
      legend.key.width = grid::unit(0.9, "cm"), legend.spacing.x = grid::unit(0.4, "cm"),
      plot.caption = ggplot2::element_text(colour = "#596773", size = 12, hjust = 0,
                                         margin = ggplot2::margin(t = 10)),
      plot.margin = ggplot2::margin(12, 16, 12, 12),
      plot.background = ggplot2::element_rect(fill = "white", colour = NA))
  first <- min(values$date)
  last <- max(values$date)
  common_geom <- if (first == last) ggplot2::geom_point(size = 1.8) else
    ggplot2::geom_line(linewidth = 0.67, lineend = "round")
  detail_geom <- if (first == last) ggplot2::geom_point(size = 1.8) else
    ggplot2::geom_line(linewidth = 0.65, lineend = "round")
  span <- as.numeric(difftime(last, first, units = "days"))
  if (span > 730) {
    years <- seq(as.POSIXct(paste0(format(first, "%Y", tz = "UTC"), "-01-01"), tz = "UTC"), last, by = "year")
    years <- years[years >= first]
    breaks <- years[seq.int(1L, length(years), by = max(1L, ceiling(length(years) / 6)))]
    small_breaks <- breaks[seq.int(1L, length(breaks), by = max(1L, ceiling(length(breaks) / 3)))]
    labels <- "%Y"
  } else {
    breaks <- small_breaks <- unique(seq(first, last, length.out = min(4L, length(unique(values$date)))))
    labels <- if (span < 2) "%b %d\n%H:%M" else "%b %d\n%Y"
  }
  common <- ggplot2::ggplot(values, ggplot2::aes(x = .data$date, y = .data$display_value,
                                               colour = .data$keyword, linetype = .data$keyword)) +
    common_geom +
    ggplot2::scale_colour_manual(values = colors, breaks = terms, labels = legend_labels) +
    ggplot2::scale_linetype_manual(values = lines, breaks = terms, labels = legend_labels) +
    ggplot2::scale_x_datetime(breaks = breaks, date_labels = labels, timezone = "UTC",
                        expand = ggplot2::expansion(mult = c(0.015, 0.025))) +
    ggplot2::scale_y_continuous(breaks = seq(0, 100, 25), limits = c(0, 100),
                              expand = ggplot2::expansion(mult = c(0, 0.04))) +
    ggplot2::labs(x = NULL, y = "Search interest index (0\u2013100)") +
    ggplot2::guides(colour = ggplot2::guide_legend(nrow = legend_rows, byrow = TRUE),
                    linetype = ggplot2::guide_legend(nrow = legend_rows, byrow = TRUE)) + style
  peaks <- stats::aggregate(display_value ~ keyword, values, max)
  peaks$label <- sprintf("Peak %.1f", peaks$display_value)
  detail <- ggplot2::ggplot(values, ggplot2::aes(x = .data$date, y = .data$display_value, colour = .data$keyword)) +
    detail_geom +
    ggplot2::geom_text(data = peaks, ggplot2::aes(x = last, y = 96, label = .data$label),
                      inherit.aes = FALSE, hjust = 1, vjust = 1, colour = "#596773", size = 3.6) +
    ggplot2::facet_wrap(~keyword, ncol = ncol, drop = FALSE,
                        labeller = ggplot2::label_wrap_gen(width = 28)) +
    ggplot2::scale_colour_manual(values = colors) +
    ggplot2::scale_x_datetime(breaks = small_breaks, date_labels = labels, timezone = "UTC",
                        expand = ggplot2::expansion(mult = c(0.015, 0.025))) +
    ggplot2::scale_y_continuous(breaks = c(0, 50, 100), limits = c(0, 100),
                              expand = ggplot2::expansion(mult = c(0, 0.04))) +
    ggplot2::labs(x = "Date (UTC)", y = "Search interest index (0\u2013100)",
      caption = paste("100 = highest interest across all supplied terms and dates.",
                      "All panels share one scale; values are not search counts.", sep = "\n")) +
    style + ggplot2::theme(legend.position = "none", panel.spacing.y = grid::unit(1.5, "lines"))
  patchwork::wrap_plots(common, detail, ncol = 1, heights = c(1, 0.675 * ceiling(length(terms) / ncol)))
}
