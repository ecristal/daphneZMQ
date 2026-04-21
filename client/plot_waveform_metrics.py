#!/usr/bin/env python3
"""
Plot persistence, FFT, and RMS stats from previously acquired waveforms.

Assumes waveforms were saved as uint16 in per-channel files:
  folder/channel_<ch>.dat
as produced by protobuf_acquire_list_channels.py. You must supply the
samples-per-waveform (-L). Number of waveforms is inferred from file size.

Usage example:
  python3 client/plot_waveform_metrics.py \
    --folder runs/run01 --channels 8 9 10 \
    --L 2048 --fs 62.5e6 --max_waves 2000
"""

import argparse
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

try:
    from scipy import signal as _scipy_signal
except Exception:
    _scipy_signal = None


def get_window(name, N):
    name = name.upper()
    if name == "NONE":
        return np.ones(N, dtype=float)
    if name == "HANNING":
        return np.hanning(N)
    if name == "HAMMING":
        return np.hamming(N)
    if name == "BLACKMAN":
        return np.blackman(N)
    if name == "BLACKMAN-HARRIS":
        if _scipy_signal is None:
            raise RuntimeError("SciPy required for BLACKMAN-HARRIS; install scipy or choose another window.")
        return _scipy_signal.windows.blackmanharris(N)
    if name == "TUKEY":
        if _scipy_signal is None:
            raise RuntimeError("SciPy required for TUKEY; install scipy or choose another window.")
        return _scipy_signal.windows.tukey(N, alpha=0.1)
    raise ValueError(f"Unknown window function: {name}")


def load_channel(fname: str, L: int, max_waves: int | None):
    raw = np.fromfile(fname, dtype=np.uint16)
    if raw.size % L != 0:
        raise ValueError(f"{fname}: size {raw.size} not divisible by L={L}")
    total_waves = raw.size // L
    if max_waves is not None:
        total_waves = min(total_waves, max_waves)
        raw = raw[: total_waves * L]
    data = raw.astype(np.int32).reshape(total_waves, L)
    return data


def plot_persistence(ax, waves, title):
    # 2D histogram for persistence
    x = np.tile(np.arange(waves.shape[1]), waves.shape[0])
    y = waves.ravel()
    ax.hist2d(x, y, bins=[waves.shape[1]//4, 200], cmap="viridis", norm=None)
    ax.set_title(title)
    ax.set_xlabel("Sample")
    ax.set_ylabel("ADC counts")


def plot_fft(ax, waves, fs_hz, avg_waves, window_fn, title):
    # Mimic osc: window -> rfft -> magnitude avg -> dBFS
    w = waves.astype(np.float64)
    W = window_fn(w.shape[1])
    if W is None:
        W = np.ones(w.shape[1], dtype=np.float64)
    w *= W
    N = w.shape[1]
    fft = np.fft.rfft(w, axis=1)
    mag = np.abs(fft) / (N / 2.0)
    # average over up to avg_waves waveforms
    if avg_waves is not None:
        mag = mag[:avg_waves, :]
    mag_avg = mag.mean(axis=0)
    dbfs = 20.0 * np.log10(mag_avg / (2**14) + 1e-12)
    freq = np.fft.rfftfreq(N, d=1.0/fs_hz)
    k0 = 4 if freq.size > 4 else 0
    ax.plot(freq[k0:]/1e6, dbfs[k0:], lw=1.0)
    ax.set_title(title)
    ax.set_xlabel("Frequency [MHz]")
    ax.set_ylabel("Magnitude [dBFS]")
    ax.grid(True, alpha=0.3)


def main():
    ap = argparse.ArgumentParser(description="Plot persistence, FFT, RMS from saved waveforms.")
    ap.add_argument("--folder", required=True, help="Folder containing channel_<ch>.dat files")
    ap.add_argument("--channels", type=int, nargs="+", required=True, help="Channel numbers matching file names")
    ap.add_argument("-L", type=int, required=True, help="Samples per waveform")
    ap.add_argument("--fs", type=float, default=62.5e6, help="Sampling rate (Hz) for FFT axis")
    ap.add_argument("--max_waves", type=int, default=2000, help="Max waveforms to load per channel (default 2000)")
    ap.add_argument("--fft_avg_waves", type=int, default=2000, help="Number of waveforms to average in FFT (matches osc default)")
    ap.add_argument("--fft_window", type=str, default="BLACKMAN-HARRIS",
                    choices=["NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"],
                    help="FFT window (matches osc choices)")
    ap.add_argument("--save", action="store_true", help="Save plots to PNG files (persistence.png, fft.png) in the folder")
    ap.add_argument("--save-prefix", type=str, default="", help="Optional prefix for saved files (default: none)")
    args = ap.parse_args()

    folder = args.folder
    L = args.L
    fs = args.fs
    max_waves = args.max_waves

    rms_stats = []
    fig_p, axs_p = plt.subplots(len(args.channels), 1, figsize=(10, 3*len(args.channels)), sharex=True)
    if len(args.channels) == 1:
        axs_p = [axs_p]
    fig_f, axs_f = plt.subplots(len(args.channels), 1, figsize=(10, 3*len(args.channels)), sharex=True)
    if len(args.channels) == 1:
        axs_f = [axs_f]

    for idx, ch in enumerate(args.channels):
        fname = os.path.join(folder, f"channel_{ch}.dat")
        if not os.path.exists(fname):
            print(f"[skip] {fname} not found")
            continue
        waves = load_channel(fname, L, max_waves)
        rms = np.sqrt((waves.astype(np.float64)**2).mean(axis=1))
        rms_stats.append((ch, rms.mean(), rms.std()))

        plot_persistence(axs_p[idx], waves, f"Ch {ch} persistence (N={waves.shape[0]})")
        window_fn = lambda n, fn=args.fft_window: get_window(fn, n)
        plot_fft(axs_f[idx], waves, fs, args.fft_avg_waves, window_fn, f"Ch {ch} FFT (N={waves.shape[0]})")

    print("RMS stats (counts):")
    for ch, mean_rms, std_rms in rms_stats:
        print(f"  ch{ch:02d}: mean={mean_rms:.2f}, std={std_rms:.2f}")

    fig_p.tight_layout()
    fig_f.tight_layout()

    if args.save:
        prefix = args.save_prefix
        p_path = os.path.join(folder, f"{prefix}persistence.png")
        f_path = os.path.join(folder, f"{prefix}fft.png")
        fig_p.savefig(p_path, dpi=150)
        fig_f.savefig(f_path, dpi=150)
        print(f"Saved plots to {p_path} and {f_path}")

    plt.show()


if __name__ == "__main__":
    sys.exit(main())
