"""Overview and term panels on one common display scale."""
import math
import textwrap
from datetime import datetime, timezone

from ._transform import _interest_matrix


def _plot_data(data):
    matrix, field = _interest_matrix(data)
    peak = matrix.to_numpy().max()
    if peak <= 0:
        raise ValueError("Plotting on a 0–100 scale requires at least one positive value")
    display = (matrix / peak) * 100
    result = display.T.reset_index().melt(id_vars="date", var_name="keyword", value_name="display_value")
    result.attrs = {"value_column": field, "geo": data.geo.iloc[0]}
    return result


def plot_trends(data, *, ncol=3):
    """Return the README-style overview and term panels as a Matplotlib Figure.

    Supply the original long DataFrame from one ``pull_trends`` call, retaining its
    metadata, and select one geography first. Uses G-TAB ``calibrated_value`` when
    present, otherwise the shared raw ``value``. Every plotted value is divided by
    the maximum across all supplied terms/dates and multiplied by 100. Every panel
    has the same y-axis; this display index is not selected-term proportions.

    ``ncol`` is the positive integer number of term-panel columns (default 3).
    Keeps all supplied dates, zeros and flagged observations without smoothing or
    mutation; inspect quality flags before interpretation. Rejects incomplete or
    mixed-scale collections, invalid values, and an entirely zero collection.
    Does not fetch data or save a file. Install ``trendspull[plot]``
    for Matplotlib; use ``figure.savefig(...)`` to export.
    """
    if type(ncol) is not int or ncol < 1:
        raise ValueError("ncol must be a positive integer")
    values = _plot_data(data)
    try:
        from matplotlib import dates as mdates, pyplot as plt
        from matplotlib.ticker import FixedLocator
    except ImportError:
        raise ImportError("plot_trends requires Matplotlib; install trendspull[plot]") from None
    terms = list(values.keyword.drop_duplicates())
    columns = min(ncol, len(terms))
    rows = math.ceil(len(terms) / columns)
    colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#7B5B3A", "#E69F00"]
    lines = ["-", (0, (2, 2)), (0, (4, 2)), (0, (1, 3)), (0, (7, 3)), (0, (3, 3, 1, 3))]
    style = {"font.family": "sans-serif", "font.size": 12, "text.color": "#26333F",
             "axes.labelcolor": "#26333F", "xtick.color": "#596773", "ytick.color": "#596773",
             "axes.edgecolor": "white", "figure.facecolor": "white", "axes.facecolor": "white"}
    with plt.rc_context(style):
        fig = plt.figure(figsize=(11, 4 + 2.75 * rows), layout="constrained")
        grid = fig.add_gridspec(rows + 1, columns, height_ratios=[1.5] + [1] * rows)
        overview = fig.add_subplot(grid[0, :])
        for i, term in enumerate(terms):
            series = values.loc[values.keyword.eq(term)]
            dates = series.date.array.to_pydatetime()
            color = colors[i % len(colors)]
            line = lines[(i + i // len(colors)) % len(lines)]
            marker = "o" if len(series) == 1 else None
            overview.plot(dates, series.display_value, label=term, color=color, linestyle=line,
                          linewidth=1.25, marker=marker)
            ax = fig.add_subplot(grid[1 + i // columns, i % columns])
            ax.plot(dates, series.display_value, color=color, linewidth=1.2, marker=marker)
            ax.set_title(textwrap.fill(term, 28), loc="left", fontweight="bold", fontsize=13)
            ax.text(0.98, 0.95, f"Peak {series.display_value.max():.1f}", transform=ax.transAxes,
                    ha="right", va="top", color="#596773", fontsize=10)
        first, last = values.date.min(), values.date.max()
        for i, ax in enumerate(fig.axes):
            ax.set_ylim(0, 104)
            ax.yaxis.set_major_locator(FixedLocator([0, 25, 50, 75, 100] if i == 0 else [0, 50, 100]))
            ax.grid(axis="y", color="#E4E9ED", linewidth=0.6)
            ax.set_axisbelow(True)
            ax.tick_params(length=0, pad=7)
            for spine in ax.spines.values():
                spine.set_visible(False)
            if (last - first).days > 730:
                years = [datetime(y, 1, 1, tzinfo=timezone.utc) for y in range(first.year, last.year + 1)]
                years = [d for d in years if first <= d <= last]
                ticks = years[::max(1, math.ceil(len(years) / (6 if i == 0 else 3)))]
                ax.xaxis.set_major_locator(FixedLocator(mdates.date2num(ticks)))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            else:
                locator = mdates.AutoDateLocator(minticks=3, maxticks=6 if i == 0 else 3)
                ax.xaxis.set_major_locator(locator)
                ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        legend_columns = 3 if max(map(len, terms)) > 16 else 6
        handles, labels = overview.get_legend_handles_labels()
        labels = [textwrap.fill(label, 24) for label in labels]
        overview.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 1.02),
                        ncol=min(legend_columns, len(terms)),
                        frameon=False, fontsize=11, handlelength=2.5, columnspacing=1.3)
        fig.supylabel("Search interest index (0–100)", fontsize=12)
        fig.get_layout_engine().set(rect=(0, 0.11, 1, 0.89))
        fig.supxlabel("Date (UTC)", y=0.085, fontsize=12)
        fig.text(0.08, 0.02, "100 = highest interest across all supplied terms and dates.\n"
                 "All panels share one scale; values are not search counts.", fontsize=11, color="#596773")
    return fig
