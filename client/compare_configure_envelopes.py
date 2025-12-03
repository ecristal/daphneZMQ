#!/usr/bin/env python3
"""
Send two CONFIGURE_FE requests (EnvelopeV2), save their envelopes, and show a
diff of the request contents:

1) A CLI-style request matching configure_fe_min_v2.py arguments.
2) A seed/output JSON-driven request (e.g. pds/configs/vd_coldbox/daphne_mezz.json).

Usage example (matches the user's CLI request):
  python3 compare_configure_envelopes.py \
    --host 127.0.0.1 --port 9876 --route mezz/0 \
    --json-path pds/configs/vd_coldbox/daphne_mezz.json --board-id 60 \
    --vgain 2300 --ch-offset 2275 --lpf-cutoff 10 \
    --pga-clamp-level "0 dBFS" --pga-gain-control "24 dB" \
    --lna-gain-control "12 dB" --lna-input-clamp auto --full
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

from google.protobuf.json_format import MessageToDict
import zmq

from client_dictionaries import (
    lna_gain_control_dict,
    lna_input_clamp_dict,
    lpf_dict,
    pga_clamp_level_dict,
    pga_gain_control_dict,
)
from configure_fe_min_v2 import (
    build_configure_v2_envelope,
    make_default_config,
    summarize_configure_response,
)
from pds_configure_utils import (
    build_defaults_from_args,
    build_request_from_seed,
    load_seed_from_output,
)
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high


def msg_to_sorted_json(msg) -> str:
    """Stable JSON for a protobuf message (sorted keys)."""
    # Older google.protobuf versions don't support including_default_value_fields
    d = MessageToDict(msg, preserving_proto_field_name=True)
    return json.dumps(d, sort_keys=True, indent=2)


def save_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def send_envelope(env: pb_high.ControlEnvelopeV2, *, host: str, port: int, timeout_ms: int, label: str) -> None:
    """Send a prepared envelope and print the response summary."""
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, f"compare-{label}".encode("ascii"))
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.connect(f"tcp://{host}:{port}")
    sock.send(env.SerializeToString())
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply = pb_high.ControlEnvelopeV2()
    reply.ParseFromString(frames[-1])
    resp = pb_high.ConfigureResponse()
    resp.ParseFromString(reply.payload)
    print(f"[{label}] reply type={reply.type} success={resp.success}")
    summarize_configure_response(resp, full=True)


def build_cli_cfg(args: argparse.Namespace) -> pb_high.ConfigureRequest:
    """Mirror configure_fe_min_v2 defaults/CLI."""
    lpf = lpf_dict[args.lpf_cutoff]
    pga_clamp = pga_clamp_level_dict[args.pga_clamp_level]
    pga_gain = pga_gain_control_dict[args.pga_gain_control]
    lna_gain = lna_gain_control_dict[args.lna_gain_control]
    lna_clamp = lna_input_clamp_dict[args.lna_input_clamp]

    cfg = make_default_config(
        ip=args.host,
        slot=0,
        timeout_ms=args.timeout,
        biasctrl=args.biasctrl,
        self_trigger_threshold=args.self_trigger_threshold,
        self_trigger_xcorr=args.self_trigger_xcorr,
        tp_conf=args.tp_conf,
        compensator=args.compensator,
        inverters=args.inverters,
        per_ch_trim=0,
        per_ch_offset=args.ch_offset,
        vgain=args.vgain,
        lpf_cutoff=lpf,
        pga_clamp_level=pga_clamp,
        pga_gain=pga_gain,
        lna_gain=lna_gain,
        lna_clamp=lna_clamp,
    )
    return cfg


def build_seed_cfg(args: argparse.Namespace) -> pb_high.ConfigureRequest:
    """Build ConfigureRequest from a seed/output JSON."""
    seed_cfgs = load_seed_from_output(Path(args.json_path))
    seed_cfg = seed_cfgs[str(args.board_id)]
    defaults = build_defaults_from_args(
        ip=args.host or seed_cfg.get("ip", "127.0.0.1"),
        slot=seed_cfg.get("slot_id", 0),
        per_ch_offset=args.ch_offset,
        vgain=args.vgain,
        lpf_cutoff=lpf_dict[args.lpf_cutoff],
        pga_gain=pga_gain_control_dict[args.pga_gain_control],
        lna_gain=lna_gain_control_dict[args.lna_gain_control],
        lna_clamp=lna_input_clamp_dict[args.lna_input_clamp],
    )
    cfg = build_request_from_seed(seed_cfg, defaults, prefer_seed_common=not args.prefer_cli_common)
    cfg.daphne_address = seed_cfg.get("ip", args.host)
    cfg.timeout_ms = args.timeout
    return cfg


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build/send two CONFIGURE_FE V2 envelopes (CLI vs seed JSON) and diff them.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--timeout", type=int, default=6000, help="Socket timeout in ms.")
    ap.add_argument("--json-path", default="pds/configs/vd_coldbox/daphne_mezz.json")
    ap.add_argument("--board-id", default="60", help="Board key in the seed/output JSON.")
    ap.add_argument("--out-dir", default="daphneZMQ/client/envelope_dumps")
    ap.add_argument("--prefer-cli-common", action="store_true", help="Override seed common ADC/PGA/LNA with CLI defaults.")

    # CLI config knobs (mirroring configure_fe_min_v2 defaults/choices)
    ap.add_argument("-vgain", "--vgain", type=int, default=2300)
    ap.add_argument("-ch_offset", "--ch-offset", "--ch_offset", type=int, default=2275)
    ap.add_argument("-lpf_cutoff", "--lpf-cutoff", "--lpf_cutoff", type=int, choices=lpf_dict.keys(), default=10)
    ap.add_argument(
        "-pga_clamp_level",
        "--pga-clamp-level",
        "--pga_clamp_level",
        type=str,
        choices=pga_clamp_level_dict.keys(),
        default="0 dBFS",
    )
    ap.add_argument(
        "-pga_gain_control",
        "--pga-gain-control",
        "--pga_gain_control",
        type=str,
        choices=pga_gain_control_dict.keys(),
        default="24 dB",
    )
    ap.add_argument(
        "-lna_gain_control",
        "--lna-gain-control",
        "--lna_gain_control",
        type=str,
        choices=lna_gain_control_dict.keys(),
        default="12 dB",
    )
    ap.add_argument(
        "-lna_input_clamp",
        "--lna-input-clamp",
        "--lna_input_clamp",
        type=str,
        choices=lna_input_clamp_dict.keys(),
        default="auto",
    )
    ap.add_argument("--biasctrl", type=int, default=1300)
    ap.add_argument("--self_trigger_threshold", type=int, default=0)
    ap.add_argument("--self_trigger_xcorr", type=int, default=0)
    ap.add_argument("--tp_conf", type=int, default=0)
    ap.add_argument("--compensator", type=int, default=0)
    ap.add_argument("--inverters", type=int, default=0)
    ap.add_argument("--full", action="store_true", help="Kept for parity; server auto-aligns by default.")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)

    # Build requests
    cfg_cli = build_cli_cfg(args)
    cfg_seed = build_seed_cfg(args)

    # Build envelopes and save them
    env_cli = build_configure_v2_envelope(cfg_cli, route=args.route)
    env_seed = build_configure_v2_envelope(cfg_seed, route=args.route)
    save_bytes(out_dir / "cli_configure_env.bin", env_cli.SerializeToString())
    save_bytes(out_dir / "seed_configure_env.bin", env_seed.SerializeToString())
    (out_dir / "cli_configure_request.json").write_text(msg_to_sorted_json(cfg_cli))
    (out_dir / "seed_configure_request.json").write_text(msg_to_sorted_json(cfg_seed))

    # Diff the requests
    diff = difflib.unified_diff(
        msg_to_sorted_json(cfg_cli).splitlines(),
        msg_to_sorted_json(cfg_seed).splitlines(),
        fromfile="cli_request",
        tofile="seed_request",
        lineterm="",
    )
    print("\n=== REQUEST DIFF (cli vs seed) ===")
    for line in diff:
        print(line)

    # Send both
    print("\n=== SENDING CLI REQUEST ===")
    send_envelope(env_cli, host=args.host, port=args.port, timeout_ms=args.timeout, label="cli")
    print("\n=== SENDING SEED REQUEST ===")
    send_envelope(env_seed, host=args.host, port=args.port, timeout_ms=args.timeout, label="seed")

    print(f"\nSaved envelopes/requests under: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
