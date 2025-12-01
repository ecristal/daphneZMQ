#!/usr/bin/env python3
"""
Build a ConfigureRequest from a PDS detail JSON, filling missing pieces with
the same defaults as configure_fe_min_v2, and send it via EnvelopeV2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from client_dictionaries import (
    lna_gain_control_dict,
    lna_input_clamp_dict,
    lpf_dict,
    pga_gain_control_dict,
)
from pds_configure_utils import (
    build_defaults_from_args,
    build_request_from_seed,
    load_seed_from_detail,
    send_configure_request,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Configure FE using a PDS detail JSON (EnvelopeV2).")
    ap.add_argument("detail", type=Path, help="Path to detail JSON (e.g. pds/configs/vst/detail_mezz.json).")
    ap.add_argument("--config-name", default="np02_daphne_selftrigger", help="Seed configuration name to build (default: np02_daphne_selftrigger).")
    ap.add_argument("--board-id", help="Only configure the board matching this board_id (string in the output JSON).")
    ap.add_argument("--host", help="Override connection IP (defaults to the board IP in the detail).")
    ap.add_argument("--port", type=int, default=9876, help="Server port (default: 9876).")
    ap.add_argument("--route", default="mezz/0", help="Optional logical route.")
    ap.add_argument("--timeout", type=int, default=6000, help="Socket timeout in ms (default: 6000).")
    ap.add_argument("--prefer-cli-common", action="store_true", help="Keep CLI defaults for ADC/PGA/LNA instead of overriding with detail/common_conf.")
    ap.add_argument("--json", action="store_true", help="Emit JSON summary after configuring.")

    # Defaults align with configure_fe_min_v2 CLI
    ap.add_argument("-vgain", type=int, default=1600, help="AFE attenuator code (default 1600).")
    ap.add_argument("-ch_offset", type=int, default=2275, help="Channel offset DAC code (default 2275).")
    ap.add_argument("-lpf_cutoff", type=int, choices=lpf_dict.keys(), default=10, help="LPF cutoff MHz (10/15/20/30).")
    ap.add_argument("-pga_gain_control", type=str, choices=pga_gain_control_dict.keys(), default="24 dB")
    ap.add_argument("-lna_gain_control", type=str, choices=lna_gain_control_dict.keys(), default="12 dB")
    ap.add_argument("-lna_input_clamp", type=str, choices=lna_input_clamp_dict.keys(), default="auto")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    seed_cfgs = load_seed_from_detail(args.detail, args.config_name)

    summaries: dict[str, dict] = {}
    for board_id, seed_cfg in seed_cfgs.items():
        if args.board_id and str(args.board_id) != str(board_id):
            continue

        target_ip = args.host or seed_cfg.get("ip", "127.0.0.1")
        defaults = build_defaults_from_args(
            ip=target_ip,
            slot=seed_cfg.get("slot_id", 0),
            per_ch_offset=args.ch_offset,
            vgain=args.vgain,
            lpf_cutoff=lpf_dict[args.lpf_cutoff],
            pga_gain=pga_gain_control_dict[args.pga_gain_control],
            lna_gain=lna_gain_control_dict[args.lna_gain_control],
            lna_clamp=lna_input_clamp_dict[args.lna_input_clamp],
        )

        cfg = build_request_from_seed(
            seed_cfg,
            defaults,
            prefer_seed_common=not args.prefer_cli_common,
        )
        cfg.daphne_address = seed_cfg.get("ip", target_ip)
        cfg.timeout_ms = args.timeout

        summary = send_configure_request(
            cfg,
            host=target_ip,
            port=args.port,
            route=args.route,
            timeout_ms=args.timeout,
            identity="client-v2-detail",
        )
        summaries[str(board_id)] = summary

    if args.json and summaries:
        print(json.dumps(summaries, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

