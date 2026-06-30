from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

try:
    from scipy.stats import fisher_exact, mannwhitneyu
except Exception:  # pragma: no cover - optional dependency fallback
    fisher_exact = None
    mannwhitneyu = None


def safe_quantile(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.quantile(values, q))


def median_abs_deviation(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)))


def median_pairwise_abs_delta(values: np.ndarray) -> float:
    if values.size < 2:
        return float("nan")
    sorted_values = np.sort(values.astype(float))
    diffs = np.abs(sorted_values[:, None] - sorted_values[None, :])
    tri = diffs[np.triu_indices(len(sorted_values), k=1)]
    return float(np.median(tri)) if tri.size else float("nan")


def fisher_greater(group_positive: int, group_negative: int, bg_positive: int, bg_negative: int) -> tuple[float, float]:
    table = [[int(group_positive), int(group_negative)], [int(bg_positive), int(bg_negative)]]
    if fisher_exact is None:
        odds = ((group_positive + 0.5) * (bg_negative + 0.5)) / ((group_negative + 0.5) * (bg_positive + 0.5))
        return float(odds), float("nan")
    result = fisher_exact(table, alternative="greater")
    statistic = result.statistic if hasattr(result, "statistic") else result[0]
    pvalue = result.pvalue if hasattr(result, "pvalue") else result[1]
    return float(statistic), float(pvalue)


def mannwhitney_greater(group_values: np.ndarray, bg_values: np.ndarray) -> tuple[float, float, float]:
    if group_values.size == 0 or bg_values.size == 0:
        return float("nan"), float("nan"), float("nan")
    if mannwhitneyu is None:
        return float("nan"), float("nan"), float("nan")
    result = mannwhitneyu(group_values, bg_values, alternative="greater")
    statistic = float(result.statistic if hasattr(result, "statistic") else result[0])
    pvalue = float(result.pvalue if hasattr(result, "pvalue") else result[1])
    rank_biserial = 2.0 * statistic / float(group_values.size * bg_values.size) - 1.0
    return statistic, pvalue, float(rank_biserial)


def fdr_bh(pvalues: list[float | None]) -> list[float]:
    series = pd.Series(pvalues, dtype="float64")
    valid = series.dropna()
    if valid.empty:
        return [float("nan")] * len(series)
    ordered = valid.sort_values()
    m = float(len(ordered))
    raw_q = ordered.to_numpy(dtype=float) * m / np.arange(1, len(ordered) + 1, dtype=float)
    monotonic_q = np.minimum.accumulate(raw_q[::-1])[::-1]
    monotonic_q = np.clip(monotonic_q, 0.0, 1.0)
    q = pd.Series(monotonic_q, index=ordered.index)
    out = pd.Series(np.nan, index=series.index, dtype="float64")
    out.loc[q.index] = q
    return [float(value) if not math.isnan(float(value)) else float("nan") for value in out]


def rank_values(values: pd.Series, higher_is_better: bool) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.rank(method="min", ascending=not higher_is_better, na_option="bottom").astype(int)


def mean_rank(df: pd.DataFrame, columns: list[str], output_column: str) -> pd.DataFrame:
    existing = [column for column in columns if column in df.columns]
    if not existing:
        df[output_column] = np.nan
    else:
        df[output_column] = df[existing].mean(axis=1)
    return df


def is_nan(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))
