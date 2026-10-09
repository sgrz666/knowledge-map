"""Dual-track psychometric score conversion algorithms for CET and NTCE."""
from __future__ import annotations

import math
from typing import List, Tuple


def standard_normal_cdf(x: float) -> float:
    """Approximate cumulative distribution function of standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def probit(p: float) -> float:
    """Inverse CDF (quantile function) of standard normal distribution using rational approximation."""
    p = max(0.001, min(0.999, p))
    # Approximation of probit
    if p < 0.5:
        # Lower region
        t = math.sqrt(-2.0 * math.log(p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return -(t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0))
    else:
        # Upper region
        t = math.sqrt(-2.0 * math.log(1.0 - p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)


class ScoreConverter:
    """Mathematical conversions for exam scale scores."""

    @staticmethod
    def cet_norm_conversion(
        raw_score: float,
        max_raw_score: float = 100.0,
    ) -> Tuple[float, List[float], float]:
        """Convert raw score to CET standard norm score (scale: 220-710, pass: 425).

        Returns:
            (point_estimate, [ci_lower, ci_upper], pass_probability)
        """
        rate = max(0.01, min(0.99, raw_score / max_raw_score))
        # Equivalent Z-score from standard normal quantile
        z = probit(rate)
        # Scale: Mean = 500, SD = 70
        point_est = 500.0 + 70.0 * z
        point_est = max(220.0, min(710.0, round(point_est, 1)))

        ci_lower = max(220.0, round(500.0 + 70.0 * (z - 0.25), 1))
        ci_upper = min(710.0, round(500.0 + 70.0 * (z + 0.25), 1))

        # Pass probability relative to 425 threshold
        z_pass = (point_est - 425.0) / (70.0 * 0.25)
        pass_prob = round(standard_normal_cdf(z_pass), 3)

        return point_est, [ci_lower, ci_upper], pass_prob

    @staticmethod
    def ntce_piecewise_conversion(
        raw_score: float,
        pass_cutoff_raw: float = 90.0,
        max_raw_score: float = 150.0,
    ) -> Tuple[float, List[float], float]:
        """Convert NTCE raw score (max 150) to reporting score (max 120, pass 70).

        Formula:
          Y(X) = (70 / Xp) * X, when 0 <= X < Xp
          Y(X) = 70 + (50 / (150 - Xp)) * (X - Xp), when Xp <= X <= 150

        Returns:
            (reporting_score, [ci_lower, ci_upper], pass_probability)
        """
        x = max(0.0, min(max_raw_score, raw_score))
        xp = pass_cutoff_raw

        def _calc_y(val: float) -> float:
            if val < xp:
                return (70.0 / xp) * val
            else:
                return 70.0 + (50.0 / (max_raw_score - xp)) * (val - xp)

        rep_score = round(_calc_y(x), 1)

        # Confidence interval assuming standard measurement error of ~3.5 raw points
        ci_lower = round(max(0.0, _calc_y(max(0.0, x - 3.5))), 1)
        ci_upper = round(min(120.0, _calc_y(min(max_raw_score, x + 3.5))), 1)

        # Pass probability relative to 70 threshold
        z_pass = (rep_score - 70.0) / 3.0
        pass_prob = round(standard_normal_cdf(z_pass), 3)

        return rep_score, [ci_lower, ci_upper], pass_prob
