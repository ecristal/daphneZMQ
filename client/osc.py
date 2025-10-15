#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import argparse
import numpy as np
import zmq

# ---- Optional SciPy window functions (fallbacks provided) ----
try:
    from scipy import signal as _scipy_signal
except Exception:
    _scipy_signal = None

from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg

# ---- Protobuf imports from your tree ----
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high

# ────────────────────── Window functions ──────────────────────
def _ensure_scipy():
    if _scipy_signal is None:
        raise RuntimeError(
            "SciPy is required for BLACKMAN-HARRIS/TUKEY windows. "
            "Install with `pip install scipy` or choose HANNING/HAMMING/BLACKMAN/NONE."
        )

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
        _ensure_scipy()
        return _scipy_signal.windows.blackmanharris(N)
    if name == "TUKEY":
        _ensure_scipy()
        return _scipy_signal.windows.tukey(N, alpha=0.1)
    raise ValueError(f"Unknown window function: {name}")

# ────────────────────── Oscilloscope App ──────────────────────
class DaphneOscApp(QtWidgets.QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args

        # Server & acquisition config
        self.endpoint = f"tcp://{args.ip}:{args.port}"
        self.channel = args.channel
        self.N = args.L
        self.software_trigger = args.software_trigger
        self.timeout_ms = args.timeout_ms
        self.Fs = 62.5e6  # Hz

        # ZMQ DEALER (ROUTER peer) with identity
        self.ctx = zmq.Context.instance()
        self.s = self.ctx.socket(zmq.DEALER)
        self.s.setsockopt(zmq.IDENTITY, args.identity.encode())
        self.s.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self.s.setsockopt(zmq.LINGER, 0)
        self.s.connect(self.endpoint)

        # Prebuild fixed parts of the request
        self.req = pb_high.DumpSpyBuffersRequest()
        self.req.channelList.append(self.channel)
        self.req.numberOfWaveforms = 1
        self.req.numberOfSamples = self.N
        self.req.softwareTrigger = self.software_trigger

        # UI
        self._build_ui(args)

        # FFT buffers (optional)
        self.enable_fft = args.enable_fft
        if self.enable_fft:
            self.f_axis = np.fft.rfftfreq(self.N, d=1.0/self.Fs)
            self._win = get_window(args.fft_window_function, self.N).astype(np.float64)
            self._W = self._win  # alias
            self.avg_count = args.fft_avg_waves
            self._fft_acc = np.zeros((self.avg_count, self.f_axis.size), dtype=np.float64)
            self._fft_idx = 0

        # Timer driving acquisition
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_once)
        self.timer.start(args.period_ms)

    # -------------------- UI --------------------
    def _build_ui(self, args):
        self.setWindowTitle(f"DAPHNE Oscilloscope — ch{self.channel} @ {self.endpoint}")
        layout = QtWidgets.QVBoxLayout(self)

        # Waveform plot
        self.plot_wf = pg.PlotWidget(title=f"Waveform (ch {self.channel})")
        self.plot_wf.setLabel('left', 'ADC counts')
        self.plot_wf.setLabel('bottom', 'Sample')
        self.curve_wf = self.plot_wf.plot(pen='y')
        layout.addWidget(self.plot_wf)

        # FFT plot
        if args.enable_fft:
            self.plot_fft = pg.PlotWidget(title="FFT (averaged)")
            self.plot_fft.setLabel('left', 'Magnitude (dBFS)')
            self.plot_fft.setLabel('bottom', 'Frequency (Hz)')
            self.curve_fft = self.plot_fft.plot(pen='c')
            layout.addWidget(self.plot_fft)

        # Status line
        self.status = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status)

        self.resize(1000, 700)

    # -------------------- Acquisition --------------------
    def _send_request(self):
        env = pb_high.ControlEnvelope()
        env.type = pb_high.DUMP_SPYBUFFER
        env.payload = self.req.SerializeToString()
        self.s.send(env.SerializeToString())

    def _recv_payload(self):
        # ROUTER replies [identity][payload]; DEALER receives all parts
        frames = [self.s.recv()]
        while self.s.getsockopt(zmq.RCVMORE):
            frames.append(self.s.recv())
        return frames[-1]

    def update_once(self):
        # Build & send request
        try:
            self._send_request()
        except Exception as e:
            self.status.setText(f"[send error] {e}")
            return

        # Receive reply
        try:
            reply = self._recv_payload()
        except zmq.Again:
            self.status.setText("[timeout] No response")
            return
        except Exception as e:
            self.status.setText(f"[recv error] {e}")
            return

        # Parse envelope
        env = pb_high.ControlEnvelope()
        try:
            env.ParseFromString(reply)
        except Exception as e:
            self.status.setText(f"[parse envelope] {e}")
            return

        if env.type != pb_high.DUMP_SPYBUFFER:
            # silently ignore unrelated frames
            self.status.setText(f"[unexpected message type {env.type}]")
            return

        # Parse response payload
        resp = pb_high.DumpSpyBuffersResponse()
        try:
            resp.ParseFromString(env.payload)
        except Exception as e:
            self.status.setText(f"[parse payload] {e}")
            return

        if not resp.success:
            self.status.setText(f"[server] {resp.message}")
            return

        # Data is repeated uint32 in your proto; interpret as np.uint32 (or int32)
        y = np.frombuffer(np.array(resp.data, dtype=np.uint32), dtype=np.int32)
        if y.size < self.N:
            self.status.setText(f"[warn] short waveform {y.size}/{self.N}")
            return
        y = y[:self.N]

        # Plot waveform
        self.curve_wf.setData(np.arange(self.N), y)
        self.status.setText(f"OK  ch={self.channel}  N={self.N}  trig={'SW' if self.software_trigger else 'EXT'}")

        # Optional FFT
        if self.enable_fft:
            # Window & rFFT
            yw = y.astype(np.float64) * self._W
            Y = np.fft.rfft(yw)
            # Normalize: single-sided magnitude in "counts"
            mag = np.abs(Y) / (self.N / 2.0)

            self._fft_acc[self._fft_idx % self.avg_count, :] = mag
            self._fft_idx += 1

            acc_valid = self._fft_acc[:min(self._fft_idx, self.avg_count), :]
            Y_avg = acc_valid.mean(axis=0)
            # Convert to dBFS (14-bit full-scale)
            Y_dbfs = 20.0 * np.log10(Y_avg / (2**14) + 1e-12)

            # Skip the first few bins (DC/very low-f)
            k0 = 4 if self.f_axis.size > 4 else 0
            self.curve_fft.setData(self.f_axis[k0:], Y_dbfs[k0:])

# ────────────────────── main ──────────────────────
def main():
    p = argparse.ArgumentParser(description="Fast oscilloscope with FFT using PyQtGraph (ROUTER-compatible).")
    p.add_argument("-ip", type=str, required=True, help="Server IP")
    p.add_argument("-port", type=int, default=9000, help="Server port (default 9000)")
    p.add_argument("-channel", type=int, required=True, help="Channel index [0..39]")
    p.add_argument("-L", type=int, required=True, help="Samples per waveform (<= 2048)")
    p.add_argument("-software_trigger", action="store_true", help="Use software trigger")
    p.add_argument("-enable_fft", action="store_true", help="Show averaged FFT plot")
    p.add_argument("-fft_avg_waves", type=int, default=2000, help="Averages for FFT")
    p.add_argument("-fft_window_function", type=str, default="BLACKMAN-HARRIS",
                   choices=["NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"])
    p.add_argument("-period_ms", type=int, default=20, help="Update period (ms)")
    p.add_argument("-timeout_ms", type=int, default=1000, help="ZMQ recv timeout (ms)")
    p.add_argument("-identity", type=str, default="osc-client", help="DEALER identity")
    args = p.parse_args()

    # Validate ranges the server enforces
    if not (0 <= args.channel <= 39):
        print("Channel must be in [0..39]")
        return 2
    if not (1 <= args.L <= 2048):
        print("L must be in [1..2048]")
        return 2

    app = QtWidgets.QApplication([])
    pg.setConfigOptions(antialias=True)
    w = DaphneOscApp(args)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
