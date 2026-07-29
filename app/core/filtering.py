"""Log filtering. Pure pandas - no pm4py - so it stays fast and predictable.

Filters run *before* discovery. Cutting the log down is by far the cheapest way
to make a process map readable, which is why every discovery endpoint accepts
the same ``LogFilters`` object.
"""

from __future__ import annotations

import pandas as pd

from app.core import model
from app.schemas.mining import LogFilters


def _keep_cases(frame: pd.DataFrame, cases: set[str]) -> pd.DataFrame:
    return frame[frame[model.CASE].isin(cases)]


def apply_filters(frame: pd.DataFrame, filters: LogFilters | None) -> pd.DataFrame:
    if frame.empty or filters is None:
        return frame

    out = frame

    if filters.date_from is not None:
        out = out[out[model.TIMESTAMP] >= pd.Timestamp(filters.date_from).tz_localize(None)]
    if filters.date_to is not None:
        out = out[out[model.TIMESTAMP] <= pd.Timestamp(filters.date_to).tz_localize(None)]
    if filters.cases:
        out = _keep_cases(out, set(filters.cases))
    if filters.activities_include:
        out = out[out[model.ACTIVITY].isin(set(filters.activities_include))]
    if filters.activities_exclude:
        out = out[~out[model.ACTIVITY].isin(set(filters.activities_exclude))]
    if filters.resources:
        out = out[out[model.RESOURCE].isin(set(filters.resources))]

    if filters.activity_coverage and not out.empty:
        counts = out[model.ACTIVITY].value_counts()
        cumulative = counts.cumsum() / counts.sum()
        keep = set(cumulative[cumulative <= filters.activity_coverage].index) or {counts.index[0]}
        out = out[out[model.ACTIVITY].isin(keep)]

    if out.empty:
        return out

    grouped = out.groupby(model.CASE, sort=False)[model.ACTIVITY]

    if filters.start_activities:
        wanted = set(filters.start_activities)
        keep = {case for case, seq in grouped if len(seq) and seq.iloc[0] in wanted}
        out = _keep_cases(out, keep)
    if filters.end_activities and not out.empty:
        wanted = set(filters.end_activities)
        keep = {
            case
            for case, seq in out.groupby(model.CASE, sort=False)[model.ACTIVITY]
            if len(seq) and seq.iloc[-1] in wanted
        }
        out = _keep_cases(out, keep)

    if (filters.min_case_length or filters.max_case_length) and not out.empty:
        sizes = out.groupby(model.CASE, sort=False).size()
        if filters.min_case_length:
            sizes = sizes[sizes >= filters.min_case_length]
        if filters.max_case_length:
            sizes = sizes[sizes <= filters.max_case_length]
        out = _keep_cases(out, set(sizes.index))

    if filters.variant_coverage and not out.empty:
        variants = (
            out.groupby(model.CASE, sort=False)[model.ACTIVITY]
            .apply(lambda s: tuple(s))
            .to_frame("variant")
        )
        counts = variants["variant"].value_counts()
        cumulative = counts.cumsum() / counts.sum()
        keep_variants = set(cumulative[cumulative <= filters.variant_coverage].index)
        if not keep_variants:
            keep_variants = {counts.index[0]}
        keep_cases = set(variants[variants["variant"].isin(keep_variants)].index)
        out = _keep_cases(out, keep_cases)

    return out.reset_index(drop=True)
