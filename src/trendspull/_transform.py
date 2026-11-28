"""Optional transformations of a single collected table."""
import math

import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_datetime64_any_dtype, is_numeric_dtype


def selected_proportions(data: pd.DataFrame) -> pd.DataFrame:
    """Return selected-term proportions, with terms as rows and UTC dates as columns.

    Pass the original DataFrame from one ``pull_trends`` call, retaining its attrs,
    and select one geography first if needed. Uses ``calibrated_value`` for G-TAB
    output and ``value`` for a single raw comparison. Each date's column sums to 1.
    These are proportions among the supplied terms, not shares of all Google searches.

    Keeps zeros and flagged observations; inspect the input quality flags separately.
    Does not mutate input, fetch data, fill missing cells, or add pseudocounts.
    Raises ValueError for missing provenance, mixed scales, incomplete grids,
    nonfinite/negative values, or dates without a positive total.
    """
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be the DataFrame returned by pull_trends")
    if data.empty or not data.columns.is_unique:
        raise ValueError("data must be nonempty with unique column names")
    meta = data.attrs.get("trendspull")
    if not isinstance(meta, dict) or meta.get("status") != "complete":
        raise ValueError("Keep the original pull_trends metadata; CSV exports omit it")
    calibration = meta.get("calibration")
    method = calibration.get("method") if isinstance(calibration, dict) else None
    if method not in ("none", "gtab"):
        raise ValueError("data must describe one raw or G-TAB collection")
    field = "calibrated_value" if method == "gtab" else "value"
    required = ["keyword", "date", "geo", "request_id", field]
    if not set(required).issubset(data.columns) or data[required].isna().any().any():
        raise ValueError(f"data requires nonmissing {', '.join(required)}")
    if data.geo.nunique() != 1:
        raise ValueError("Select one geography before calling selected_proportions")
    if not is_datetime64_any_dtype(data.date.dtype) or str(data.date.dt.tz) != "UTC":
        raise ValueError("date must contain the original UTC timestamps")
    requests = meta.get("requests", [])
    if not isinstance(requests, list) or any(not isinstance(r, dict) or not isinstance(r.get("request_id"), str)
                                             for r in requests):
        raise ValueError("Collection request metadata is incomplete")
    allowed = {r["request_id"] for r in requests if r.get("geo") == data.geo.iloc[0]}
    if not set(data.request_id).issubset(allowed) or (method == "none" and data.request_id.nunique() != 1):
        raise ValueError("Use one pull_trends call; separate raw comparisons have different scales")
    if data.duplicated(["keyword", "date"]).any():
        raise ValueError("Each term must occur once per date")
    values = data[field]
    if (not is_numeric_dtype(values.dtype) or is_bool_dtype(values.dtype)
            or is_complex_dtype(values.dtype)):
        raise ValueError(f"{field} must contain numeric values")
    if not values.map(lambda x: math.isfinite(x) and x >= 0).all():
        raise ValueError(f"{field} must contain finite nonnegative values")
    matrix = data.pivot(index="keyword", columns="date", values=field)
    matrix = matrix.reindex(data.keyword.drop_duplicates()).sort_index(axis=1).astype(float)
    if matrix.isna().any().any():
        raise ValueError("Every selected term must have the same dates; missing cells are not filled")
    peaks = matrix.max(axis=0)
    if peaks.le(0).any():
        raise ValueError("Each date must have a positive total across the selected terms")
    # A common per-column factor cancels and avoids overflow in the column sum.
    scaled = matrix.div(peaks, axis=1)
    result = scaled.div(scaled.sum(axis=0), axis=1)
    result.index = pd.Index(list(matrix.index), dtype=object, name="keyword")
    result.attrs = {"selected_proportions": dict(geo=data.geo.iloc[0], value_column=field,
                    keywords=list(matrix.index), request_ids=sorted(set(data.request_id)),
                    denominator="sum across the supplied terms at each date")}
    return result
