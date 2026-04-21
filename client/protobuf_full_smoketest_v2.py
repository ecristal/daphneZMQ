#!/usr/bin/env python3
"""
Exercise all implemented MT2 protobuf handlers on daphneServer.

Read-only checks run by default. Enable write-back and intrusive operations
explicitly with CLI flags.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


def next_ids() -> Tuple[int, int]:
    now_ns = time.time_ns()
    mask = (1 << 63) - 1
    return ((now_ns << 16) ^ random.randrange(1 << 16)) & mask, ((now_ns << 1) ^ random.randrange(1 << 16)) & mask


def parse_int_tokens(tokens: List[str]) -> List[int]:
    values: List[int] = []
    for tok in tokens:
        for part in tok.split(","):
            part = part.strip()
            if part:
                values.append(int(part, 0))
    return values


def parse_kv_list(items: Optional[List[str]]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not items:
        return out
    for item in items:
        if ":" not in item:
            raise ValueError(f"Expected AFE:VALUE, got '{item}'")
        afe_str, val_str = item.split(":", 1)
        out[int(afe_str, 0)] = int(val_str, 0)
    return out


def v2_rpc(sock: zmq.Socket, mtype_req: int, payload_bytes: bytes, route: str, timeout_ms: int) -> pb_high.ControlEnvelopeV2:
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = mtype_req
    env.payload = payload_bytes
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route

    sock.send(env.SerializeToString())
    if not sock.poll(timeout_ms, zmq.POLLIN):
        raise TimeoutError(f"Timeout waiting for response to type={mtype_req}")

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply_bytes = frames[-1]

    rep = pb_high.ControlEnvelopeV2()
    if not rep.ParseFromString(reply_bytes):
        raise RuntimeError("Failed to parse ControlEnvelopeV2 reply")
    if rep.dir != pb_high.DIR_RESPONSE:
        raise RuntimeError(f"Unexpected dir={rep.dir} for type={mtype_req}")
    if rep.correl_id and rep.correl_id != env.msg_id:
        raise RuntimeError(f"Correlation mismatch (got {rep.correl_id}, expected {env.msg_id})")
    return rep


def load_config_request(json_path: str) -> pb_high.ConfigureRequest:
    with open(json_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    first = next(iter(cfg.values()))
    req = pb_high.ConfigureRequest()
    req.daphne_address = first.get("daphne_address", "0.0.0.0")
    req.slot = first["slot"]
    req.timeout_ms = int(first.get("timeout_ms", 500))
    req.biasctrl = first["bias_ctrl"]
    req.self_trigger_threshold = int(first["self_trigger_threshold"])
    req.self_trigger_xcorr = int(first["self_trigger_xcorr"])
    req.tp_conf = int(first["tp_conf"])
    req.compensator = int(first["compensator"])
    req.inverters = int(first["inverter"])

    ch_conf = first["channel_analog_conf"]
    for cid, gain, offset, trim in zip(ch_conf["ids"], ch_conf["gains"], ch_conf["offsets"], ch_conf["trims"]):
        ch = req.channels.add()
        ch.id = cid
        ch.gain = gain
        ch.offset = offset
        ch.trim = trim

    afe_conf = first["afes"]
    for idx, att, vbias, adc, pga, lna in zip(
        afe_conf["ids"],
        afe_conf["attenuators"],
        afe_conf["v_biases"],
        afe_conf["adcs"],
        afe_conf["pgas"],
        afe_conf["lnas"],
    ):
        afe = req.afes.add()
        afe.id = idx
        afe.attenuators = att
        afe.v_bias = vbias

        afe_adc = afe.adc
        afe_adc.resolution = adc["resolution"]
        afe_adc.output_format = adc["output_format"]
        afe_adc.sb_first = adc.get("SB_first", adc.get("sb_first", False))

        afe_pga = afe.pga
        afe_pga.lpf_cut_frequency = pga["lpf_cut_frequency"]
        afe_pga.integrator_disable = pga["integrator_disable"]
        afe_pga.gain = pga["gain"]

        afe_lna = afe.lna
        afe_lna.clamp = lna["clamp"]
        afe_lna.integrator_disable = lna["integrator_disable"]
        afe_lna.gain = lna["gain"]

    if "full_stream_channels" in first:
        req.full_stream_channels.extend(first["full_stream_channels"])
    return req


def print_status(label: str, resp: object, extra: str = "") -> None:
    success = getattr(resp, "success", None)
    message = getattr(resp, "message", "")
    if success is None:
        status = "OK"
    else:
        status = "OK" if success else "FAIL"
    msg = f"{message}".strip()
    suffix = f" :: {msg}" if msg else ""
    if extra:
        suffix = f"{suffix} {extra}".strip()
    print(f"[{status}] {label}{suffix}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Full MT2 protobuf smoketest (EnvelopeV2).")
    ap.add_argument("-ip", default="127.0.0.1", help="Server IP")
    ap.add_argument("-port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="EnvelopeV2 route")
    ap.add_argument("--identity", default="proto-full-test", help="ZMQ identity")
    ap.add_argument("--timeout_ms", type=int, default=5000, help="Per-request timeout (ms)")

    ap.add_argument("--channels", nargs="+", default=["0"], help="Channel list for single-CH ops (e.g. 0 1 2 or 0,1,2)")
    ap.add_argument("--counter-channels", nargs="*", default=[], help="Trigger counter channels (empty=all)")
    ap.add_argument("--afes", nargs="*", default=[], help="AFE list (e.g. 0 1 2 or 0,1,2)")
    ap.add_argument("--afe-count", type=int, default=5, help="Default AFE count if --afes not provided")

    ap.add_argument("--skip-bias-monitor", action="store_true", help="Skip bias voltage monitor reads")
    ap.add_argument("--current-monitor-channel", type=int, default=0, help="Current monitor channel (MT2_READ_CURRENT_MONITOR)")
    ap.add_argument("--afe-reg", nargs=2, action="append", metavar=("AFE", "REG"), help="Read/write AFE reg (repeatable)")

    ap.add_argument("--do-writes", action="store_true", help="Enable write-back tests where safe")
    ap.add_argument("--force-trim-all", type=int, help="Force WRITE_TRIM_ALL_CH with value")
    ap.add_argument("--force-offset-all", type=int, help="Force WRITE_OFFSET_ALL_CH with value")
    ap.add_argument("--force-trim-afe", action="append", metavar="AFE:VALUE", help="Force WRITE_TRIM_ALL_AFE for AFE:VALUE")
    ap.add_argument("--force-offset-afe", action="append", metavar="AFE:VALUE", help="Force WRITE_OFFSET_ALL_AFE for AFE:VALUE")
    ap.add_argument("--attenuation", type=int, help="WRITE_AFE_ATTENUATION value (applies to all AFEs)")
    ap.add_argument("--vbias-control", type=int, help="WRITE_VBIAS_CONTROL value")
    ap.add_argument("--vbias-enable", action="store_true", help="Enable Vbias control when writing")

    ap.add_argument("--configure-json", help="Send CONFIGURE_FE using JSON")
    ap.add_argument("--configure-clks", action="store_true", help="Send CONFIGURE_CLKS")
    ap.add_argument("--clks-id", type=int, default=0, help="ConfigureCLKsRequest.id")
    ap.add_argument("--ctrl-ep-clk", action="store_true", help="ConfigureCLKsRequest.ctrl_ep_clk")
    ap.add_argument("--reset-mmcm1", action="store_true", help="ConfigureCLKsRequest.reset_MMCM1")
    ap.add_argument("--reset-endpoint", action="store_true", help="ConfigureCLKsRequest.reset_endpoint")

    ap.add_argument("--align-afes", action="store_true", help="Send ALIGN_AFE")
    ap.add_argument("--set-afe-reset", choices=["0", "1"], help="Send SET_AFE_RESET with value")
    ap.add_argument("--do-afe-reset", action="store_true", help="Send DO_AFE_RESET")
    ap.add_argument("--set-afe-powerstate", choices=["0", "1"], help="Send SET_AFE_POWERSTATE with value")
    ap.add_argument("--do-software-trigger", action="store_true", help="Send DO_SOFTWARE_TRIGGER")

    ap.add_argument("--spybuffer", action="store_true", help="Exercise DUMP_SPYBUFFER and CHUNK")
    ap.add_argument("--spybuffer-waveforms", type=int, default=1, help="Spybuffer waveforms")
    ap.add_argument("--spybuffer-samples", type=int, default=32, help="Spybuffer samples")
    ap.add_argument("--spybuffer-software-trigger", action="store_true", help="Spybuffer software trigger")

    args = ap.parse_args()

    channels = parse_int_tokens(args.channels)
    counter_channels = parse_int_tokens(args.counter_channels) if args.counter_channels else []
    afe_list = parse_int_tokens(args.afes) if args.afes else list(range(args.afe_count))
    force_trim_afe = parse_kv_list(args.force_trim_afe)
    force_offset_afe = parse_kv_list(args.force_offset_afe)

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, args.identity.encode())
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{args.ip}:{args.port}")

    failures: List[str] = []

    def run(label: str, fn):
        try:
            return fn()
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            print(f"[FAIL] {label}: {exc}")
            return None

    # ------------------------ Read-only tests ------------------------
    def do_test_reg():
        req = pb_high.TestRegRequest()
        rep = v2_rpc(sock, pb_high.MT2_READ_TEST_REG_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_TEST_REG_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_high.TestRegResponse()
        resp.ParseFromString(rep.payload)
        print_status("READ_TEST_REG", resp, f"value=0x{resp.value:08X}")
        return resp

    def do_general_info():
        req = pb_high.InfoRequest(level=0)
        rep = v2_rpc(sock, pb_high.MT2_READ_GENERAL_INFO_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_GENERAL_INFO_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_high.GeneralInfo()
        resp.ParseFromString(rep.payload)
        extra = f"vbias0={resp.v_bias_0:.3f} vbias1={resp.v_bias_1:.3f} temp={resp.temperature:.2f}"
        print_status("READ_GENERAL_INFO", resp, extra)
        return resp

    def do_trigger_counters():
        req = pb_high.ReadTriggerCountersRequest()
        if counter_channels:
            req.channels.extend(counter_channels)
        rep = v2_rpc(sock, pb_high.MT2_READ_TRIGGER_COUNTERS_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_TRIGGER_COUNTERS_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_high.ReadTriggerCountersResponse()
        resp.ParseFromString(rep.payload)
        extra = f"channels={len(resp.snapshots)}"
        print_status("READ_TRIGGER_COUNTERS", resp, extra)
        return resp

    def do_read_current_monitor():
        req = pb_low.cmd_readCurrentMonitor(currentMonitorChannel=args.current_monitor_channel)
        rep = v2_rpc(sock, pb_high.MT2_READ_CURRENT_MONITOR_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_CURRENT_MONITOR_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readCurrentMonitor_response()
        resp.ParseFromString(rep.payload)
        print_status("READ_CURRENT_MONITOR", resp, f"ch={resp.currentMonitorChannel}")
        return resp

    trim_single: Dict[int, int] = {}
    offset_single: Dict[int, int] = {}
    trim_all_afe: Dict[int, List[int]] = {}
    offset_all_afe: Dict[int, List[int]] = {}
    afe_vgain: Dict[int, int] = {}
    afe_bias: Dict[int, int] = {}
    afe_reg_vals: Dict[Tuple[int, int], int] = {}

    run("READ_TEST_REG", do_test_reg)
    run("READ_GENERAL_INFO", do_general_info)
    run("READ_TRIGGER_COUNTERS", do_trigger_counters)
    run("READ_CURRENT_MONITOR", do_read_current_monitor)

    def read_trim_all_ch():
        req = pb_low.cmd_readTrim_allChannels()
        rep = v2_rpc(sock, pb_high.MT2_READ_TRIM_ALL_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_TRIM_ALL_CH_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readTrim_allChannels_response()
        resp.ParseFromString(rep.payload)
        print_status("READ_TRIM_ALL_CH", resp, f"n={len(resp.trimValues)}")
        return resp

    def read_offset_all_ch():
        req = pb_low.cmd_readOffset_allChannels()
        rep = v2_rpc(sock, pb_high.MT2_READ_OFFSET_ALL_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_OFFSET_ALL_CH_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readOffset_allChannels_response()
        resp.ParseFromString(rep.payload)
        print_status("READ_OFFSET_ALL_CH", resp, f"n={len(resp.offsetValues)}")
        return resp

    def read_trim_all_afe(afe: int):
        req = pb_low.cmd_readTrim_allAFE(afeBlock=afe)
        rep = v2_rpc(sock, pb_high.MT2_READ_TRIM_ALL_AFE_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_TRIM_ALL_AFE_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readTrim_allAFE_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_TRIM_ALL_AFE[{afe}]", resp, f"n={len(resp.trimValues)}")
        return resp

    def read_offset_all_afe(afe: int):
        req = pb_low.cmd_readOffset_allAFE(afeBlock=afe)
        rep = v2_rpc(sock, pb_high.MT2_READ_OFFSET_ALL_AFE_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_OFFSET_ALL_AFE_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readOffset_allAFE_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_OFFSET_ALL_AFE[{afe}]", resp, f"n={len(resp.offsetValues)}")
        return resp

    def read_trim_single(ch: int):
        req = pb_low.cmd_readTrim_singleChannel(trimChannel=ch)
        rep = v2_rpc(sock, pb_high.MT2_READ_TRIM_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_TRIM_CH_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readTrim_singleChannel_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_TRIM_CH[{ch}]", resp, f"value={resp.trimValue}")
        return resp

    def read_offset_single(ch: int):
        req = pb_low.cmd_readOffset_singleChannel(offsetChannel=ch)
        rep = v2_rpc(sock, pb_high.MT2_READ_OFFSET_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_OFFSET_CH_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readOffset_singleChannel_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_OFFSET_CH[{ch}]", resp, f"value={resp.offsetValue}")
        return resp

    def read_vbias_control():
        req = pb_low.cmd_readVbiasControl()
        rep = v2_rpc(sock, pb_high.MT2_READ_VBIAS_CONTROL_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_VBIAS_CONTROL_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readVbiasControl_response()
        resp.ParseFromString(rep.payload)
        print_status("READ_VBIAS_CONTROL", resp, f"value={resp.vBiasControlValue}")
        return resp

    def read_afe_reg(afe: int, reg: int):
        req = pb_low.cmd_readAFEReg(afeBlock=afe, regAddress=reg)
        rep = v2_rpc(sock, pb_high.MT2_READ_AFE_REG_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_AFE_REG_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readAFEReg_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_AFE_REG[{afe},0x{reg:X}]", resp, f"value=0x{resp.regValue:X}")
        return resp

    def read_afe_vgain(afe: int):
        req = pb_low.cmd_readAFEVgain(afeBlock=afe)
        rep = v2_rpc(sock, pb_high.MT2_READ_AFE_VGAIN_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_AFE_VGAIN_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readAFEVgain_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_AFE_VGAIN[{afe}]", resp, f"value={resp.vgainValue}")
        return resp

    def read_afe_bias(afe: int):
        req = pb_low.cmd_readAFEBiasSet(afeBlock=afe)
        rep = v2_rpc(sock, pb_high.MT2_READ_AFE_BIAS_SET_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_AFE_BIAS_SET_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readAFEBiasSet_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_AFE_BIAS_SET[{afe}]", resp, f"value={resp.biasValue}")
        return resp

    def read_bias_monitor(afe: int):
        req = pb_low.cmd_readBiasVoltageMonitor(afeBlock=afe)
        rep = v2_rpc(sock, pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_REQ, req.SerializeToString(), args.route, args.timeout_ms)
        if rep.type != pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_RESP:
            raise RuntimeError(f"type mismatch {rep.type}")
        resp = pb_low.cmd_readBiasVoltageMonitor_response()
        resp.ParseFromString(rep.payload)
        print_status(f"READ_BIAS_VOLTAGE_MONITOR[{afe}]", resp, f"value={resp.biasVoltageValue}")
        return resp

    trim_all = run("READ_TRIM_ALL_CH", read_trim_all_ch)
    offset_all = run("READ_OFFSET_ALL_CH", read_offset_all_ch)

    if trim_all:
        trim_values = list(getattr(trim_all, "trimValues", []))
    else:
        trim_values = []
    if offset_all:
        offset_values = list(getattr(offset_all, "offsetValues", []))
    else:
        offset_values = []

    for afe in afe_list:
        resp = run(f"READ_TRIM_ALL_AFE[{afe}]", lambda afe=afe: read_trim_all_afe(afe))
        if resp:
            trim_all_afe[afe] = list(getattr(resp, "trimValues", []))
        resp = run(f"READ_OFFSET_ALL_AFE[{afe}]", lambda afe=afe: read_offset_all_afe(afe))
        if resp:
            offset_all_afe[afe] = list(getattr(resp, "offsetValues", []))
        resp = run(f"READ_AFE_VGAIN[{afe}]", lambda afe=afe: read_afe_vgain(afe))
        if resp:
            afe_vgain[afe] = getattr(resp, "vgainValue", 0)
        resp = run(f"READ_AFE_BIAS_SET[{afe}]", lambda afe=afe: read_afe_bias(afe))
        if resp:
            afe_bias[afe] = getattr(resp, "biasValue", 0)
        if not args.skip_bias_monitor:
            run(f"READ_BIAS_VOLTAGE_MONITOR[{afe}]", lambda afe=afe: read_bias_monitor(afe))

    for ch in channels:
        resp = run(f"READ_TRIM_CH[{ch}]", lambda ch=ch: read_trim_single(ch))
        if resp:
            trim_single[ch] = getattr(resp, "trimValue", 0)
        resp = run(f"READ_OFFSET_CH[{ch}]", lambda ch=ch: read_offset_single(ch))
        if resp:
            offset_single[ch] = getattr(resp, "offsetValue", 0)

    run("READ_VBIAS_CONTROL", read_vbias_control)

    if args.afe_reg:
        for afe_str, reg_str in args.afe_reg:
            afe = int(afe_str, 0)
            reg = int(reg_str, 0)
            resp = run(f"READ_AFE_REG[{afe},0x{reg:X}]", lambda afe=afe, reg=reg: read_afe_reg(afe, reg))
            if resp:
                afe_reg_vals[(afe, reg)] = getattr(resp, "regValue", 0)

    # ------------------------ Write-back tests ------------------------
    if args.do_writes:
        def write_trim_single(ch: int, value: int):
            req = pb_low.cmd_writeTrim_singleChannel(trimChannel=ch, trimValue=value, trimGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_TRIM_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_TRIM_CH_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeTrim_singleChannel_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_TRIM_CH[{ch}]", resp, f"value={resp.trimValue}")
            return resp

        def write_offset_single(ch: int, value: int):
            req = pb_low.cmd_writeOFFSET_singleChannel(offsetChannel=ch, offsetValue=value, offsetGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_OFFSET_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_OFFSET_CH_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeOFFSET_singleChannel_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_OFFSET_CH[{ch}]", resp, f"value={resp.offsetValue}")
            return resp

        def write_afe_vgain(afe: int, value: int):
            req = pb_low.cmd_writeAFEVGAIN(afeBlock=afe, vgainValue=value)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_AFE_VGAIN_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_AFE_VGAIN_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeAFEVGAIN_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_AFE_VGAIN[{afe}]", resp, f"value={resp.vgainValue}")
            return resp

        def write_afe_bias(afe: int, value: int):
            req = pb_low.cmd_writeAFEBiasSet(afeBlock=afe, biasValue=value)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_AFE_BIAS_SET_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_AFE_BIAS_SET_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeAFEBiasSet_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_AFE_BIAS_SET[{afe}]", resp, f"value={resp.biasValue}")
            return resp

        def write_afe_reg(afe: int, reg: int, value: int):
            req = pb_low.cmd_writeAFEReg(afeBlock=afe, regAddress=reg, regValue=value)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_AFE_REG_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_AFE_REG_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeAFEReg_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_AFE_REG[{afe},0x{reg:X}]", resp, f"value=0x{resp.regValue:X}")
            return resp

        def write_trim_all(value: int):
            req = pb_low.cmd_writeTRIM_allChannels(trimValue=value, trimGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_TRIM_ALL_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_TRIM_ALL_CH_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeTRIM_allChannels_response()
            resp.ParseFromString(rep.payload)
            print_status("WRITE_TRIM_ALL_CH", resp, f"value={resp.trimValue}")
            return resp

        def write_offset_all(value: int):
            req = pb_low.cmd_writeOFFSET_allChannels(offsetValue=value, offsetGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_OFFSET_ALL_CH_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_OFFSET_ALL_CH_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeOFFSET_allChannels_response()
            resp.ParseFromString(rep.payload)
            print_status("WRITE_OFFSET_ALL_CH", resp, f"value={resp.offsetValue}")
            return resp

        def write_trim_all_afe(afe: int, value: int):
            req = pb_low.cmd_writeTrim_allAFE(afeBlock=afe, trimValue=value, trimGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_TRIM_ALL_AFE_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_TRIM_ALL_AFE_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeTrim_allAFE_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_TRIM_ALL_AFE[{afe}]", resp, f"value={resp.trimValue}")
            return resp

        def write_offset_all_afe(afe: int, value: int):
            req = pb_low.cmd_writeOFFSET_allAFE(afeBlock=afe, offsetValue=value, offsetGain=False)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_OFFSET_ALL_AFE_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_OFFSET_ALL_AFE_RESP:
                raise RuntimeError(f"type mismatch {rep.type}")
            resp = pb_low.cmd_writeOFFSET_allAFE_response()
            resp.ParseFromString(rep.payload)
            print_status(f"WRITE_OFFSET_ALL_AFE[{afe}]", resp, f"value={resp.offsetValue}")
            return resp

        # Safe write-backs: per-channel/AFE using read values
        for ch in channels:
            if ch in trim_single:
                run(f"WRITE_TRIM_CH[{ch}]", lambda ch=ch: write_trim_single(ch, trim_single[ch]))
            if ch in offset_single:
                run(f"WRITE_OFFSET_CH[{ch}]", lambda ch=ch: write_offset_single(ch, offset_single[ch]))

        for afe in afe_list:
            if afe in afe_vgain:
                run(f"WRITE_AFE_VGAIN[{afe}]", lambda afe=afe: write_afe_vgain(afe, afe_vgain[afe]))
            if afe in afe_bias:
                run(f"WRITE_AFE_BIAS_SET[{afe}]", lambda afe=afe: write_afe_bias(afe, afe_bias[afe]))

        for (afe, reg), value in afe_reg_vals.items():
            run(f"WRITE_AFE_REG[{afe},0x{reg:X}]", lambda afe=afe, reg=reg, value=value: write_afe_reg(afe, reg, value))

        # Optional: write-all operations (safe only if uniform or forced)
        if args.force_trim_all is not None:
            run("WRITE_TRIM_ALL_CH", lambda: write_trim_all(args.force_trim_all))
        elif trim_values and len(set(trim_values)) == 1:
            run("WRITE_TRIM_ALL_CH", lambda: write_trim_all(trim_values[0]))
        else:
            print("[SKIP] WRITE_TRIM_ALL_CH (not uniform; use --force-trim-all to override)")

        if args.force_offset_all is not None:
            run("WRITE_OFFSET_ALL_CH", lambda: write_offset_all(args.force_offset_all))
        elif offset_values and len(set(offset_values)) == 1:
            run("WRITE_OFFSET_ALL_CH", lambda: write_offset_all(offset_values[0]))
        else:
            print("[SKIP] WRITE_OFFSET_ALL_CH (not uniform; use --force-offset-all to override)")

        for afe in afe_list:
            if afe in force_trim_afe:
                run(f"WRITE_TRIM_ALL_AFE[{afe}]", lambda afe=afe: write_trim_all_afe(afe, force_trim_afe[afe]))
            else:
                afe_vals = trim_all_afe.get(afe, [])
                if afe_vals and len(set(afe_vals)) == 1:
                    run(f"WRITE_TRIM_ALL_AFE[{afe}]", lambda afe=afe: write_trim_all_afe(afe, afe_vals[0]))
                else:
                    print(f"[SKIP] WRITE_TRIM_ALL_AFE[{afe}] (not uniform; use --force-trim-afe AFE:VAL)")

            if afe in force_offset_afe:
                run(f"WRITE_OFFSET_ALL_AFE[{afe}]", lambda afe=afe: write_offset_all_afe(afe, force_offset_afe[afe]))
            else:
                afe_off_vals = offset_all_afe.get(afe, [])
                if afe_off_vals and len(set(afe_off_vals)) == 1:
                    run(f"WRITE_OFFSET_ALL_AFE[{afe}]", lambda afe=afe: write_offset_all_afe(afe, afe_off_vals[0]))
                else:
                    print(f"[SKIP] WRITE_OFFSET_ALL_AFE[{afe}] (not uniform; use --force-offset-afe AFE:VAL)")

        if args.attenuation is not None:
            for afe in afe_list:
                req = pb_low.cmd_writeAFEAttenuation(afeBlock=afe, attenuation=args.attenuation)
                rep = v2_rpc(sock, pb_high.MT2_WRITE_AFE_ATTENUATION_REQ, req.SerializeToString(), args.route, args.timeout_ms)
                if rep.type != pb_high.MT2_WRITE_AFE_ATTENUATION_RESP:
                    print(f"[FAIL] WRITE_AFE_ATTENUATION[{afe}] type mismatch {rep.type}")
                    continue
                resp = pb_low.cmd_writeAFEAttenuation_response()
                resp.ParseFromString(rep.payload)
                print_status(f"WRITE_AFE_ATTENUATION[{afe}]", resp, f"value={resp.attenuation}")
        else:
            print("[SKIP] WRITE_AFE_ATTENUATION (requires --attenuation)")

        if args.vbias_control is not None:
            req = pb_low.cmd_writeVbiasControl(vBiasControlValue=args.vbias_control, enable=args.vbias_enable)
            rep = v2_rpc(sock, pb_high.MT2_WRITE_VBIAS_CONTROL_REQ, req.SerializeToString(), args.route, args.timeout_ms)
            if rep.type != pb_high.MT2_WRITE_VBIAS_CONTROL_RESP:
                print(f"[FAIL] WRITE_VBIAS_CONTROL type mismatch {rep.type}")
            else:
                resp = pb_low.cmd_writeVbiasControl_response()
                resp.ParseFromString(rep.payload)
                print_status("WRITE_VBIAS_CONTROL", resp, f"value={resp.vBiasControlValue}")
        else:
            print("[SKIP] WRITE_VBIAS_CONTROL (requires --vbias-control)")

    # ------------------------ Explicit/intrusive ops ------------------------
    if args.configure_clks:
        req = pb_high.ConfigureCLKsRequest()
        req.id = args.clks_id
        req.ctrl_ep_clk = args.ctrl_ep_clk
        req.reset_MMCM1 = args.reset_mmcm1
        req.reset_endpoint = args.reset_endpoint
        rep = run("CONFIGURE_CLKS", lambda: v2_rpc(sock, pb_high.MT2_CONFIGURE_CLKS_REQ, req.SerializeToString(), args.route, args.timeout_ms))
        if rep and rep.type == pb_high.MT2_CONFIGURE_CLKS_RESP:
            resp = pb_high.ConfigureCLKsResponse()
            resp.ParseFromString(rep.payload)
            print_status("CONFIGURE_CLKS", resp)

    if args.configure_json:
        req = load_config_request(args.configure_json)
        rep = run("CONFIGURE_FE", lambda: v2_rpc(sock, pb_high.MT2_CONFIGURE_FE_REQ, req.SerializeToString(), args.route, max(args.timeout_ms, 20000)))
        if rep and rep.type == pb_high.MT2_CONFIGURE_FE_RESP:
            resp = pb_high.ConfigureResponse()
            resp.ParseFromString(rep.payload)
            print_status("CONFIGURE_FE", resp)

    if args.align_afes:
        req = pb_low.cmd_alignAFEs()
        rep = run("ALIGN_AFE", lambda: v2_rpc(sock, pb_high.MT2_ALIGN_AFE_REQ, req.SerializeToString(), args.route, max(args.timeout_ms, 20000)))
        if rep and rep.type == pb_high.MT2_ALIGN_AFE_RESP:
            resp = pb_low.cmd_alignAFEs_response()
            resp.ParseFromString(rep.payload)
            print_status("ALIGN_AFE", resp)

    if args.set_afe_reset is not None:
        req = pb_low.cmd_setAFEReset(resetValue=bool(int(args.set_afe_reset)))
        rep = run("SET_AFE_RESET", lambda: v2_rpc(sock, pb_high.MT2_SET_AFE_RESET_REQ, req.SerializeToString(), args.route, args.timeout_ms))
        if rep and rep.type == pb_high.MT2_SET_AFE_RESET_RESP:
            resp = pb_low.cmd_setAFEReset_response()
            resp.ParseFromString(rep.payload)
            print_status("SET_AFE_RESET", resp, f"value={resp.resetValue}")

    if args.do_afe_reset:
        req = pb_low.cmd_doAFEReset()
        rep = run("DO_AFE_RESET", lambda: v2_rpc(sock, pb_high.MT2_DO_AFE_RESET_REQ, req.SerializeToString(), args.route, args.timeout_ms))
        if rep and rep.type == pb_high.MT2_DO_AFE_RESET_RESP:
            resp = pb_low.cmd_doAFEReset_response()
            resp.ParseFromString(rep.payload)
            print_status("DO_AFE_RESET", resp)

    if args.set_afe_powerstate is not None:
        req = pb_low.cmd_setAFEPowerState(powerState=bool(int(args.set_afe_powerstate)))
        rep = run("SET_AFE_POWERSTATE", lambda: v2_rpc(sock, pb_high.MT2_SET_AFE_POWERSTATE_REQ, req.SerializeToString(), args.route, args.timeout_ms))
        if rep and rep.type == pb_high.MT2_SET_AFE_POWERSTATE_RESP:
            resp = pb_low.cmd_setAFEPowerState_response()
            resp.ParseFromString(rep.payload)
            print_status("SET_AFE_POWERSTATE", resp, f"value={resp.powerState}")

    if args.do_software_trigger:
        req = pb_low.cmd_doSoftwareTrigger()
        rep = run("DO_SOFTWARE_TRIGGER", lambda: v2_rpc(sock, pb_high.MT2_DO_SOFTWARE_TRIGGER_REQ, req.SerializeToString(), args.route, args.timeout_ms))
        if rep and rep.type == pb_high.MT2_DO_SOFTWARE_TRIGGER_RESP:
            resp = pb_low.cmd_doSoftwareTrigger_response()
            resp.ParseFromString(rep.payload)
            print_status("DO_SOFTWARE_TRIGGER", resp)

    if args.spybuffer:
        req = pb_high.DumpSpyBuffersRequest()
        req.channelList.extend(channels[:1] if channels else [0])
        req.numberOfWaveforms = args.spybuffer_waveforms
        req.numberOfSamples = args.spybuffer_samples
        req.softwareTrigger = bool(args.spybuffer_software_trigger)
        rep = run("DUMP_SPYBUFFER", lambda: v2_rpc(sock, pb_high.MT2_DUMP_SPYBUFFER_REQ, req.SerializeToString(), args.route, max(args.timeout_ms, 20000)))
        if rep and rep.type == pb_high.MT2_DUMP_SPYBUFFER_RESP:
            resp = pb_high.DumpSpyBuffersResponse()
            resp.ParseFromString(rep.payload)
            print_status("DUMP_SPYBUFFER", resp, f"wf={resp.numberOfWaveforms} samples={resp.numberOfSamples}")

        req2 = pb_high.DumpSpyBuffersChunkRequest()
        req2.channelList.extend(req.channelList)
        req2.numberOfWaveforms = args.spybuffer_waveforms
        req2.numberOfSamples = args.spybuffer_samples
        req2.softwareTrigger = bool(args.spybuffer_software_trigger)
        req2.requestID = f"full-{uuid.uuid4()}"
        req2.chunkSize = max(1, args.spybuffer_waveforms)
        rep2 = run("DUMP_SPYBUFFER_CHUNK", lambda: v2_rpc(sock, pb_high.MT2_DUMP_SPYBUFFER_CHUNK_REQ, req2.SerializeToString(), args.route, max(args.timeout_ms, 30000)))
        if rep2 and rep2.type == pb_high.MT2_DUMP_SPYBUFFER_CHUNK_RESP:
            resp2 = pb_high.DumpSpyBuffersChunkResponse()
            resp2.ParseFromString(rep2.payload)
            print_status("DUMP_SPYBUFFER_CHUNK", resp2, f"wf={resp2.waveformCount} samples={resp2.numberOfSamples}")

    sock.close()

    if failures:
        print("\nFailures:")
        for item in failures:
            print(f"- {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
