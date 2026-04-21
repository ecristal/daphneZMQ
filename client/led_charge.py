from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ChargeWindow:
    channel: int
    baseline_start: int
    baseline_stop: int
    search_start: int
    search_stop: int
    onset_index: int
    peak_index: int
    integrate_start: int
    integrate_stop: int

    def as_dict(self) -> dict[str, int]:
        return {
            "channel": int(self.channel),
            "baseline_start": int(self.baseline_start),
            "baseline_stop": int(self.baseline_stop),
            "search_start": int(self.search_start),
            "search_stop": int(self.search_stop),
            "onset_index": int(self.onset_index),
            "peak_index": int(self.peak_index),
            "integrate_start": int(self.integrate_start),
            "integrate_stop": int(self.integrate_stop),
        }


def load_channel_waves(path: str | Path, n_samples: int, *, max_waves: int = 0, interpret: str = "signed") -> np.ndarray:
    raw = np.fromfile(path, dtype=np.uint16)
    if raw.size % n_samples != 0:
        raise ValueError(f"{path}: size {raw.size} is not divisible by L={n_samples}")

    n_total = raw.size // n_samples
    n_use = n_total if max_waves <= 0 else min(n_total, max_waves)
    raw = raw[: n_use * n_samples]

    if interpret == "signed":
        vals = raw.view(np.int16).astype(np.int32, copy=False)
    elif interpret == "unsigned":
        vals = raw.astype(np.int32, copy=False)
    else:
        raise ValueError(f"Unsupported interpret mode: {interpret}")

    return vals.reshape(n_use, n_samples)


def compute_baseline(waves: np.ndarray, start: int, stop: int) -> np.ndarray:
    lo, hi = normalize_bounds(waves.shape[1], start, stop)
    if hi <= lo:
        raise ValueError(f"Invalid baseline window [{start}, {stop})")
    return waves[:, lo:hi].mean(axis=1)


def compute_charge(
    waves: np.ndarray,
    *,
    integrate_start: int,
    integrate_stop: int,
    baseline_start: int,
    baseline_stop: int,
    clip_negative: bool = False,
) -> np.ndarray:
    if waves.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {waves.shape}")

    lo, hi = normalize_bounds(waves.shape[1], integrate_start, integrate_stop)
    base = compute_baseline(waves, baseline_start, baseline_stop)[:, np.newaxis]
    seg = waves[:, lo:hi].astype(np.float64, copy=False) - base
    if clip_negative:
        seg = np.maximum(seg, 0.0)
    return seg.sum(axis=1)


def pedestal_window_for_charge(
    charge_window: ChargeWindow,
    *,
    n_samples: int,
    window_len: int | None = None,
) -> tuple[int, int]:
    use_len = int(window_len) if window_len is not None else int(charge_window.integrate_stop - charge_window.integrate_start)
    if use_len <= 0:
        raise ValueError("window_len must be > 0")

    ped_stop = int(charge_window.baseline_stop)
    ped_start = max(int(charge_window.baseline_start), ped_stop - use_len)
    ped_stop = min(int(n_samples), ped_start + use_len)
    if ped_stop <= ped_start:
        raise ValueError(f"Invalid pedestal window for channel {charge_window.channel}")
    return ped_start, ped_stop


def reanchor_charge_window(
    charge_window: ChargeWindow,
    *,
    n_samples: int,
    anchor: str,
    pre_samples: int,
    post_samples: int,
) -> ChargeWindow:
    pre = max(0, int(pre_samples))
    post = max(1, int(post_samples))
    anchor_mode = str(anchor).strip().lower()
    if anchor_mode == "peak":
        anchor_index = int(charge_window.peak_index)
    elif anchor_mode == "onset":
        anchor_index = int(charge_window.onset_index)
    else:
        raise ValueError(f"Unsupported charge window anchor: {anchor}")

    start = max(0, min(int(n_samples), anchor_index - pre))
    stop = max(start + 1, min(int(n_samples), anchor_index + post))
    return ChargeWindow(
        channel=int(charge_window.channel),
        baseline_start=int(charge_window.baseline_start),
        baseline_stop=int(charge_window.baseline_stop),
        search_start=int(charge_window.search_start),
        search_stop=int(charge_window.search_stop),
        onset_index=int(charge_window.onset_index),
        peak_index=int(charge_window.peak_index),
        integrate_start=int(start),
        integrate_stop=int(stop),
    )


def normalize_bounds(n_samples: int, start: int | None, stop: int | None) -> tuple[int, int]:
    lo = 0 if start is None else max(0, min(n_samples, int(start)))
    hi = n_samples if stop is None else max(0, min(n_samples, int(stop)))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def mean_waveform(waves: np.ndarray) -> np.ndarray:
    if waves.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {waves.shape}")
    return waves.astype(np.float64, copy=False).mean(axis=0)


def calibrate_window_from_mean(
    mean_wf: np.ndarray,
    *,
    channel: int,
    baseline_start: int,
    baseline_stop: int,
    search_start: int,
    search_stop: int,
    onset_fraction: float,
    integrate_offset: int,
    integrate_len: int,
) -> ChargeWindow:
    n_samples = mean_wf.size
    b_lo, b_hi = normalize_bounds(n_samples, baseline_start, baseline_stop)
    s_lo, s_hi = normalize_bounds(n_samples, search_start, search_stop)
    if b_hi <= b_lo:
        raise ValueError(f"Invalid baseline window [{baseline_start}, {baseline_stop})")
    if s_hi <= s_lo:
        raise ValueError(f"Invalid search window [{search_start}, {search_stop})")
    if integrate_len <= 0:
        raise ValueError("integrate_len must be > 0")

    baseline = float(mean_wf[b_lo:b_hi].mean())
    signal = mean_wf[s_lo:s_hi] - baseline
    peak_rel = int(np.argmax(signal))
    peak_index = s_lo + peak_rel
    amplitude = float(signal[peak_rel])

    if amplitude <= 0.0:
        raise ValueError(f"Channel {channel}: no positive LED signal found in calibration window")

    frac = min(max(float(onset_fraction), 0.01), 0.95)
    threshold = amplitude * frac
    above = np.flatnonzero(signal >= threshold)
    if above.size > 0:
        onset_index = s_lo + int(above[0])
    else:
        deriv = np.diff(signal, prepend=signal[0])
        onset_index = s_lo + int(np.argmax(deriv))

    integrate_start = max(0, min(n_samples, onset_index + int(integrate_offset)))
    integrate_stop = max(integrate_start + 1, min(n_samples, integrate_start + int(integrate_len)))

    return ChargeWindow(
        channel=int(channel),
        baseline_start=b_lo,
        baseline_stop=b_hi,
        search_start=s_lo,
        search_stop=s_hi,
        onset_index=int(onset_index),
        peak_index=int(peak_index),
        integrate_start=int(integrate_start),
        integrate_stop=int(integrate_stop),
    )


def calibrate_windows_from_folder(
    folder: str | Path,
    *,
    channels: list[int],
    n_samples: int,
    baseline_start: int,
    baseline_stop: int,
    search_start: int,
    search_stop: int,
    onset_fraction: float,
    integrate_offset: int,
    integrate_len: int,
    max_waves: int = 0,
    interpret: str = "signed",
) -> dict[int, ChargeWindow]:
    folder = Path(folder)
    out: dict[int, ChargeWindow] = {}
    for ch in channels:
        path = folder / f"channel_{ch}.dat"
        waves = load_channel_waves(path, n_samples, max_waves=max_waves, interpret=interpret)
        out[int(ch)] = calibrate_window_from_mean(
            mean_waveform(waves),
            channel=int(ch),
            baseline_start=baseline_start,
            baseline_stop=baseline_stop,
            search_start=search_start,
            search_stop=search_stop,
            onset_fraction=onset_fraction,
            integrate_offset=integrate_offset,
            integrate_len=integrate_len,
        )
    return out


def save_charge_windows(path: str | Path, windows: dict[int, ChargeWindow], *, metadata: dict[str, Any] | None = None) -> None:
    payload = {
        "metadata": dict(metadata or {}),
        "windows": {str(ch): win.as_dict() for ch, win in sorted(windows.items())},
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_charge_windows(path: str | Path) -> dict[int, ChargeWindow]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    windows_raw = raw.get("windows", raw)
    out: dict[int, ChargeWindow] = {}
    for key, value in windows_raw.items():
        channel = int(value.get("channel", key))
        out[channel] = ChargeWindow(
            channel=channel,
            baseline_start=int(value["baseline_start"]),
            baseline_stop=int(value["baseline_stop"]),
            search_start=int(value.get("search_start", value["integrate_start"])),
            search_stop=int(value.get("search_stop", value["integrate_stop"])),
            onset_index=int(value.get("onset_index", value["integrate_start"])),
            peak_index=int(value.get("peak_index", value["integrate_start"])),
            integrate_start=int(value["integrate_start"]),
            integrate_stop=int(value["integrate_stop"]),
        )
    return out


def histogram_payload(charges: np.ndarray, bins: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arr = np.asarray(charges, dtype=np.float64)
    if arr.size == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    lo = float(np.min(arr))
    hi = float(np.max(arr))
    if not np.isfinite(lo) or not np.isfinite(hi):
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    if hi <= lo:
        hi = lo + 1.0
    counts, edges = np.histogram(arr, bins=max(8, int(bins)), range=(lo, hi))
    centers = 0.5 * (edges[:-1] + edges[1:])
    return centers, edges, counts.astype(np.float64, copy=False)


def summarize_charge_distribution(
    charges: np.ndarray,
    *,
    bins: int = 120,
    target_signal_fraction: float = 0.5,
) -> dict[str, float | int | bool | None]:
    arr = np.asarray(charges, dtype=np.float64)
    if arr.size == 0:
        return {
            "n_waveforms": 0,
            "threshold_charge": None,
            "signal_fraction": None,
            "balance_error": None,
            "pedestal_mean": None,
            "signal_mean": None,
            "snr_estimate": None,
            "two_cluster_split": False,
        }

    centers, _edges, counts = histogram_payload(arr, bins)
    if centers.size == 0:
        return {
            "n_waveforms": int(arr.size),
            "threshold_charge": None,
            "signal_fraction": None,
            "balance_error": None,
            "pedestal_mean": None,
            "signal_mean": None,
            "snr_estimate": None,
            "two_cluster_split": False,
        }

    smooth = counts.copy()
    if smooth.size >= 5:
        kernel = np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=np.float64)
        kernel /= kernel.sum()
        smooth = np.convolve(smooth, kernel, mode="same")

    threshold = _otsu_threshold(arr, bins)
    left = arr[arr <= threshold]
    right = arr[arr > threshold]

    signal_fraction = float(right.size / arr.size)
    balance_error = abs(signal_fraction - float(target_signal_fraction))

    if left.size >= 3 and right.size >= 3:
        pedestal_mean = float(left.mean())
        signal_mean = float(right.mean())
        pedestal_std = float(left.std(ddof=0))
        signal_std = float(right.std(ddof=0))
        denom = float(np.hypot(pedestal_std, signal_std))
        snr_estimate = float((signal_mean - pedestal_mean) / denom) if denom > 0 else float("nan")
        split_ok = True
    else:
        pedestal_mean = float(np.mean(arr))
        signal_mean = None
        snr_estimate = None
        split_ok = False

    return {
        "n_waveforms": int(arr.size),
        "threshold_charge": float(threshold),
        "signal_fraction": float(signal_fraction),
        "balance_error": float(balance_error),
        "pedestal_mean": float(pedestal_mean),
        "signal_mean": None if signal_mean is None else float(signal_mean),
        "snr_estimate": None if snr_estimate is None else float(snr_estimate),
        "two_cluster_split": bool(split_ok),
    }


def _otsu_threshold(arr: np.ndarray, bins: int) -> float:
    counts, edges = np.histogram(arr, bins=max(8, int(bins)))
    counts = counts.astype(np.float64, copy=False)
    mids = 0.5 * (edges[:-1] + edges[1:])

    weight1 = np.cumsum(counts)
    weight2 = np.cumsum(counts[::-1])[::-1]

    mean1 = np.cumsum(counts * mids) / np.maximum(weight1, 1.0)
    mean2 = (np.cumsum((counts * mids)[::-1]) / np.maximum(weight2[::-1], 1.0))[::-1]

    inter_class = weight1[:-1] * weight2[1:] * (mean1[:-1] - mean2[1:]) ** 2
    if inter_class.size == 0:
        return float(mids[0])
    idx = int(np.argmax(inter_class))
    return float(mids[idx])


def summarize_charge_vs_pedestal(
    charges: np.ndarray,
    pedestal_charges: np.ndarray,
    *,
    target_signal_fraction: float = 0.5,
    threshold_sigma: float = 4.0,
    threshold_quantile: float = 0.995,
) -> dict[str, float | int | bool | None]:
    signal = np.asarray(charges, dtype=np.float64)
    pedestal = np.asarray(pedestal_charges, dtype=np.float64)

    if signal.size == 0 or pedestal.size == 0:
        return {
            "n_waveforms": int(signal.size),
            "threshold_charge": None,
            "signal_fraction": None,
            "balance_error": None,
            "pedestal_mean": None,
            "pedestal_sigma": None,
            "signal_mean": None,
            "snr_estimate": None,
            "threshold_source": "pedestal_ref",
        }

    ped_median = float(np.median(pedestal))
    ped_mean = float(np.mean(pedestal))
    ped_mad = float(np.median(np.abs(pedestal - ped_median)))
    ped_sigma = float(max(1e-12, 1.4826 * ped_mad))
    q_hi = float(np.quantile(pedestal, min(max(threshold_quantile, 0.5), 0.9999)))
    threshold = max(ped_median + float(threshold_sigma) * ped_sigma, q_hi)

    selected = signal > threshold
    signal_fraction = float(np.mean(selected))
    balance_error = abs(signal_fraction - float(target_signal_fraction))

    if np.any(selected):
        signal_mean = float(np.mean(signal[selected]))
        signal_std = float(np.std(signal[selected], ddof=0))
    else:
        signal_mean = None
        signal_std = None

    if signal_mean is not None:
        denom = float(np.hypot(ped_sigma, signal_std if signal_std is not None else 0.0))
        snr_estimate = float((signal_mean - ped_mean) / denom) if denom > 0 else None
    else:
        snr_estimate = None

    return {
        "n_waveforms": int(signal.size),
        "threshold_charge": float(threshold),
        "signal_fraction": float(signal_fraction),
        "balance_error": float(balance_error),
        "pedestal_mean": float(ped_mean),
        "pedestal_sigma": float(ped_sigma),
        "signal_mean": None if signal_mean is None else float(signal_mean),
        "snr_estimate": None if snr_estimate is None else float(snr_estimate),
        "threshold_source": "pedestal_ref",
    }


class FixedWindowChargeMonitor:
    def __init__(
        self,
        *,
        channels: list[int],
        n_samples: int,
        windows: dict[int, ChargeWindow],
        history: int,
        hist_bins: int,
        clip_negative: bool = False,
    ):
        self.channels = list(channels)
        self.n_samples = int(n_samples)
        self.windows = dict(windows)
        self.history = max(16, int(history))
        self.hist_bins = max(8, int(hist_bins))
        self.clip_negative = bool(clip_negative)
        self._series = {int(ch): deque(maxlen=self.history) for ch in self.channels}

        missing = [ch for ch in self.channels if ch not in self.windows]
        if missing:
            raise ValueError(f"Missing charge windows for channels: {missing}")

    def update(self, yk: np.ndarray) -> dict[str, Any]:
        if yk.ndim != 2 or yk.shape[0] != len(self.channels) or yk.shape[1] != self.n_samples:
            raise ValueError(f"Invalid waveform frame shape {yk.shape}")

        charges_by_channel: dict[int, float] = {}
        for idx, ch in enumerate(self.channels):
            win = self.windows[ch]
            charge = compute_charge(
                yk[idx : idx + 1, :],
                integrate_start=win.integrate_start,
                integrate_stop=win.integrate_stop,
                baseline_start=win.baseline_start,
                baseline_stop=win.baseline_stop,
                clip_negative=self.clip_negative,
            )[0]
            q = float(charge)
            self._series[ch].append(q)
            charges_by_channel[ch] = q
        return {
            "latest_charge": charges_by_channel,
            "windows": {
                int(ch): {
                    "integrate_start": int(self.windows[ch].integrate_start),
                    "integrate_stop": int(self.windows[ch].integrate_stop),
                    "onset_index": int(self.windows[ch].onset_index),
                    "peak_index": int(self.windows[ch].peak_index),
                }
                for ch in self.channels
            },
        }

    def history_for_channel(self, channel: int) -> np.ndarray:
        return np.asarray(self._series[int(channel)], dtype=np.float64)

    def histogram_series(self) -> dict[int, dict[str, np.ndarray]]:
        non_empty = [self.history_for_channel(ch) for ch in self.channels if len(self._series[int(ch)]) > 0]
        if not non_empty:
            return {}

        combined = np.concatenate(non_empty)
        lo = float(np.min(combined))
        hi = float(np.max(combined))
        if hi <= lo:
            hi = lo + 1.0
        edges = np.linspace(lo, hi, self.hist_bins + 1, dtype=np.float64)
        centers = 0.5 * (edges[:-1] + edges[1:])

        out: dict[int, dict[str, np.ndarray]] = {}
        for ch in self.channels:
            arr = self.history_for_channel(ch)
            if arr.size == 0:
                continue
            counts, _ = np.histogram(arr, bins=edges)
            out[int(ch)] = {
                "centers": centers,
                "counts": counts.astype(np.float64, copy=False),
            }
        return out
