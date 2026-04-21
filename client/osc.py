#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import zmq

# Optional SciPy window functions (fallbacks provided)
try:
    from scipy import signal as _scipy_signal
except Exception:
    _scipy_signal = None

from PyQt6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

# Protobuf imports from repository tree
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high

# Shared waveform parser (same directory)
from led_charge import ChargeWindow, FixedWindowChargeMonitor, load_charge_windows
from waveparse import parse_dump_response


# ---------------------- Window functions ----------------------
def _ensure_scipy():
    if _scipy_signal is None:
        raise RuntimeError(
            "SciPy is required for BLACKMAN-HARRIS/TUKEY windows. "
            "Install with `pip install scipy` or choose HANNING/HAMMING/BLACKMAN/NONE."
        )


def get_window(name, n_samples):
    name = name.upper()
    if name == "NONE":
        return np.ones(n_samples, dtype=float)
    if name == "HANNING":
        return np.hanning(n_samples)
    if name == "HAMMING":
        return np.hamming(n_samples)
    if name == "BLACKMAN":
        return np.blackman(n_samples)
    if name == "BLACKMAN-HARRIS":
        _ensure_scipy()
        return _scipy_signal.windows.blackmanharris(n_samples)
    if name == "TUKEY":
        _ensure_scipy()
        return _scipy_signal.windows.tukey(n_samples, alpha=0.1)
    raise ValueError(f"Unknown window function: {name}")


# ---------------------- V2 request helper ----------------------
class V2Link:
    def __init__(self, endpoint, identity: bytes, timeout_ms: int):
        self.endpoint = endpoint
        self.timeout_ms = max(1, int(timeout_ms))

        self.ctx = zmq.Context.instance()
        self.s = self.ctx.socket(zmq.DEALER)
        self.s.setsockopt(zmq.IDENTITY, identity)
        self.s.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self.s.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        self.s.setsockopt(zmq.LINGER, 0)
        self.s.connect(endpoint)

        self._poller = zmq.Poller()
        self._poller.register(self.s, zmq.POLLIN)

        self._seq = 0
        self._rand = int(time.time_ns()) & 0xFFFFFFFF

    def close(self):
        try:
            self._poller.unregister(self.s)
        except Exception:
            pass
        try:
            self.s.close(0)
        except Exception:
            pass

    def _next_ids(self):
        self._seq += 1
        now = time.time_ns()
        task_id = (now << 16) ^ (os.getpid() << 8) ^ (self._rand & 0xFF)
        msg_id = (now << 1) ^ self._seq
        mask = (1 << 63) - 1
        return task_id & mask, msg_id & mask

    def request(self, mtype_req, payload_bytes: bytes, route: str | None = None, stop_checker=None):
        env = pb_high.ControlEnvelopeV2()
        env.version = 2
        env.dir = pb_high.DIR_REQUEST
        env.type = mtype_req
        env.payload = payload_bytes
        env.task_id, env.msg_id = self._next_ids()
        env.timestamp_ns = time.time_ns()
        if route:
            env.route = route

        t0 = time.time_ns()
        self.s.send(env.SerializeToString())

        deadline = time.monotonic() + (self.timeout_ms / 1000.0)
        while True:
            if stop_checker is not None and stop_checker():
                raise InterruptedError("Stop requested")

            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise zmq.Again("Timed out waiting for reply")

            wait_ms = min(50, max(1, int(remaining_s * 1000.0)))
            events = dict(self._poller.poll(wait_ms))
            if events.get(self.s, 0) & zmq.POLLIN:
                break

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


# ---------------------- Disk writer ----------------------
class WaveformDiskWriter(threading.Thread):
    def __init__(self, save_dir, channels, append_data=False, queue_frames=512, flush_every=128):
        super().__init__(daemon=True)
        self.save_dir = Path(save_dir)
        self.channels = list(channels)
        self.append_data = bool(append_data)
        self.flush_every = max(1, int(flush_every))

        self.queue = queue.Queue(maxsize=max(1, int(queue_frames)))
        self._sentinel = object()

        self._lock = threading.Lock()
        self._written_frames = 0
        self._bytes_written = 0
        self._error = ""
        self._ready_evt = threading.Event()

    def run(self):
        mode = "ab" if self.append_data else "wb"
        files = {}

        try:
            self.save_dir.mkdir(parents=True, exist_ok=True)
            for ch in self.channels:
                fp = self.save_dir / f"channel_{ch}.dat"
                files[ch] = open(fp, mode)
        except Exception as exc:
            with self._lock:
                self._error = f"writer init failed: {exc}"
            self._ready_evt.set()
            return

        self._ready_evt.set()
        try:
            while True:
                item = self.queue.get()
                try:
                    if item is self._sentinel:
                        break

                    yk = item
                    if yk.ndim != 2 or yk.shape[0] != len(self.channels):
                        raise ValueError(
                            f"Invalid frame shape {yk.shape}, expected ({len(self.channels)}, N)"
                        )

                    local_bytes = 0
                    for idx, ch in enumerate(self.channels):
                        out = yk[idx, :].astype(np.uint16, copy=False)
                        out.tofile(files[ch])
                        local_bytes += out.nbytes

                    with self._lock:
                        self._written_frames += 1
                        self._bytes_written += local_bytes
                        written = self._written_frames

                    if written % self.flush_every == 0:
                        for handle in files.values():
                            handle.flush()
                except Exception as exc:
                    with self._lock:
                        self._error = f"writer runtime failed: {exc}"
                    break
                finally:
                    self.queue.task_done()
        finally:
            for handle in files.values():
                try:
                    handle.flush()
                except Exception:
                    pass
                try:
                    handle.close()
                except Exception:
                    pass

    def stop(self, timeout_s=2.0):
        if not self.is_alive():
            return True

        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while time.monotonic() < deadline:
            try:
                self.queue.put(self._sentinel, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def wait_ready(self, timeout_s=2.0):
        return self._ready_evt.wait(timeout=max(0.0, float(timeout_s)))

    def snapshot(self):
        with self._lock:
            return {
                "written_frames": self._written_frames,
                "bytes_written": self._bytes_written,
                "error": self._error,
            }


# ---------------------- Acquisition worker ----------------------
class AcquisitionWorker(QtCore.QObject):
    status = QtCore.pyqtSignal(str)
    telemetry = QtCore.pyqtSignal(object)
    fft_update = QtCore.pyqtSignal(object, int)  # (dBFS spectrum, number of averaged waveforms)
    plot_update = QtCore.pyqtSignal(object, float, int, int)  # (yk, rtt_ms, frame_id, t_ns)
    acquisition_finished = QtCore.pyqtSignal(str)

    def __init__(
        self,
        endpoint,
        route,
        identity,
        timeout_ms,
        req,
        period_ms,
        max_waveforms=0,
        save_queue=None,
        save_health_checker=None,
        fft_config=None,
    ):
        super().__init__()
        self.endpoint = endpoint
        self.route = route
        self.identity = identity
        self.timeout_ms = max(1, int(timeout_ms))
        self.req = req
        self.period_ms = max(1, int(period_ms))
        self.max_waveforms = max(0, int(max_waveforms))

        self.save_queue = save_queue
        self.save_health_checker = save_health_checker
        self.fft_config = dict(fft_config or {})

        self._timer = None
        self._link = None
        self._busy = False
        self._stop_evt = threading.Event()

        self._frames_acquired = 0
        self._timeouts = 0
        self._save_backpressure = 0
        self._last_telemetry_emit_s = 0.0

        self._fft_enabled = bool(self.fft_config.get("enabled", False))
        self._fft_emit_every = max(1, int(self.fft_config.get("emit_every", 1)))
        self._fft_channel_index = int(self.fft_config.get("channel_index", 0))
        self._fft_remove_dc = bool(self.fft_config.get("remove_dc", True))
        self._fft_adc_full_scale = max(1.0, float(self.fft_config.get("adc_full_scale", 2**14)))
        self._fft_avg_count = max(1, int(self.fft_config.get("avg_waves", 1)))

        self._fft_window = None
        self._fft_window_power = 1.0
        self._fft_ring = None
        self._fft_sum = None
        self._fft_frames = 0

        self._setup_fft()

    def _finish_acquisition(self, message):
        self.status.emit(message)
        self._emit_telemetry(force=True)
        self._stop_evt.set()
        if self._timer is not None:
            self._timer.stop()
        self.acquisition_finished.emit(message)

    def _setup_fft(self):
        if not self._fft_enabled:
            return

        n_samples = int(getattr(self.req, "numberOfSamples", 0))
        if n_samples <= 0:
            self._fft_enabled = False
            return

        window = self.fft_config.get("window", None)
        if window is None:
            self._fft_enabled = False
            return

        window = np.asarray(window, dtype=np.float64)
        if window.ndim != 1 or window.size != n_samples:
            self._fft_enabled = False
            return

        n_bins = (n_samples // 2) + 1
        self._fft_window = window.copy()
        self._fft_window_power = max(1.0, float(np.sum(self._fft_window * self._fft_window)))
        self._fft_ring = np.zeros((self._fft_avg_count, n_bins), dtype=np.float64)
        self._fft_sum = np.zeros(n_bins, dtype=np.float64)

    def _update_fft(self, yk):
        if not self._fft_enabled:
            return
        if self._fft_channel_index < 0 or self._fft_channel_index >= yk.shape[0]:
            return

        y = yk[self._fft_channel_index].astype(np.float64, copy=False)
        if self._fft_remove_dc:
            y = y - y.mean()

        y_windowed = y * self._fft_window
        y_fft = np.fft.rfft(y_windowed)
        power = ((y_fft.real * y_fft.real) + (y_fft.imag * y_fft.imag)) / self._fft_window_power

        slot = self._fft_frames % self._fft_avg_count
        if self._fft_frames >= self._fft_avg_count:
            self._fft_sum -= self._fft_ring[slot]

        self._fft_ring[slot, :] = power
        self._fft_sum += power
        self._fft_frames += 1

        if (self._fft_frames % self._fft_emit_every) != 0:
            return

        navg = self._fft_avg_count if self._fft_frames >= self._fft_avg_count else self._fft_frames
        if navg <= 0:
            return

        mean_power = self._fft_sum / float(navg)
        y_dbfs = 10.0 * np.log10((mean_power / (self._fft_adc_full_scale * self._fft_adc_full_scale)) + 1e-24)
        self.fft_update.emit(y_dbfs, int(navg))

    def request_stop(self):
        self._stop_evt.set()

    @QtCore.pyqtSlot()
    def start(self):
        self._stop_evt.clear()

        self._timer = QtCore.QTimer()
        self._timer.setInterval(self.period_ms)
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._poll_once)
        self._timer.start()

    @QtCore.pyqtSlot()
    def stop(self):
        self._stop_evt.set()

        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

        self._close_link()

    def _close_link(self):
        if self._link is not None:
            try:
                self._link.close()
            except Exception:
                pass
            self._link = None

    def _ensure_link(self):
        if self._link is not None:
            return
        self._link = V2Link(self.endpoint, self.identity.encode(), self.timeout_ms)
        self.status.emit(f"Connected to {self.endpoint}")

    def _push_save_frame(self, yk):
        if self.save_queue is None:
            return

        frame_copy = yk.copy()
        while not self._stop_evt.is_set():
            try:
                self.save_queue.put(frame_copy, timeout=0.05)
                return
            except queue.Full:
                if self.save_health_checker is not None:
                    writer_error = self.save_health_checker()
                    if writer_error:
                        self.status.emit(f"[writer disabled] {writer_error}")
                        self.save_queue = None
                        return
                self._save_backpressure += 1
                if self._save_backpressure % 20 == 0:
                    self.status.emit("[writer backlog] waiting for disk queue")

    def _emit_telemetry(self, force=False):
        now_s = time.monotonic()
        if (not force) and (now_s - self._last_telemetry_emit_s < 0.5):
            return

        self.telemetry.emit(
            {
                "frames_acquired": self._frames_acquired,
                "timeouts": self._timeouts,
                "save_backpressure": self._save_backpressure,
            }
        )
        self._last_telemetry_emit_s = now_s

    def _poll_once(self):
        if self._busy or self._stop_evt.is_set():
            return
        self._busy = True

        try:
            self._ensure_link()

            payload = self.req.SerializeToString()
            _, rep_env, rtt_ms = self._link.request(
                pb_high.MT2_DUMP_SPYBUFFER_REQ,
                payload,
                route=self.route,
                stop_checker=self._stop_evt.is_set,
            )

            if rep_env.type != pb_high.MT2_DUMP_SPYBUFFER_RESP:
                raise RuntimeError(f"Unexpected V2 type {rep_env.type}")

            resp = pb_high.DumpSpyBuffersResponse()
            resp.ParseFromString(rep_env.payload)

            if not resp.success:
                self.status.emit(f"[server] {resp.message}")
                return

            y_all, _meta = parse_dump_response(resp)
            yk = np.ascontiguousarray(y_all[0])

            self._frames_acquired += 1
            self._update_fft(yk)
            self.plot_update.emit(yk, float(rtt_ms), int(self._frames_acquired), time.time_ns())
            self._push_save_frame(yk)
            if self.max_waveforms > 0 and self._frames_acquired >= self.max_waveforms:
                self._finish_acquisition(f"[done] acquired {self._frames_acquired} waveforms")
                return

        except InterruptedError:
            pass
        except zmq.Again:
            self._timeouts += 1
            self.status.emit("[timeout] No response")
            self._close_link()
        except Exception as exc:
            self.status.emit(f"[acquisition error] {exc}")
            self._close_link()
        finally:
            self._emit_telemetry(force=False)
            self._busy = False


# ---------------------- Main UI app ----------------------
class DaphneOscApp(QtWidgets.QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args

        self.endpoint = f"tcp://{args.ip}:{args.port}"
        self.channels = args.channels if args.channels else [args.channel]
        self.n_samples = args.L
        self.software_trigger = args.software_trigger
        self.timeout_ms = args.timeout_ms
        self.fs_hz = args.sampling_rate_hz
        self.route = args.route
        self.fft_every = max(1, int(args.fft_every))
        self.autoscale = bool(args.autoscale)
        self.enable_fft = bool(args.enable_fft)
        self.fft_channel = int(args.fft_channel) if args.fft_channel is not None else int(self.channels[0])
        self.fft_channel_index = self.channels.index(self.fft_channel) if self.enable_fft else 0
        self.enable_charge_hist = bool(args.enable_charge_hist)
        # Default to log-frequency FFT axis; allow explicit linear override.
        self.fft_log_x = bool(self.enable_fft and not getattr(args, "fft_linear_x", False))
        self._fft_samples_averaged = 0

        self._x_axis = np.arange(self.n_samples)
        self._latest_worker_msg = "Ready"
        self._last_rtt_ms = 0.0
        self._frames_rendered = 0
        self._last_render_ns = 0
        self._last_render_error = ""
        self._telemetry = {
            "frames_acquired": 0,
            "timeouts": 0,
            "plot_drops": 0,
            "save_backpressure": 0,
        }
        self._plot_drops_ui = 0
        self._latest_plot_packet = None
        self._last_seen_frame_id = 0
        self._last_rendered_frame_id = 0
        self._latest_charge_info = None
        self.charge_monitor = None

        self.writer = None
        self.save_queue = None
        if args.save_dir:
            self.writer = WaveformDiskWriter(
                save_dir=args.save_dir,
                channels=self.channels,
                append_data=args.append_data,
                queue_frames=args.save_queue_frames,
                flush_every=args.flush_every_frames,
            )
            self.writer.start()
            self.writer.wait_ready(timeout_s=2.0)
            writer_init_error = self.writer.snapshot()["error"]
            if writer_init_error:
                self._latest_worker_msg = f"[writer disabled] {writer_init_error}"
                self.writer = None
            else:
                self.save_queue = self.writer.queue
                self._write_run_metadata(args)

        self.req = pb_high.DumpSpyBuffersRequest()
        self.req.channelList.extend(self.channels)
        self.req.numberOfWaveforms = 1
        self.req.numberOfSamples = self.n_samples
        self.req.softwareTrigger = self.software_trigger

        self.f_axis = None
        self._fft_pos_mask = None
        self._win = None
        self.avg_count = 1
        if self.enable_fft:
            self.f_axis = np.fft.rfftfreq(self.n_samples, d=1.0 / self.fs_hz)
            self._fft_pos_mask = np.isfinite(self.f_axis) & (self.f_axis > 0.0)
            self._win = get_window(args.fft_window_function, self.n_samples).astype(np.float64)
            self.avg_count = max(1, int(args.fft_avg_waves))
        if self.enable_charge_hist:
            self.charge_monitor = FixedWindowChargeMonitor(
                channels=self.channels,
                n_samples=self.n_samples,
                windows=self._build_charge_windows(args),
                history=args.charge_history,
                hist_bins=args.charge_hist_bins,
                clip_negative=args.charge_clip_negative,
            )

        self._build_ui(args)

        self.worker_thread = QtCore.QThread(self)
        self.worker = AcquisitionWorker(
            endpoint=self.endpoint,
            route=self.route,
            identity=args.identity,
            timeout_ms=self.timeout_ms,
            req=self.req,
            period_ms=args.period_ms,
            max_waveforms=args.max_waveforms,
            save_queue=self.save_queue,
            save_health_checker=self._writer_error_text,
            fft_config={
                "enabled": self.enable_fft,
                "channel_index": self.fft_channel_index,
                "window": self._win,
                "avg_waves": self.avg_count,
                "emit_every": self.fft_every,
                "adc_full_scale": args.fft_full_scale_counts,
                "remove_dc": not args.fft_keep_dc,
            },
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker.status.connect(self._on_worker_status)
        self.worker.telemetry.connect(self._on_worker_telemetry)
        self.worker.fft_update.connect(self._on_fft_update)
        self.worker.plot_update.connect(self._on_plot_update)
        self.worker.acquisition_finished.connect(self._on_acquisition_finished)

        self.worker_thread.started.connect(self.worker.start)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        QtWidgets.QApplication.instance().aboutToQuit.connect(self._cleanup)
        self.worker_thread.start()

        self.render_timer = QtCore.QTimer(self)
        self.render_timer.setInterval(max(5, int(args.ui_period_ms)))
        self.render_timer.timeout.connect(self._render_latest_frame)
        self.render_timer.start()

        self._cleaned = False

    def _write_run_metadata(self, args):
        payload = {
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "endpoint": self.endpoint,
            "route": self.route,
            "channels": self.channels,
            "samples_per_waveform": self.n_samples,
            "software_trigger": bool(self.software_trigger),
            "acq_period_ms": int(args.period_ms),
            "max_waveforms": int(args.max_waveforms),
            "ui_period_ms": int(args.ui_period_ms),
            "fft_every": int(args.fft_every),
            "autoscale": bool(args.autoscale),
            "fft_enabled": bool(args.enable_fft),
            "fft_channel": int(self.fft_channel) if args.enable_fft else None,
            "fft_keep_dc": bool(args.fft_keep_dc),
            "fft_log_x": bool(self.fft_log_x) if args.enable_fft else False,
            "fft_full_scale_counts": float(args.fft_full_scale_counts),
            "fft_window_function": args.fft_window_function,
            "sampling_rate_hz": float(self.fs_hz),
            "charge_hist_enabled": bool(args.enable_charge_hist),
        }
        if args.enable_charge_hist:
            payload["charge_windows_json"] = str(args.charge_windows_json) if args.charge_windows_json else ""
            payload["charge_start"] = int(args.charge_start)
            payload["charge_stop"] = int(args.charge_stop)
            payload["charge_baseline_start"] = int(args.charge_baseline_start)
            payload["charge_baseline_stop"] = int(args.charge_baseline_stop)
            payload["charge_hist_bins"] = int(args.charge_hist_bins)
            payload["charge_history"] = int(args.charge_history)
            payload["charge_clip_negative"] = bool(args.charge_clip_negative)
        if getattr(args, "run_label", ""):
            payload["run_label"] = str(args.run_label)
        if getattr(args, "run_notes", ""):
            payload["run_notes"] = str(args.run_notes)
        save_dir = Path(args.save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        with open(save_dir / "run_metadata.json", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)

    def _build_ui(self, args):
        ch_label = ",".join(str(c) for c in self.channels)
        self.setWindowTitle(f"DAPHNE Oscilloscope ch[{ch_label}] @ {self.endpoint}")

        layout = QtWidgets.QVBoxLayout(self)

        self.plot_wf = pg.PlotWidget(title=f"Waveforms (ch {ch_label})")
        self.plot_wf.setLabel("left", "ADC counts")
        self.plot_wf.setLabel("bottom", "Sample")
        wf_item = self.plot_wf.getPlotItem()
        wf_item.setClipToView(False)
        wf_item.setDownsampling(auto=False)
        wf_item.enableAutoRange(axis="y", enable=False)
        self.plot_wf.setXRange(0, self.n_samples - 1, padding=0)
        layout.addWidget(self.plot_wf)

        self.legend = self.plot_wf.addLegend(offset=(10, 10))
        color_cycle = [
            (0, 114, 189),
            (217, 83, 25),
            (237, 177, 32),
            (126, 47, 142),
            (119, 172, 48),
            (77, 190, 238),
            (162, 20, 47),
            (0, 0, 0),
        ]
        pens = [pg.mkPen(pg.mkColor(r, g, b), width=1.6) for (r, g, b) in color_cycle]

        self.curves = []
        for i, ch in enumerate(self.channels):
            c = self.plot_wf.plot(pen=pens[i % len(pens)], name=f"ch {ch}")
            self.curves.append(c)

        if self.enable_charge_hist:
            self.plot_charge = pg.PlotWidget(title="Charge Histogram")
            self.plot_charge.setLabel("left", "Counts")
            self.plot_charge.setLabel("bottom", "Integrated charge (ADC x sample)")
            charge_item = self.plot_charge.getPlotItem()
            charge_item.setClipToView(False)
            charge_item.setDownsampling(auto=False)
            self.plot_charge.addLegend(offset=(10, 10))
            self.charge_curves = []
            for i, ch in enumerate(self.channels):
                c = self.plot_charge.plot(
                    pen=pens[i % len(pens)],
                    name=f"ch {ch}",
                    stepMode="center",
                    connect="finite",
                )
                self.charge_curves.append(c)
            layout.addWidget(self.plot_charge)

        if args.enable_fft:
            self.plot_fft = pg.PlotWidget(title=f"FFT (averaged power) - ch {self.fft_channel}")
            self.plot_fft.setLabel("left", "Magnitude (dBFS)")
            self.plot_fft.setLabel("bottom", "Frequency (Hz" + (", log)" if self.fft_log_x else ")"))
            fft_item = self.plot_fft.getPlotItem()
            fft_item.setClipToView(False)
            fft_item.setDownsampling(auto=False)
            try:
                fft_item.setLogMode(x=self.fft_log_x, y=False)
            except Exception:
                # Keep running in linear mode if log mode isn't supported.
                self.fft_log_x = False
                self.plot_fft.setLabel("bottom", "Frequency (Hz)")
            self.curve_fft = self.plot_fft.plot(pen="c")
            layout.addWidget(self.plot_fft)

        self.status = QtWidgets.QLabel("Ready")
        layout.addWidget(self.status)

        self._shortcut_autoscale = QtGui.QShortcut(QtGui.QKeySequence("A"), self)
        self._shortcut_autoscale.activated.connect(self._toggle_autoscale)

        if not self.autoscale:
            self.plot_wf.setYRange(-32768, 32767, padding=0)

        self.resize(1180, 760)

    @QtCore.pyqtSlot(str)
    def _on_worker_status(self, msg):
        self._latest_worker_msg = msg
        self._refresh_status_line()

    @QtCore.pyqtSlot(object)
    def _on_worker_telemetry(self, telemetry):
        self._telemetry = telemetry
        self._refresh_status_line()

    @QtCore.pyqtSlot(object, float, int, int)
    def _on_plot_update(self, yk, rtt_ms, frame_id, timestamp_ns):
        if frame_id > (self._last_seen_frame_id + 1):
            self._plot_drops_ui += (frame_id - self._last_seen_frame_id - 1)
        self._last_seen_frame_id = frame_id
        if self.charge_monitor is not None:
            try:
                self._latest_charge_info = self.charge_monitor.update(yk)
            except Exception as exc:
                self._latest_worker_msg = f"[charge error] {exc}"
        self._latest_plot_packet = (frame_id, yk, rtt_ms, timestamp_ns)

    @QtCore.pyqtSlot(object, int)
    def _on_fft_update(self, y_dbfs, navg):
        if not self.enable_fft:
            return
        if self.f_axis is None:
            return

        k0 = 4 if self.f_axis.size > 4 else 0
        if self.fft_log_x:
            # Log-x cannot include DC/non-positive frequency bins.
            k0 = max(k0, 1)

        x = self.f_axis[k0:]
        y = y_dbfs[k0:]

        if self.fft_log_x:
            pos_mask = self._fft_pos_mask[k0:] if self._fft_pos_mask is not None else (x > 0.0)
            good = np.isfinite(x) & np.isfinite(y) & pos_mask
            x = x[good]
            y = y[good]
            if x.size == 0:
                self._latest_worker_msg = "[fft] no positive finite bins for log-x"
                self._refresh_status_line()
                return

        self.curve_fft.setData(x, y, connect="finite")
        self._fft_samples_averaged = int(navg)
        self._refresh_status_line()

    def _writer_error_text(self):
        if self.writer is None:
            return ""
        return self.writer.snapshot().get("error", "")

    @QtCore.pyqtSlot(str)
    def _on_acquisition_finished(self, msg):
        self._latest_worker_msg = msg
        self._refresh_status_line()
        QtCore.QTimer.singleShot(100, QtWidgets.QApplication.instance().quit)

    def _toggle_autoscale(self):
        self.autoscale = not self.autoscale
        self._refresh_status_line(extra=f"Autoscale {'ON' if self.autoscale else 'OFF'}")

    def _render_latest_frame(self):
        try:
            latest = self._latest_plot_packet
            if latest is None:
                return

            frame_id, yk, rtt_ms, _timestamp_ns = latest
            if frame_id == self._last_rendered_frame_id:
                return

            self._last_rtt_ms = float(rtt_ms)

            n_channels, n_samples = yk.shape
            if n_channels != len(self.curves) or n_samples != self.n_samples:
                self._latest_worker_msg = (
                    f"[shape mismatch] got {yk.shape}, expected ({len(self.curves)}, {self.n_samples})"
                )
                self._refresh_status_line()
                return

            for i, curve in enumerate(self.curves):
                curve.setData(self._x_axis, yk[i], connect="finite")

            if self.charge_monitor is not None:
                series = self.charge_monitor.histogram_series()
                for i, ch in enumerate(self.channels):
                    if ch in series:
                        self.charge_curves[i].setData(series[ch]["centers"], series[ch]["counts"], connect="finite")
                    else:
                        self.charge_curves[i].clear()

            if self.autoscale:
                y_min = float(yk.min())
                y_max = float(yk.max())
                pad = max(50.0, 0.1 * max(1.0, y_max - y_min))
                self.plot_wf.setYRange(y_min - pad, y_max + pad, padding=0)

            self._frames_rendered += 1
            self._last_rendered_frame_id = frame_id
            self._last_render_ns = time.time_ns()
            self._last_render_error = ""
            self._refresh_status_line()
        except Exception as exc:
            self._last_render_error = str(exc)
            self._latest_worker_msg = f"[render error] {exc}"
            self._refresh_status_line()

    def _refresh_status_line(self, extra=""):
        writer_frames = 0
        writer_queue = 0
        writer_error = ""

        if self.writer is not None:
            snap = self.writer.snapshot()
            writer_frames = snap["written_frames"]
            writer_error = snap["error"]
            writer_queue = self.writer.queue.qsize()

        render_age_ms = -1.0
        if self._last_render_ns > 0:
            render_age_ms = (time.time_ns() - self._last_render_ns) / 1e6

        ch_label = ",".join(str(c) for c in self.channels)
        status_text = (
            f"{self._latest_worker_msg} | ch=[{ch_label}] N={self.n_samples} "
            f"trig={'SW' if self.software_trigger else 'EXT'} RTT={self._last_rtt_ms:.2f}ms "
            f"acq={self._telemetry.get('frames_acquired', 0)} "
            f"saved={writer_frames} saveQ={writer_queue} "
            f"dropPlot={self._plot_drops_ui} "
            f"timeouts={self._telemetry.get('timeouts', 0)} "
            f"rendered={self._frames_rendered} renderAgeMs={render_age_ms:.0f}"
        )
        if self.enable_fft:
            status_text += f" fftCh={self.fft_channel} fftAvg={self._fft_samples_averaged}"
            status_text += f" fftX={'log' if self.fft_log_x else 'lin'}"
        if self.enable_charge_hist and self._latest_charge_info:
            ch0 = int(self.channels[0])
            latest_charge = self._latest_charge_info.get("latest_charge", {}).get(ch0)
            win0 = self._latest_charge_info.get("windows", {}).get(ch0, {})
            if latest_charge is not None:
                status_text += f" qCh={ch0} q={latest_charge:.1f}"
            if win0:
                status_text += f" qWin={win0.get('integrate_start', '?')}:{win0.get('integrate_stop', '?')}"

        if writer_error:
            status_text += f" writerError={writer_error}"
        if self._last_render_error:
            status_text += f" renderError={self._last_render_error}"
        if extra:
            status_text += f" | {extra}"

        self.status.setText(status_text)

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True

        if hasattr(self, "render_timer") and self.render_timer is not None:
            self.render_timer.stop()

        if getattr(self, "worker", None) is not None:
            self.worker.request_stop()
            QtCore.QMetaObject.invokeMethod(
                self.worker,
                "stop",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

        if getattr(self, "worker_thread", None) is not None:
            self.worker_thread.quit()
            self.worker_thread.wait(3000)

        if self.writer is not None:
            self.writer.stop(timeout_s=2.0)
            self.writer.join(timeout=5.0)

    def _build_charge_windows(self, args):
        if args.charge_windows_json:
            windows = load_charge_windows(args.charge_windows_json)
            missing = [ch for ch in self.channels if ch not in windows]
            if missing:
                raise ValueError(f"Missing charge windows for channels {missing} in {args.charge_windows_json}")
            return {ch: windows[ch] for ch in self.channels}

        start = int(args.charge_start)
        stop = int(args.charge_stop)
        if stop <= start:
            raise ValueError("charge_stop must be greater than charge_start")

        out = {}
        for ch in self.channels:
            out[ch] = ChargeWindow(
                channel=int(ch),
                baseline_start=int(args.charge_baseline_start),
                baseline_stop=int(args.charge_baseline_stop),
                search_start=start,
                search_stop=stop,
                onset_index=start,
                peak_index=start,
                integrate_start=start,
                integrate_stop=stop,
            )
        return out


# ---------------------- CLI + main ----------------------
def _parse_channels(csv):
    channels = []
    for token in csv.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a_str, b_str = token.split("-", 1)
            a = int(a_str)
            b = int(b_str)
            if a > b:
                a, b = b, a
            channels.extend(range(a, b + 1))
        else:
            channels.append(int(token))
    return sorted(set(channels))


def main():
    parser = argparse.ArgumentParser(
        description="DAPHNE Oscilloscope (EnvelopeV2), multi-channel overlay, live FFT, optional on-disk recording."
    )
    parser.add_argument("-ip", type=str, default="127.0.0.1", help="Server IP (default 127.0.0.1)")
    parser.add_argument("-port", type=int, default=9876, help="Server port (default 9876)")

    # Back-compat single channel
    parser.add_argument("-channel", type=int, default=0, help="Single channel [0..39] (ignored if --channels is set)")

    # New multi-channel CSV/range (e.g. --channels 0,8,16,24,32 or --channels 0-7)
    parser.add_argument("--channels", type=str, default="", help="CSV/range of channels, e.g. '0,8,16' or '0-7'")

    parser.add_argument("-L", type=int, required=True, help="Samples per waveform (<= 2048)")
    parser.add_argument("-software_trigger", action="store_true", help="Use software trigger")

    parser.add_argument("-enable_fft", action="store_true", help="Show statistically averaged FFT plot")
    parser.add_argument("-fft_avg_waves", type=int, default=2000, help="Averages for FFT")
    parser.add_argument(
        "-fft_window_function",
        type=str,
        default="BLACKMAN-HARRIS",
        choices=["NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"],
    )
    parser.add_argument("--fft_channel", type=int, default=None, help="Channel ID used for FFT (must be in --channels)")
    parser.add_argument("--fft_full_scale_counts", type=float, default=float(2**14), help="Full-scale ADC counts for dBFS conversion")
    parser.add_argument("--fft_keep_dc", action="store_true", help="Keep DC component (default removes DC before FFT)")
    parser.add_argument("--fft_linear_x", action="store_true", help="Use linear x-axis for FFT (default is logarithmic)")

    parser.add_argument("-period_ms", type=int, default=20, help="Acquisition period (ms)")
    parser.add_argument("--max_waveforms", type=int, default=0, help="Stop automatically after this many acquired waveforms (0 = run forever)")
    parser.add_argument("--ui_period_ms", type=int, default=33, help="UI redraw period (ms)")
    parser.add_argument("--fft_every", type=int, default=2, help="Publish FFT update every N acquired waveforms")
    parser.add_argument("--autoscale", action="store_true", help="Continuously autoscale waveform Y range")
    parser.add_argument("-timeout_ms", type=int, default=1000, help="ZMQ recv/snd timeout (ms)")
    parser.add_argument("-identity", type=str, default="osc-client", help="DEALER identity")
    parser.add_argument("--route", type=str, default="mezz/0", help="Optional logical route target")
    parser.add_argument("--sampling_rate_hz", type=float, default=62.5e6, help="Sample rate used for FFT axis")
    parser.add_argument("--enable_charge_hist", action="store_true", help="Show live fixed-window charge histogram")
    parser.add_argument("--charge_windows_json", type=str, default="", help="Per-channel charge windows JSON from a bright LED calibration run")
    parser.add_argument("--charge_start", type=int, default=124, help="Manual charge integration start sample if no JSON is provided")
    parser.add_argument("--charge_stop", type=int, default=148, help="Manual charge integration stop sample if no JSON is provided")
    parser.add_argument("--charge_baseline_start", type=int, default=0, help="Charge baseline window start sample")
    parser.add_argument("--charge_baseline_stop", type=int, default=100, help="Charge baseline window stop sample")
    parser.add_argument("--charge_hist_bins", type=int, default=120, help="Histogram bins for the live charge plot")
    parser.add_argument("--charge_history", type=int, default=2000, help="Number of recent charges kept per channel")
    parser.add_argument("--charge_clip_negative", action="store_true", help="Clip negative baseline-subtracted samples before integration")

    parser.add_argument(
        "--save_dir",
        type=str,
        default="",
        help="If set, continuously save incoming waveforms into channel_<id>.dat in this folder",
    )
    parser.add_argument("--run_label", type=str, default="", help="Human-readable run label stored in run_metadata.json")
    parser.add_argument("--run_notes", type=str, default="", help="Human-readable run notes stored in run_metadata.json")
    parser.add_argument("--append_data", action="store_true", help="Append to existing channel_<id>.dat files")
    parser.add_argument("--save_queue_frames", type=int, default=512, help="Max buffered frames waiting for disk write")
    parser.add_argument("--flush_every_frames", type=int, default=128, help="Flush files every N frames")

    args = parser.parse_args()

    # Parse channels
    if args.channels:
        channels = _parse_channels(args.channels)
        if not channels:
            print("No valid channels parsed from --channels")
            return 2
        args.channels = channels
    else:
        args.channels = [args.channel]

    if any((ch < 0 or ch > 39) for ch in args.channels):
        print("Channels must be in [0..39]")
        return 2

    if not (1 <= args.L <= 2048):
        print("L must be in [1..2048]")
        return 2

    if args.ui_period_ms < 1:
        print("ui_period_ms must be >= 1")
        return 2
    if args.max_waveforms < 0:
        print("max_waveforms must be >= 0")
        return 2
    if args.fft_every < 1:
        print("fft_every must be >= 1")
        return 2
    if args.fft_full_scale_counts <= 0:
        print("fft_full_scale_counts must be > 0")
        return 2

    if args.enable_fft:
        if args.fft_channel is None:
            args.fft_channel = args.channels[0]
        if args.fft_channel not in args.channels:
            print("fft_channel must be included in --channels")
            return 2
    if args.enable_charge_hist:
        if args.charge_baseline_stop <= args.charge_baseline_start:
            print("charge_baseline_stop must be greater than charge_baseline_start")
            return 2
        if (not args.charge_windows_json) and args.charge_stop <= args.charge_start:
            print("charge_stop must be greater than charge_start")
            return 2

    app = QtWidgets.QApplication([])
    pg.setConfigOptions(antialias=False)

    window = DaphneOscApp(args)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
