# scoring.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------
# Configuration
# -----------------------------
@dataclass(frozen=True)
class ScoreConfig:
    # Robust z-score settings
    clip_z: Optional[float] = 4.0   # set None to disable clipping
    eps: float = 1e-9              # prevents divide-by-zero when MAD == 0

    # Weight handling
    normalize_weights: bool = True  # normalize weights to sum to 1
    equal_if_all_zero: bool = True  # if all weights are 0, fallback to equal weights

    # Quality normalization scope
    # - "job": quality z computed within each job's candidate suppliers (default)
    # - "global": quality z computed across all rows (job-independent)
    quality_scope: str = "job"


# -----------------------------
# Core stats helpers
# -----------------------------
def _robust_center_scale(x: np.ndarray, eps: float) -> Tuple[float, float]:
    """
    Robust location/scale using median and MAD.
    scale = 1.4826 * MAD + eps  (1.4826 makes MAD comparable to std for normal data)
    """
    x = np.asarray(x, dtype=float)
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    scale = 1.4826 * mad + eps
    return med, scale


def robust_z(x: np.ndarray, *, eps: float = 1e-9, clip: Optional[float] = None) -> np.ndarray:
    """
    Robust z-score: z = (x - median) / (1.4826*MAD + eps)
    """
    med, scale = _robust_center_scale(np.asarray(x), eps=eps)
    z = (np.asarray(x, dtype=float) - med) / scale
    if clip is not None:
        z = np.clip(z, -clip, clip)
    return z


def normalize_weights(
    w_cost: float,
    w_quality: float,
    w_distance: float,
    *,
    normalize: bool = True,
    equal_if_all_zero: bool = True,
) -> Tuple[float, float, float]:
    wc = float(w_cost)
    wq = float(w_quality)
    wd = float(w_distance)

    if not normalize:
        return wc, wq, wd

    s = wc + wq + wd
    if s <= 0:
        if equal_if_all_zero:
            return (1 / 3, 1 / 3, 1 / 3)
        return (0.0, 0.0, 0.0)

    return (wc / s, wq / s, wd / s)


# -----------------------------
# Scoring main entry point
# -----------------------------
def add_weighted_scores(
    df: pd.DataFrame,
    *,
    # required columns (defaults match your naming)
    job_col: str = "job_id",
    supplier_col: str = "supplier_id",
    cost_col: str = "cost",
    distance_col: str = "drive_distance",
    quality_col: str = "quality_score",
    # weights (from widget)
    w_cost: float,
    w_quality: float,
    w_distance: float,
    # config
    config: ScoreConfig = ScoreConfig(),
) -> pd.DataFrame:
    """
    Given a row-per-(job, supplier) DataFrame with cost/distance/quality,
    compute robust per-job z-scores and a weighted total score.

    Adds columns:
      z_cost, z_distance, z_quality
      f_cost, f_distance, f_quality  (direction-corrected so higher = better)
      weighted_z_score
      w_cost_used, w_quality_used, w_distance_used
      outlier_cost, outlier_distance, outlier_quality (|raw z| >= 3 using unclipped z)

    Notes:
      - cost & distance: lower is better -> we negate their z when forming f_*
      - quality: higher is better -> keep z as-is
      - by default, z-scores are computed within each job's candidate set
      - you can set config.quality_scope="global" to normalize quality across all rows
    """
    if df.empty:
        out = df.copy()
        out["weighted_z_score"] = pd.Series(dtype=float)
        return out

    out = df.copy()

    # Validate config
    if config.quality_scope not in ("job", "global"):
        raise ValueError("ScoreConfig.quality_scope must be 'job' or 'global'")

    wc, wq, wd = normalize_weights(
        w_cost, w_quality, w_distance,
        normalize=config.normalize_weights,
        equal_if_all_zero=config.equal_if_all_zero,
    )

    # Helpers for group transforms
    def _z_group_clipped(s: pd.Series) -> pd.Series:
        z = robust_z(s.to_numpy(), eps=config.eps, clip=config.clip_z)
        return pd.Series(z, index=s.index)

    def _z_group_raw(s: pd.Series) -> pd.Series:
        z = robust_z(s.to_numpy(), eps=config.eps, clip=None)
        return pd.Series(z, index=s.index)

    # Cost & distance: per-job
    out["z_cost_raw"] = out.groupby(job_col)[cost_col].transform(_z_group_raw)
    out["z_distance_raw"] = out.groupby(job_col)[distance_col].transform(_z_group_raw)

    out["z_cost"] = out.groupby(job_col)[cost_col].transform(_z_group_clipped)
    out["z_distance"] = out.groupby(job_col)[distance_col].transform(_z_group_clipped)

    # Quality: per-job or global
    if config.quality_scope == "job":
        out["z_quality_raw"] = out.groupby(job_col)[quality_col].transform(_z_group_raw)
        out["z_quality"] = out.groupby(job_col)[quality_col].transform(_z_group_clipped)
    else:
        # global (same scaling across all rows)
        zq_raw = robust_z(out[quality_col].to_numpy(), eps=config.eps, clip=None)
        zq = robust_z(out[quality_col].to_numpy(), eps=config.eps, clip=config.clip_z)
        out["z_quality_raw"] = zq_raw
        out["z_quality"] = zq

    # Outlier flags (use raw, unclipped z; threshold is conventional)
    out["outlier_cost"] = out["z_cost_raw"].abs() >= 3.0
    out["outlier_distance"] = out["z_distance_raw"].abs() >= 3.0
    out["outlier_quality"] = out["z_quality_raw"].abs() >= 3.0

    # Direction correction so "higher is better"
    out["f_cost"] = -out["z_cost"]
    out["f_distance"] = -out["z_distance"]
    out["f_quality"] = out["z_quality"]

    # Weighted sum
    out["weighted_z_score"] = (wc * out["f_cost"]) + (wd * out["f_distance"]) + (wq * out["f_quality"])

    # Track weights used (for debugging / explainability)
    out["w_cost_used"] = wc
    out["w_quality_used"] = wq
    out["w_distance_used"] = wd

    # Optional: drop raw z columns if you want the table cleaner
    # (leave them in by default because they’re useful for debug and transparency)

    return out


def to_minimization_cost(
    weighted_score: pd.Series,
    *,
    scale: float = 1000.0,
    shift_to_nonnegative: bool = True,
) -> pd.Series:
    """
    Converts a "higher is better" score into a "lower is better" integer-ish cost
    for solvers that require minimization with non-negative coefficients.

    cost = (-score) * scale
    If shift_to_nonnegative=True, shifts by subtracting min(cost) so smallest becomes 0.

    Returns float series (you can cast to int after rounding if needed).
    """
    cost = (-weighted_score.astype(float)) * float(scale)
    if shift_to_nonnegative:
        cost = cost - float(cost.min())
    return cost
