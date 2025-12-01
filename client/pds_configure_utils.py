#!/usr/bin/env python3
"""
Utility helpers to turn PDS configuration JSON blobs into ConfigureRequest
messages and send them via the EnvelopeV2 transport.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import zmq

from configure_fe_min_v2 import (  # type: ignore
    build_configure_v2_envelope,
    make_default_config,
    ns_to_iso,
    print_envelope,
    summarize_configure_response,
)
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high


# --------------------------------------------------------------------------- #
# Small helpers                                                               #
# --------------------------------------------------------------------------- #


def bitmask(indices: list[int] | tuple[int, ...]) -> int:
    """Return bitmask with bits set for each index in *indices*."""
    mask = 0
    for idx in indices:
        mask |= 1 << int(idx)
    return mask


def assemble_tp_conf(trigger: dict[str, Any]) -> int:
    """
    Re-implemented locally to avoid depending on pds.utils.
    Encodes the trigger parameters into a single register value.
    """
    filter_modes = {"compensated": 0, "inverted": 1, "xcorr": 2, "raw": 3}
    filter_mode = filter_modes.get(trigger.get("filter_mode", "inverted"), 1)
    slope_mode = 0 if str(trigger.get("slope_mode", "16")) == "16" else 1
    slope_threshold = trigger.get("slope_threshold", 12)
    pedestal_length = trigger.get("pedestal_length", 64)
    spybuffer_channel = trigger.get("spybuffer_channel", 63)

    pedestal_code = max(0, min(31, pedestal_length // 8))
    spy_code = max(0, min(63, spybuffer_channel))

    return (
        (filter_mode & 0x3)
        | ((slope_mode & 0x1) << 8)
        | ((slope_threshold & 0x7F) << 9)
        | ((pedestal_code & 0x1F) << 16)
        | ((spy_code & 0x3F) << 21)
    )


def compute_self_trigger_xcorr(xcorr_conf: dict[str, Any]) -> int:
    corr = xcorr_conf.get("correlation_threshold", 0)
    disc = xcorr_conf.get("discrimination_threshold", 0)
    return ((disc & 0x3FFF) << 28) | (corr & 0x0FFFFFFF)


def load_seed_from_detail(detail_path: Path, config_name: str) -> Dict[str, Any]:
    """
    Convert a detail JSON file into a seed-style configuration dictionary
    using pds.core.seed.generate_configuration.
    """
    pds_src = Path(__file__).resolve().parents[2] / "pds" / "src"
    if str(pds_src) not in sys.path:
        sys.path.append(str(pds_src))

    try:
        from pds.core.seed import generate_configuration  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Unable to import pds.core.seed from {pds_src}. "
            "Make sure the pds repo is present."
        ) from exc

    with open(detail_path, "r", encoding="utf-8") as fh:
        detail_data = json.load(fh)

    return generate_configuration(detail_data, config_name)


def load_seed_from_output(output_path: Path) -> Dict[str, Any]:
    """Load a pre-generated seed/output JSON file."""
    with open(output_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _ensure_channel(cfg: pb_high.ConfigureRequest, ch_id: int):
    for ch in cfg.channels:
        if ch.id == ch_id:
            return ch
    ch = cfg.channels.add()
    ch.id = ch_id
    return ch


def _ensure_afe(cfg: pb_high.ConfigureRequest, afe_id: int):
    for afe in cfg.afes:
        if afe.id == afe_id:
            return afe
    afe = cfg.afes.add()
    afe.id = afe_id
    return afe


def _maybe_get(values: list[Any] | None, idx: int, default: Any = None) -> Any:
    try:
        return values[idx] if values is not None else default
    except IndexError:
        return default


def build_request_from_seed(
    seed_cfg: Dict[str, Any],
    defaults_cfg: pb_high.ConfigureRequest,
    *,
    prefer_seed_common: bool = True,
) -> pb_high.ConfigureRequest:
    """
    Overlay a seed-style configuration (as produced by pds-run seed) on top of
    a default ConfigureRequest.
    """
    cfg = pb_high.ConfigureRequest()
    cfg.CopyFrom(defaults_cfg)

    cfg.slot = seed_cfg.get("slot_id", cfg.slot)
    cfg.biasctrl = seed_cfg.get("bias_ctrl", cfg.biasctrl)
    cfg.self_trigger_threshold = seed_cfg.get("self_trigger_threshold", cfg.self_trigger_threshold)
    cfg.self_trigger_xcorr = seed_cfg.get("self_trigger_xcorr", cfg.self_trigger_xcorr)
    cfg.tp_conf = seed_cfg.get("tp_conf", cfg.tp_conf)
    cfg.compensator = seed_cfg.get("compensator", cfg.compensator)
    cfg.inverters = seed_cfg.get("inverter", seed_cfg.get("inverters", cfg.inverters))

    cfg.full_stream_channels[:] = []
    cfg.full_stream_channels.extend(seed_cfg.get("full_stream_channels", []))

    chan_cfg = seed_cfg.get("channel_analog_conf", {})
    ch_ids = chan_cfg.get("ids", [])
    offsets = chan_cfg.get("offsets", [])
    trims = chan_cfg.get("trims", [])
    gains = chan_cfg.get("gains", [])

    for idx, ch_id in enumerate(ch_ids):
        ch = _ensure_channel(cfg, int(ch_id))
        ch.offset = _maybe_get(offsets, idx, ch.offset)
        ch.trim = _maybe_get(trims, idx, ch.trim)
        ch.gain = _maybe_get(gains, idx, ch.gain)

    afes = seed_cfg.get("afes", {})
    afe_ids = afes.get("ids", [])
    attenuators = afes.get("attenuators", [])
    v_biases = afes.get("v_biases", [])
    adcs = afes.get("adcs", {})
    pgas = afes.get("pgas", {})
    lnas = afes.get("lnas", {})

    adc_res = adcs.get("resolution")
    adc_fmt = adcs.get("output_format")
    adc_sb = adcs.get("SB_first") or adcs.get("sb_first")

    pga_cut = pgas.get("lpf_cut_frequency")
    pga_int = pgas.get("integrator_disable")
    pga_gain = pgas.get("gain")

    lna_clamp = lnas.get("clamp")
    lna_gain = lnas.get("gain")
    lna_int = lnas.get("integrator_disable")

    for idx, afe_id in enumerate(afe_ids):
        afe = _ensure_afe(cfg, int(afe_id))
        afe.attenuators = _maybe_get(attenuators, idx, afe.attenuators)
        afe.v_bias = _maybe_get(v_biases, idx, afe.v_bias)

        if prefer_seed_common:
            if adc_res is not None:
                afe.adc.resolution = bool(_maybe_get(adc_res, idx, afe.adc.resolution))
            if adc_fmt is not None:
                afe.adc.output_format = bool(_maybe_get(adc_fmt, idx, afe.adc.output_format))
            if adc_sb is not None:
                afe.adc.sb_first = bool(_maybe_get(adc_sb, idx, getattr(afe.adc, "sb_first", True)))
            if pga_cut is not None:
                afe.pga.lpf_cut_frequency = _maybe_get(pga_cut, idx, afe.pga.lpf_cut_frequency)
            if pga_int is not None:
                afe.pga.integrator_disable = bool(_maybe_get(pga_int, idx, afe.pga.integrator_disable))
            if pga_gain is not None:
                afe.pga.gain = bool(_maybe_get(pga_gain, idx, afe.pga.gain))
            if lna_clamp is not None:
                afe.lna.clamp = _maybe_get(lna_clamp, idx, afe.lna.clamp)
            if lna_gain is not None:
                afe.lna.gain = _maybe_get(lna_gain, idx, afe.lna.gain)
            if lna_int is not None:
                afe.lna.integrator_disable = bool(_maybe_get(lna_int, idx, afe.lna.integrator_disable))

    return cfg


def build_defaults_from_args(
    *,
    ip: str,
    slot: int,
    per_ch_offset: int,
    vgain: int,
    lpf_cutoff: int,
    pga_gain: int,
    lna_gain: int,
    lna_clamp: int,
) -> pb_high.ConfigureRequest:
    """
    Thin wrapper around make_default_config to keep call-sites concise.
    """
    return make_default_config(
        ip=ip,
        slot=slot,
        per_ch_offset=per_ch_offset,
        vgain=vgain,
        lpf_cutoff=lpf_cutoff,
        pga_gain=pga_gain,
        lna_gain=lna_gain,
        lna_clamp=lna_clamp,
    )


def send_configure_request(
    cfg: pb_high.ConfigureRequest,
    *,
    host: str,
    port: int,
    route: str,
    timeout_ms: int,
    identity: str = "client-v2-pds",
) -> dict[str, Any]:
    """
    Send a ConfigureRequest to *host:port* and return a small summary dict.
    """
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, identity.encode("ascii"))
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)

    endpoint = f"tcp://{host}:{port}"
    sock.connect(endpoint)

    req_env = build_configure_v2_envelope(cfg, route=route)
    t_send_ns = time.time_ns()
    print_envelope("REQUEST", req_env)
    sock.send(req_env.SerializeToString())

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply_bytes = frames[-1]
    t_recv_ns = time.time_ns()
    rtt_ms = (t_recv_ns - t_send_ns) / 1e6

    reply = pb_high.ControlEnvelopeV2()
    if not reply.ParseFromString(reply_bytes):
        raise RuntimeError("Failed to parse ControlEnvelopeV2 reply")

    print_envelope("RESPONSE", reply)
    print(f"[METRICS]\n  client_send_iso  : {ns_to_iso(t_send_ns)}")
    print(f"  client_recv_iso  : {ns_to_iso(t_recv_ns)}")
    print(f"  client_RTT_ms    : {rtt_ms:.2f}")
    if reply.timestamp_ns:
        print(f"  server_ts_iso    : {ns_to_iso(reply.timestamp_ns)}")
    print()

    out = pb_high.ConfigureResponse()
    if not out.ParseFromString(reply.payload):
        raise RuntimeError("Failed to parse ConfigureResponse")

    summarize_configure_response(out, full=True)

    return {
        "endpoint": endpoint,
        "request": {
            "version": req_env.version,
            "dir": int(req_env.dir),
            "type": int(req_env.type),
            "task_id": req_env.task_id,
            "msg_id": req_env.msg_id,
            "route": req_env.route,
            "timestamp_ns": req_env.timestamp_ns,
            "payload_size": len(req_env.payload),
        },
        "response": {
            "version": reply.version,
            "dir": int(reply.dir),
            "type": int(reply.type),
            "task_id": reply.task_id,
            "msg_id": reply.msg_id,
            "correl_id": reply.correl_id,
            "timestamp_ns": reply.timestamp_ns,
            "payload_size": len(reply.payload),
        },
        "metrics": {
            "client_send_ns": t_send_ns,
            "client_recv_ns": t_recv_ns,
            "rtt_ms": rtt_ms,
        },
        "configure_response": {
            "success": out.success,
            "message_lines": out.message.count("\n") + (1 if out.message else 0),
        },
    }

