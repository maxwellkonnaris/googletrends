"""G-TAB peak ratios and minimum-rounding-error paths (West, CIKM 2020).

https://doi.org/10.1145/3340531.3412075
The requested terms form a finite anchor bank; optional terms can bridge gaps.
No precomputed bank is reused across places, periods or search settings.
"""
import heapq
from itertools import combinations
import math


_CALIBRATED_COLUMNS = ["calibrated_value", "calibrated_lower", "calibrated_upper",
                       "calibration_factor", "calibration_reference"]


def _rounding_interval(value):
    return (100.0, 100.0) if value == 100 else (max(0.0, value - 0.5), value + 0.5)


def _usable(row):
    return row["has_data"] is not False and row["is_partial"] is not True and not row["low_volume"]


def _groups(terms):
    if len(terms) <= 5:
        return [terms]
    return [terms[i:i + 5] for i in range(len(terms) - 4)]


def _paths(graph, reference):
    # Add log interval widths, so Dijkstra minimizes multiplicative rounding error.
    paths = {reference: (0.0, 1.0, 1.0, 1.0, [reference], [])}
    queue = [(0.0, reference)]
    while queue:
        cost, term = heapq.heappop(queue)
        if cost != paths[term][0]:
            continue
        _, ratio, lower, upper, nodes, requests = paths[term]
        for neighbor, edge in graph[term].items():
            weight, estimate, lo, hi, request_id = edge
            distance = cost + weight
            if neighbor not in paths or distance < paths[neighbor][0]:
                paths[neighbor] = (distance, ratio * estimate, lower * lo, upper * hi,
                                   nodes + [neighbor], requests + [request_id])
                heapq.heappush(queue, (distance, neighbor))
    return paths


def _bank(comparisons, min_anchor_peak):
    graph, sources = {}, {}
    grid, resolution = None, None
    for comparison in comparisons:
        rows, terms = comparison["rows"], comparison["keywords"]
        dates = sorted({row["date"] for row in rows})
        if not dates:
            raise ValueError("G-TAB cannot calibrate an empty comparison")
        if grid is not None and (dates != grid or comparison["resolution"] != resolution):
            raise ValueError("G-TAB requires identical timestamps and resolution across comparisons; no alignment is applied")
        grid, resolution = dates, comparison["resolution"]
        peaks = {}
        for term in terms:
            graph.setdefault(term, {})
            series = [row for row in rows if row["keyword"] == term]
            peak = max((row["value"] for row in series if _usable(row)), default=0)
            peaks[term] = peak
            if peak > sources.get(term, (0, None))[0]:
                sources[term] = (peak, series)
        for first, second in combinations(terms, 2):
            if min(peaks[first], peaks[second]) < min_anchor_peak:
                continue
            for origin, target in ((first, second), (second, first)):
                a, b = peaks[target], peaks[origin]
                a_lo, a_hi = _rounding_interval(a)
                b_lo, b_hi = _rounding_interval(b)
                lo, hi = a_lo / b_hi, a_hi / b_lo
                weight = math.log(hi / lo)
                edge = (weight, a / b, lo, hi, comparison["request_id"])
                if target not in graph[origin] or weight < graph[origin][target][0]:
                    graph[origin][target] = edge
    return graph, sources


def _next_bridge(comparisons, keywords, reference, min_anchor_peak):
    graph, _ = _bank(comparisons, min_anchor_peak)
    paths = _paths(graph, reference)
    if all(term in paths for term in keywords):
        return None
    missing = set(graph) - paths.keys()
    terms = list(graph)
    tried = {frozenset(c["keywords"]) for c in comparisons if len(c["keywords"]) == 2}
    candidates = []
    for comparison in comparisons:
        peaks = {term: max((r["value"] for r in comparison["rows"]
                            if r["keyword"] == term and _usable(r)), default=0)
                 for term in comparison["keywords"]}
        for target in terms:
            if target not in missing or target not in peaks:
                continue
            for anchor in comparison["keywords"]:
                pair = frozenset((target, anchor))
                if anchor in paths and peaks[anchor] > 0 and pair not in tried:
                    # Approximate ratios only choose a new query; never calibrate an edge
                    # below the threshold. Removing dominant terms improves precision.
                    distance = abs(math.log(max(peaks[target], 0.5) / peaks[anchor]))
                    candidates.append((distance, terms.index(target), anchor, target))
    if not candidates:
        return None
    _, _, anchor, target = min(candidates)
    return [anchor, target]


def _calibrate(comparisons, keywords, reference, min_anchor_peak):
    graph, sources = _bank(comparisons, min_anchor_peak)
    paths = _paths(graph, reference)
    missing = [term for term in keywords if term not in paths or term not in sources]
    if missing:
        raise ValueError(f"G-TAB has no reliable anchor path to {missing!r} from {reference!r}; "
                         "add anchors of intermediate popularity, reorder the terms, or change the time/region. "
                         "Zero or insufficient-volume series cannot be recovered by calibration")
    output, details = [], {}
    for term in keywords:
        _, ratio, lower, upper, nodes, requests = paths[term]
        peak, rows = sources[term]
        peak_lo, peak_hi = _rounding_interval(peak)
        factor, factor_lo, factor_hi = ratio / peak, lower / peak_hi, upper / peak_lo
        if not all(math.isfinite(x) and x > 0 for x in (factor, factor_lo, factor_hi)):
            raise ValueError("G-TAB calibration overflow or underflow; use a shorter anchor chain")
        details[term] = dict(peak_ratio=ratio, peak_ratio_lower=lower, peak_ratio_upper=upper,
                             factor=factor, factor_lower=factor_lo, factor_upper=factor_hi,
                             path=nodes, path_request_ids=requests,
                             source_request_id=rows[0]["request_id"], source_peak=peak)
        for row in rows:
            lo, hi = _rounding_interval(row["value"])
            output.append(dict(row, calibrated_value=row["value"] * factor,
                               calibrated_lower=lo * factor_lo if _usable(row) else None,
                               calibrated_upper=hi * factor_hi if _usable(row) else None,
                               calibration_factor=factor, calibration_reference=reference))
    order = {term: i for i, term in enumerate(keywords)}
    output.sort(key=lambda row: (row["date"], order[row["keyword"]]))
    return output, dict(reference=reference, terms=details, min_anchor_peak=min_anchor_peak,
                        uncertainty="conditional integer-rounding bounds; not sampling confidence intervals")
