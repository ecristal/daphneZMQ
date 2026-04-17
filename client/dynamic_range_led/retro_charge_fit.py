#!/usr/bin/env python3
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


def gauss(x: np.ndarray, amplitude: float, mean: float, sigma: float) -> np.ndarray:
    sigma = max(float(sigma), 1e-9)
    return amplitude * np.exp(-0.5 * ((x - mean) / sigma) ** 2)


def triple_gauss(
    x: np.ndarray,
    a0: float,
    mu0: float,
    s0: float,
    a1: float,
    mu1: float,
    s1: float,
    a2: float,
    mu2: float,
    s2: float,
) -> np.ndarray:
    return (
        gauss(x, a0, mu0, s0)
        + gauss(x, a1, mu1, s1)
        + gauss(x, a2, mu2, s2)
    )


def area_gauss(x: np.ndarray, n_events: float, mean: float, sigma: float, bin_width: float) -> np.ndarray:
    sigma = max(float(sigma), 1e-9)
    norm = float(n_events) * float(bin_width) / (math.sqrt(2.0 * math.pi) * sigma)
    return norm * np.exp(-0.5 * ((x - mean) / sigma) ** 2)


def constrained_triple_gauss(
    x: np.ndarray,
    a0: float,
    mu0: float,
    s0: float,
    a1: float,
    mu1: float,
    s1: float,
    a2: float,
) -> np.ndarray:
    gain = mu1 - mu0
    mu2 = mu0 + 2.0 * gain
    s1_eff = max(float(s1), 1e-9)
    s0_eff = max(float(s0), 1e-9)
    excess_var = max(s1_eff * s1_eff - s0_eff * s0_eff, 0.0)
    s2 = math.sqrt(max(s0_eff * s0_eff + 2.0 * excess_var, 1e-9))
    return (
        gauss(x, a0, mu0, s0_eff)
        + gauss(x, a1, mu1, s1_eff)
        + gauss(x, a2, mu2, s2)
    )


def triple_area_gauss(
    x: np.ndarray,
    n0: float,
    mu0: float,
    s0: float,
    n1: float,
    gain: float,
    s_pe: float,
    n2: float,
    bin_width: float,
) -> np.ndarray:
    mu1 = mu0 + gain
    mu2 = mu0 + 2.0 * gain
    s1 = math.sqrt(max(s0 * s0 + s_pe * s_pe, 1e-9))
    s2 = math.sqrt(max(s0 * s0 + 2.0 * s_pe * s_pe, 1e-9))
    return (
        area_gauss(x, n0, mu0, s0, bin_width)
        + area_gauss(x, n1, mu1, s1, bin_width)
        + area_gauss(x, n2, mu2, s2, bin_width)
    )


def _nearest_count(x: np.ndarray, y: np.ndarray, target: float) -> float:
    idx = int(np.argmin(np.abs(x - target)))
    return float(max(y[idx], 1.0))


def _estimate_peak_width(
    x: np.ndarray,
    y: np.ndarray,
    lo: float,
    hi: float,
    *,
    fallback_sigma: float,
) -> tuple[float, float, float]:
    mask = (x >= lo) & (x <= hi)
    if not np.any(mask):
        center = 0.5 * (lo + hi)
        return center, max(float(fallback_sigma), 1.0), 1.0

    xs = x[mask]
    ys = y[mask]
    if len(xs) == 0 or not np.any(ys > 0):
        center = 0.5 * (lo + hi)
        return center, max(float(fallback_sigma), 1.0), 1.0

    peak_idx = int(np.argmax(ys))
    peak_x = float(xs[peak_idx])
    peak_y = float(max(ys[peak_idx], 1.0))
    half = 0.5 * peak_y

    left = peak_idx
    while left > 0 and ys[left] > half:
        left -= 1
    right = peak_idx
    while right < len(ys) - 1 and ys[right] > half:
        right += 1

    if right <= left:
        sigma = max(float(fallback_sigma), 1.0)
    else:
        fwhm = float(xs[right] - xs[left])
        sigma = max(fwhm / 2.355, 1.0)
    return peak_x, sigma, peak_y


def _fit_window(
    x: np.ndarray,
    y: np.ndarray,
    mu1_guess: float,
    sigma0_guess: float,
) -> np.ndarray:
    sigma0 = max(float(sigma0_guess), np.median(np.diff(x)) if len(x) > 1 else 1.0, 1.0)
    lo = min(float(np.min(x[y > 0])) if np.any(y > 0) else float(np.min(x)), -4.0 * sigma0)
    hi = max(2.35 * mu1_guess + 3.5 * sigma0, 6.0 * sigma0)
    return (x >= lo) & (x <= hi)


def fit_retro_triple_gauss(
    frame: pd.DataFrame,
    *,
    mu1_guess: float,
    sigma0_guess: float,
    sigma1_guess: float | None = None,
) -> dict[str, Any]:
    x = frame["x"].to_numpy(dtype=float)
    y = frame["count"].to_numpy(dtype=float)
    if len(x) < 10 or not np.any(y > 0):
      return {"status": "empty_histogram"}

    bin_width = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
    sigma0 = max(float(sigma0_guess), 1.5 * bin_width, 1.0)
    mu1 = max(float(mu1_guess), 2.5 * sigma0)
    sigma1 = max(float(sigma1_guess) if sigma1_guess and np.isfinite(sigma1_guess) else sigma0 * 1.2, 1.5 * bin_width)

    fit_mask = _fit_window(x, y, mu1, sigma0)
    xf = x[fit_mask]
    yf = y[fit_mask]
    if len(xf) < 10 or not np.any(yf > 0):
        return {"status": "empty_fit_window"}

    mu0_seed, sigma0_seed, pedestal_height = _estimate_peak_width(
        xf,
        yf,
        -1.5 * sigma0,
        1.5 * sigma0,
        fallback_sigma=sigma0,
    )
    mu1_seed, sigma1_seed, one_height = _estimate_peak_width(
        xf,
        yf,
        max(0.55 * mu1, 2.0 * bin_width),
        1.45 * mu1,
        fallback_sigma=sigma1,
    )
    gain_seed = max(mu1_seed - mu0_seed, 2.5 * sigma0)
    mu2_seed, sigma2_seed, two_height = _estimate_peak_width(
        xf,
        yf,
        1.55 * gain_seed,
        2.55 * gain_seed,
        fallback_sigma=max(math.sqrt(max(2.0 * sigma1_seed * sigma1_seed - sigma0_seed * sigma0_seed, 1.0)), sigma1_seed),
    )
    p0 = [
        pedestal_height,
        mu0_seed,
        sigma0_seed,
        one_height,
        mu1_seed,
        sigma1_seed,
        two_height,
    ]

    mu0_lo = max(-max(3.0 * sigma0_seed, 0.35 * gain_seed), mu0_seed - 1.5 * sigma0_seed)
    mu0_hi = min(max(3.0 * sigma0_seed, 0.35 * gain_seed), mu0_seed + 1.5 * sigma0_seed)
    bounds = (
        [
            0.0,
            mu0_lo,
            max(0.5 * bin_width, 0.5 * sigma0_seed),
            0.0,
            max(0.75 * mu1_seed, 2.0 * bin_width),
            max(0.5 * bin_width, 0.55 * sigma1_seed),
            0.0,
        ],
        [
            float(np.max(yf)) * 4.5 + 10.0,
            mu0_hi,
            max(1.45 * sigma0_seed, 0.3 * mu1_seed),
            float(np.max(yf)) * 4.5 + 10.0,
            1.18 * mu1_seed,
            min(max(1.35 * sigma1_seed, 1.25 * sigma0_seed), 0.24 * mu1_seed),
            float(np.max(yf)) * 4.5 + 10.0,
        ],
    )
    lower = np.asarray(bounds[0], dtype=float)
    upper = np.asarray(bounds[1], dtype=float)
    p0 = np.clip(np.asarray(p0, dtype=float), lower + 1e-6, upper - 1e-6).tolist()

    sigma_y = np.sqrt(np.clip(yf, 9.0, None))
    try:
        popt, _ = curve_fit(
            constrained_triple_gauss,
            xf,
            yf,
            p0=p0,
            bounds=bounds,
            sigma=sigma_y,
            absolute_sigma=False,
            maxfev=40000,
        )
    except Exception as exc:
        return {"status": "fit_failed", "error": str(exc)}

    a0, mu0, s0, a1, mu1, s1, a2 = [float(v) for v in popt]
    gain = mu1 - mu0
    mu2 = mu0 + 2.0 * gain
    excess_var = max(s1 * s1 - s0 * s0, 0.0)
    s2 = math.sqrt(max(s0 * s0 + 2.0 * excess_var, 1e-9))
    xfit = np.linspace(float(np.min(xf)), float(np.max(xf)), 1800)
    yfit = constrained_triple_gauss(xfit, a0, mu0, s0, a1, mu1, s1, a2)
    c0 = gauss(xfit, a0, mu0, s0)
    c1 = gauss(xfit, a1, mu1, s1)
    c2 = gauss(xfit, a2, mu2, s2)
    snr_ped = (mu1 - mu0) / max(s0, 1e-9)
    snr_sep = (mu1 - mu0) / math.sqrt(max(1e-9, s0 * s0 + s1 * s1))
    return {
        "status": "ok",
        "params": {
            "A0": a0,
            "mu0": mu0,
            "s0": s0,
            "A1": a1,
            "mu1": mu1,
            "s1": s1,
            "A2": a2,
            "mu2": mu2,
            "s2": s2,
            "gain": gain,
        },
        "xfit": xfit,
        "yfit": yfit,
        "components": [c0, c1, c2],
        "snr_ped": snr_ped,
        "snr_sep": snr_sep,
        "fit_window": [float(np.min(xf)), float(np.max(xf))],
    }
