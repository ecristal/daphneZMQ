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

from PyQt6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg

# ---- Protobuf imports from your tree ----
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high

# ---- Shared waveform parser (same directory) ----
# If you prefer keeping it as a package import, change to: from client.waveparse import parse_dump_response
from waveparse import parse_dump_response


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

# ────────────────────── V2 helper ──────────────────────
class V2Link:
    def __init__(self, endpoint, identity: bytes, timeout_ms: int):
        self.ctx = zmq.Context.instance()
        self.s   = self.ctx.socket(zmq.DEALER)
        self.s.setsockopt(zmq.IDENTITY, identity)
        self.s.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.s.setsockopt(zmq.SNDTIMEO, timeout_ms)
        self.s.setsockopt(zmq.LINGER,   0)
        self.s.connect(endpoint)
        self._seq = 0
        self._rand = int(time.time_ns()) & 0xFFFFFFFF

    def _next_ids(self):
        self._seq += 1
        now = time.time_ns()
        task_id = (now << 16) ^ (os.getpid() << 8) ^ (self._rand & 0xFF)
        msg_id  = (now << 1) ^ self._seq
        mask = (1 << 63) - 1
        return task_id & mask, msg_id & mask

    def request(self, mtype_req, payload_bytes: bytes, route: str|None=None):
        env = pb_high.ControlEnvelopeV2()
        env.version = 2
        env.dir     = pb_high.DIR_REQUEST
        env.type    = mtype_req
        env.payload = payload_bytes
        env.task_id, env.msg_id = self._next_ids()
        env.timestamp_ns = time.time_ns()
        if route:
            env.route = route

        t0 = time.time_ns()
        self.s.send(env.SerializeToString())
        frames = [self.s.recv()]
        while self.s.getsockopt(zmq.RCVMORE):
            frames.append(self.s.recv())
        t1 = time.time_ns()

        rep = pb_high.ControlEnvelopeV2()
        rep.ParseFromString(frames[-1])

        if rep.dir != pb_high.DIR_RESPONSE:
            raise RuntimeError(f"Unexpected dir={rep.dir}")
        if rep.correl_id != env.msg_id:
            raise RuntimeError("V2 correlation/type mismatch (correl_id != req.msg_id)")

        rtt_ms = (t1 - t0) / 1e6
        return env, rep, rtt_ms

# ────────────────────── Oscilloscope App ──────────────────────
class DaphneOscApp(QtWidgets.QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args

        # Server & acquisition config
        self.endpoint = f"tcp://{args.ip}:{args.port}"
        # multi-channel: list of ints
        self.channels = args.channels if args.channels else [args.channel]
        self.N = args.L
        self.software_trigger = args.software_trigger
        self.timeout_ms = args.timeout_ms
        self.Fs = args.sampling_rate_hz  # default 62.5e6

        # ZMQ V2 link
        self.link = V2Link(self.endpoint, args.identity.encode(), self.timeout_ms)
        self.route = args.route

        # Prebuild fixed parts of the request
        self.req = pb_high.DumpSpyBuffersRequest()
        self.req.channelList.extend(self.channels)
        self.req.numberOfWaveforms = 1
        self.req.numberOfSamples = self.N
        self.req.softwareTrigger = self.software_trigger

        # UI
        self._build_ui(args)

        # FFT buffers (optional) — do FFT of the first channel
        self.enable_fft = args.enable_fft
        if self.enable_fft:
            self.f_axis = np.fft.rfftfreq(self.N, d=1.0/self.Fs)
            self._win = get_window(args.fft_window_function, self.N).astype(np.float64)
            self._W = self._win
            self.avg_count = max(1, int(args.fft_avg_waves))
            self._fft_acc = np.zeros((self.avg_count, self.f_axis.size), dtype=np.float64)
            self._fft_idx = 0

        # Auto y-range
        self.autoscale = True

        # Timer driving acquisition
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_once)
        self.timer.start(args.period_ms)

    # -------------------- UI --------------------
    def _build_ui(self, args):
        ch_label = ",".join(str(c) for c in self.channels)
        self.setWindowTitle(f"DAPHNE Oscilloscope — ch[{ch_label}] @ {self.endpoint}")
        layout = QtWidgets.QVBoxLayout(self)

        # Waveform plot
        self.plot_wf = pg.PlotWidget(title=f"Waveforms (ch {ch_label})")
        self.plot_wf.setLabel('left', 'ADC counts')
        self.plot_wf.setLabel('bottom', 'Sample')
        layout.addWidget(self.plot_wf)

        # Legend + color cycling
        self.legend = self.plot_wf.addLegend(offset=(10,10))
        color_cycle = [
            (0,114,189), (217,83,25), (237,177,32), (126,47,142),
            (119,172,48), (77,190,238), (162,20,47), (0,0,0)
        ]
        self.pens = [pg.mkPen(pg.mkColor(r, g, b), width=1.6) for (r,g,b) in color_cycle]
        # curves per channel
        self.curves = []
        for i, ch in enumerate(self.channels):
            pen = self.pens[i % len(self.pens)]
            c = self.plot_wf.plot(pen=pen, name=f"ch {ch}")
            self.curves.append(c)

        # FFT plot (first channel only)
        if args.enable_fft:
            self.plot_fft = pg.PlotWidget(title="FFT (averaged) — first channel")
            self.plot_fft.setLabel('left', 'Magnitude (dBFS)')
            self.plot_fft.setLabel('bottom', 'Frequency (Hz)')
            self.curve_fft = self.plot_fft.plot(pen='c')
            layout.addWidget(self.plot_fft)

        # Status line
        self.status = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status)

        # Shortcuts
        self._shortcut_autoscale = QtGui.QShortcut(QtGui.QKeySequence("A"), self)
        self._shortcut_autoscale.activated.connect(self._toggle_autoscale)

        self.resize(1100, 750)

    def _toggle_autoscale(self):
        self.autoscale = not self.autoscale
        if self.autoscale:
            self.plot_wf.enableAutoRange(axis='y')
        self.status.setText(f"Autoscale {'ON' if self.autoscale else 'OFF'}")

    # -------------------- Acquisition --------------------
    def update_once(self):
        # Build request payload
        try:
            payload = self.req.SerializeToString()
        except Exception as e:
            self.status.setText(f"[req build error] {e}")
            return

        # Send V2 request and get V2 reply
        try:
            send_env, rep_env, rtt_ms = self.link.request(
                pb_high.MT2_DUMP_SPYBUFFER_REQ,
                payload,
                route=self.route
            )
        except zmq.Again:
            self.status.setText("[timeout] No response")
            return
        except Exception as e:
            self.status.setText(f"[send/recv error] {e}")
            return

        # Validate type
        if rep_env.type != pb_high.MT2_DUMP_SPYBUFFER_RESP:
            self.status.setText(f"[unexpected V2 type {rep_env.type}]")
            return

        # Decode typed payload
        resp = pb_high.DumpSpyBuffersResponse()
        try:
            resp.ParseFromString(rep_env.payload)
        except Exception as e:
            self.status.setText(f"[parse resp] {e}")
            return

        if not resp.success:
            self.status.setText(f"[server] {resp.message}")
            return

        # ───── Unified parse: (W, K, N) int32 ─────
        try:
            y_all, meta = parse_dump_response(resp)   # y_all.shape == (W, K, N)
        except Exception as e:
            self.status.setText(f"[parse data] {e}")
            return

        # We request W=1 in this app; take the first waveform
        yk = y_all[0]  # shape (K, N), signed int32
        K, N = yk.shape

        # Plot each channel
        x = np.arange(N)
        for i, c in enumerate(self.curves):
            c.setData(x, yk[i])

        # Autoscale or manual y-range
        if self.autoscale:
            self.plot_wf.enableAutoRange(axis='y')
        else:
            ymin = float(yk.min()); ymax = float(yk.max())
            pad = max(50.0, 0.1 * max(1.0, ymax - ymin))
            self.plot_wf.setYRange(ymin - pad, ymax + pad, padding=0)

        ch_label = ",".join(str(c) for c in self.channels)
        self.status.setText(
            f"OK  ch=[{ch_label}]  N={N}  trig={'SW' if self.software_trigger else 'EXT'}  "
            f"RTT={rtt_ms:.2f} ms"
        )

        # Optional FFT (first channel only)
        if self.enable_fft:
            y = yk[0].astype(np.float64) * self._W
            Y = np.fft.rfft(y)
            mag = np.abs(Y) / (N / 2.0)
            self._fft_acc[self._fft_idx % self.avg_count, :] = mag
            self._fft_idx += 1

            acc_valid = self._fft_acc[:min(self._fft_idx, self.avg_count), :]
            Y_avg = acc_valid.mean(axis=0)
            Y_dbfs = 20.0 * np.log10(Y_avg / (2**14) + 1e-12)
            # skip the first few DC bins for a cleaner view
            k0 = 4 if self.f_axis.size > 4 else 0
            self.curve_fft.setData(self.f_axis[k0:], Y_dbfs[k0:])

# ────────────────────── main ──────────────────────
def _parse_channels(csv: str):
    chans = []
    for tok in csv.split(','):
        tok = tok.strip()
        if not tok:
            continue
        # allow ranges like 8-15
        if '-' in tok:
            a, b = tok.split('-', 1)
            a = int(a); b = int(b)
            if a > b: a, b = b, a
            chans.extend(range(a, b+1))
        else:
            chans.append(int(tok))
    # uniq + sorted
    return sorted(set(chans))

def main():
    p = argparse.ArgumentParser(description="DAPHNE Oscilloscope (EnvelopeV2) with multi-channel overlay.")
    p.add_argument("-ip", type=str, required=True, help="Server IP")
    p.add_argument("-port", type=int, default=9000, help="Server port (default 9000)")

    # Back-compat single channel
    p.add_argument("-channel", type=int, default=0, help="Single channel [0..39] (ignored if --channels is set)")

    # New: multi-channel CSV/range (e.g. --channels 0,8,16,24,32 or --channels 0-7)
    p.add_argument("--channels", type=str, default="", help="CSV/range of channels, e.g. '0,8,16' or '0-7'")

    p.add_argument("-L", type=int, required=True, help="Samples per waveform (<= 2048)")
    p.add_argument("-software_trigger", action="store_true", help="Use software trigger")

    p.add_argument("-enable_fft", action="store_true", help="Show averaged FFT plot (first channel)")
    p.add_argument("-fft_avg_waves", type=int, default=2000, help="Averages for FFT")
    p.add_argument("-fft_window_function", type=str, default="BLACKMAN-HARRIS",
                   choices=["NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"])

    p.add_argument("-period_ms", type=int, default=20, help="Update period (ms)")
    p.add_argument("-timeout_ms", type=int, default=1000, help="ZMQ recv/snd timeout (ms)")
    p.add_argument("-identity", type=str, default="osc-client", help="DEALER identity")
    p.add_argument("--route", type=str, default="mezz/0", help="Optional logical route to target")
    p.add_argument("--sampling_rate_hz", type=float, default=62.5e6, help="Sample rate used for FFT axis")
    args = p.parse_args()

    # Parse channels
    if args.channels:
        chs = _parse_channels(args.channels)
        if not chs:
            print("No valid channels parsed from --channels")
            return 2
        args.channels = chs
    else:
        args.channels = [args.channel]

    # Validate ranges the server enforces
    if any((c < 0 or c > 39) for c in args.channels):
        print("Channels must be in [0..39]")
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
