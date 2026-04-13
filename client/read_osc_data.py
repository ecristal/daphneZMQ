#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_metadata(run_dir: Path) -> dict:
    meta_path = run_dir / "run_metadata.json"
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def resolve_paths(input_path: Path, channel: int | None) -> tuple[Path, Path]:
    if input_path.is_dir():
        if channel is None:
            raise ValueError("--channel is required when the input path is a run directory")
        return input_path, input_path / f"channel_{channel}.dat"

    if input_path.is_file():
        if channel is None:
            stem = input_path.stem
            if stem.startswith("channel_"):
                try:
                    channel = int(stem.split("_", 1)[1])
                except ValueError:
                    pass
        return input_path.parent, input_path

    raise FileNotFoundError(f"Input path not found: {input_path}")


def load_waveforms(channel_path: Path, n_samples: int, interpret: str) -> np.ndarray:
    raw = np.fromfile(channel_path, dtype=np.uint16)
    if raw.size == 0:
        raise ValueError(f"No samples found in {channel_path}")
    if raw.size % n_samples != 0:
        raise ValueError(
            f"{channel_path}: sample count {raw.size} is not divisible by samples_per_waveform={n_samples}"
        )

    if interpret == "signed":
        values = raw.view(np.int16).astype(np.int32, copy=False)
    else:
        values = raw.astype(np.int32, copy=False)

    return values.reshape((-1, n_samples))


def make_window(name: str, n_samples: int) -> np.ndarray:
    name = name.upper()
    if name == "NONE":
        return np.ones(n_samples, dtype=np.float64)
    if name == "HANNING":
        return np.hanning(n_samples).astype(np.float64)
    if name == "HAMMING":
        return np.hamming(n_samples).astype(np.float64)
    if name == "BLACKMAN":
        return np.blackman(n_samples).astype(np.float64)
    if name == "BLACKMAN-HARRIS":
        n = np.arange(n_samples, dtype=np.float64)
        scale = 2.0 * np.pi * n / max(1, n_samples - 1)
        return (
            0.35875
            - 0.48829 * np.cos(scale)
            + 0.14128 * np.cos(2.0 * scale)
            - 0.01168 * np.cos(3.0 * scale)
        )
    if name == "TUKEY":
        alpha = 0.1
        if n_samples <= 1:
            return np.ones(n_samples, dtype=np.float64)
        x = np.linspace(0.0, 1.0, n_samples, dtype=np.float64)
        w = np.ones(n_samples, dtype=np.float64)
        left = x < alpha / 2.0
        right = x > 1.0 - alpha / 2.0
        w[left] = 0.5 * (1.0 + np.cos(2.0 * np.pi / alpha * (x[left] - alpha / 2.0)))
        w[right] = 0.5 * (1.0 + np.cos(2.0 * np.pi / alpha * (x[right] - 1.0 + alpha / 2.0)))
        return w
    raise ValueError(f"Unsupported FFT window: {name}")


def compute_fft_dbfs(
    waves: np.ndarray,
    fs_hz: float,
    window_name: str,
    full_scale_counts: float,
    keep_dc: bool,
) -> tuple[np.ndarray, np.ndarray]:
    window = make_window(window_name, waves.shape[1])
    x = waves.astype(np.float64, copy=False)
    if not keep_dc:
        x = x - x.mean(axis=1, keepdims=True)
    xw = x * window[np.newaxis, :]
    xf = np.fft.rfft(xw, axis=1)
    power = (xf.real * xf.real + xf.imag * xf.imag) / np.sum(window * window)
    mean_power = power.mean(axis=0)
    dbfs = 10.0 * np.log10((mean_power / (full_scale_counts * full_scale_counts)) + 1e-24)
    freq_hz = np.fft.rfftfreq(waves.shape[1], d=1.0 / fs_hz)
    if not keep_dc and dbfs.size > 0:
        dbfs = dbfs.copy()
        dbfs[0] = np.nan
    return freq_hz, dbfs


def main() -> int:
    ap = argparse.ArgumentParser(description="Read osc channel_<n>.dat files from a saved run.")
    ap.add_argument("input", help="Run directory or channel_<n>.dat file")
    ap.add_argument("-c", "--channel", type=int, default=None, help="Channel number when input is a run directory")
    ap.add_argument(
        "-L",
        "--samples-per-waveform",
        type=int,
        default=0,
        help="Override samples_per_waveform. Default: read from run_metadata.json",
    )
    ap.add_argument(
        "--interpret",
        choices=["signed", "unsigned"],
        default="signed",
        help="How to interpret the stored uint16 words",
    )
    ap.add_argument("-w", "--waveform", type=int, default=0, help="Waveform index to inspect")
    ap.add_argument(
        "--print-samples",
        type=int,
        default=16,
        help="How many samples from the selected waveform to print",
    )
    ap.add_argument("--mean", action="store_true", help="Show the mean waveform instead of a single waveform")
    ap.add_argument("--plot", action="store_true", help="Plot the selected waveform or mean waveform")
    ap.add_argument("--fft", action="store_true", help="Compute FFT")
    ap.add_argument(
        "--fft-avg-waves",
        type=int,
        default=1,
        help="Number of waveforms to average in the FFT. Use 0 for all waveforms",
    )
    ap.add_argument(
        "--fft-window",
        default="",
        help="FFT window function: NONE, HANNING, HAMMING, BLACKMAN, BLACKMAN-HARRIS, TUKEY",
    )
    ap.add_argument("--fs", type=float, default=0.0, help="Sampling rate override in Hz")
    ap.add_argument("--fft-full-scale", type=float, default=0.0, help="Full-scale ADC counts override for dBFS")
    ap.add_argument("--fft-keep-dc", action="store_true", help="Keep the DC bin in the FFT")
    ap.add_argument("--fft-log-x", action="store_true", help="Use a log x-axis when plotting the FFT")
    args = ap.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    run_dir, channel_path = resolve_paths(input_path, args.channel)
    metadata = load_metadata(run_dir)

    n_samples = int(args.samples_per_waveform or metadata.get("samples_per_waveform", 0) or 0)
    if n_samples <= 0:
        raise ValueError("Could not determine samples_per_waveform. Pass -L explicitly or use a run directory with run_metadata.json")
    if not channel_path.exists():
        raise FileNotFoundError(f"Channel file not found: {channel_path}")

    waves = load_waveforms(channel_path, n_samples=n_samples, interpret=args.interpret)
    n_waveforms = waves.shape[0]

    waveform_index = args.waveform
    if waveform_index < 0 or waveform_index >= n_waveforms:
        raise IndexError(f"Waveform index {waveform_index} out of range 0..{n_waveforms - 1}")

    selected = waves.mean(axis=0) if args.mean else waves[waveform_index]
    selected_name = "mean waveform" if args.mean else f"waveform {waveform_index}"

    print(f"run_dir: {run_dir}")
    print(f"channel_file: {channel_path}")
    print(f"interpret: {args.interpret}")
    print(f"waveforms: {n_waveforms}")
    print(f"samples_per_waveform: {n_samples}")
    if metadata.get("sampling_rate_hz"):
        print(f"sampling_rate_hz: {metadata['sampling_rate_hz']}")
    print(f"selected: {selected_name}")
    print(
        f"selected_stats: min={selected.min():.0f} max={selected.max():.0f} "
        f"mean={selected.mean():.3f} std={selected.std():.3f}"
    )

    count = max(0, min(args.print_samples, n_samples))
    if count > 0:
        print(f"first_{count}_samples:")
        print(" ".join(str(int(v)) for v in selected[:count]))

    freq_hz = None
    fft_dbfs = None
    if args.fft:
        fft_wave_count = waves.shape[0] if args.fft_avg_waves <= 0 else min(args.fft_avg_waves, waves.shape[0])
        fft_input = waves[:fft_wave_count, :]
        fs_hz = float(args.fs or metadata.get("sampling_rate_hz", 0.0) or 62.5e6)
        fft_full_scale = float(args.fft_full_scale or metadata.get("fft_full_scale_counts", 0.0) or 16384.0)
        fft_window = str(args.fft_window or metadata.get("fft_window_function", "BLACKMAN-HARRIS"))
        keep_dc = bool(args.fft_keep_dc or metadata.get("fft_keep_dc", False))

        freq_hz, fft_dbfs = compute_fft_dbfs(
            fft_input,
            fs_hz=fs_hz,
            window_name=fft_window,
            full_scale_counts=fft_full_scale,
            keep_dc=keep_dc,
        )

        finite = np.isfinite(fft_dbfs)
        if np.any(finite):
            peak_idx = int(np.nanargmax(fft_dbfs))
            print(f"fft_avg_waves: {fft_wave_count}")
            print(f"fft_window: {fft_window}")
            print(f"fft_full_scale_counts: {fft_full_scale}")
            print(f"fft_peak_freq_hz: {freq_hz[peak_idx]:.3f}")
            print(f"fft_peak_dbfs: {fft_dbfs[peak_idx]:.3f}")

    if args.plot:
        import matplotlib.pyplot as plt

        if args.fft:
            fig, axes = plt.subplots(2, 1, figsize=(10, 7))
            ax_time, ax_fft = axes
        else:
            fig, ax_time = plt.subplots(1, 1, figsize=(10, 4))
            ax_fft = None

        x = np.arange(n_samples)
        ax_time.plot(x, selected)
        ax_time.set_title(f"{channel_path.name}: {selected_name}")
        ax_time.set_xlabel("Sample")
        ax_time.set_ylabel("ADC counts")
        ax_time.grid(True, alpha=0.3)

        if args.fft and ax_fft is not None and freq_hz is not None and fft_dbfs is not None:
            ax_fft.plot(freq_hz, fft_dbfs)
            ax_fft.set_title("FFT")
            ax_fft.set_xlabel("Frequency [Hz]")
            ax_fft.set_ylabel("Power [dBFS/bin]")
            ax_fft.grid(True, alpha=0.3)
            if args.fft_log_x:
                ax_fft.set_xscale("log")

        plt.tight_layout()
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
