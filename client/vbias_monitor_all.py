#!/usr/bin/env python3
import argparse
import shutil
import os
import sys
import time
import re
from collections import deque
import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


def read_one(sock, route, afe):
    req = pb_low.cmd_readBiasVoltageMonitor()
    req.id = 0
    req.afeBlock = afe

    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_REQ
    env.payload = req.SerializeToString()
    env.route = route

    sock.send(env.SerializeToString())
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())

    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(frames[-1])
    if rep.type != pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_RESP:
        raise RuntimeError(f"Unexpected reply type {rep.type}")

    out = pb_low.cmd_readBiasVoltageMonitor_response()
    out.ParseFromString(rep.payload)
    return out


def main():
    ap = argparse.ArgumentParser(description="Read all AFE bias monitors once (V2).")
    ap.add_argument("--ip", default="127.0.0.1", help="Server IP (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=9876, help="Server port (default 9876)")
    ap.add_argument("--timeout", type=int, default=2000, help="ZMQ send/recv timeout (ms)")
    ap.add_argument("--route", default="mezz/0", help="Logical route")
    ap.add_argument("--identity", default="vbias-monitor-all", help="Dealer identity")
    ap.add_argument("--afes", type=str, default="0-4", help="AFE list, CSV/range, e.g. '0-4' or '0,2,4'")
    ap.add_argument("--interval", type=float, default=1.0, help="Seconds between refreshes (default 1s)")
    ap.add_argument("--max-points", type=int, default=300, help="Points kept for plotting (default 300)")
    ap.add_argument("--no-plot", action="store_true", help="Disable matplotlib plotting (text output only)")
    ap.add_argument("--status", action="store_true", help="Show live updating status in terminal")
    args = ap.parse_args()

    # parse AFE list
    afes = []
    for tok in args.afes.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '-' in tok:
            a, b = tok.split('-', 1)
            a = int(a); b = int(b)
            if a > b:
                a, b = b, a
            afes.extend(range(a, b + 1))
        else:
            afes.append(int(tok))
    afes = sorted(set(afes))

    endpoint = f"tcp://{args.ip}:{args.port}"
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.IDENTITY, args.identity.encode())
    s.setsockopt(zmq.RCVTIMEO, args.timeout)
    s.setsockopt(zmq.SNDTIMEO, args.timeout)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)

    printed_board_readback = False

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None

    plot_enabled = (not args.no_plot) and (plt is not None)

    names_rails = ["3V3PDS", "1V8PDS", "3V3A", "1V8A", "5VA"]  # 5VA is stored as -5VA; display absolute name
    names_biases = [f"BIAS{i}" for i in afes]

    history = {name: deque(maxlen=args.max_points) for name in names_rails + names_biases}
    history["t"] = deque(maxlen=args.max_points)

    if plot_enabled:
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
        fig.patch.set_facecolor("black")
        rail_lines = {}
        bias_lines = {}
        for name in names_rails:
            (rail_lines[name],) = ax1.plot([], [], label=name)
        for name in names_biases:
            (bias_lines[name],) = ax2.plot([], [], label=name)
        for ax in (ax1, ax2):
            ax.set_facecolor("black")
            ax.tick_params(colors="white")
            ax.spines["bottom"].set_color("white")
            ax.spines["top"].set_color("white")
            ax.spines["left"].set_color("white")
            ax.spines["right"].set_color("white")
            ax.yaxis.label.set_color("white")
            ax.xaxis.label.set_color("white")
            ax.grid(color="gray", linestyle="--", alpha=0.3)
        ax1.set_ylabel("Rails [V]")
        ax2.set_ylabel("Bias [V]")
        ax2.set_xlabel("Time [s]")
        leg1 = ax1.legend(loc="upper right", facecolor="black", edgecolor="white")
        leg2 = ax2.legend(loc="upper right", facecolor="black", edgecolor="white")
        for leg in (leg1, leg2):
            for text in leg.get_texts():
                text.set_color("white")
        rail_text = ax1.text(0.01, 0.99, "", transform=ax1.transAxes, va="top", ha="left", color="white", fontsize=9)
        bias_text = ax2.text(0.01, 0.99, "", transform=ax2.transAxes, va="top", ha="left", color="white", fontsize=9)
        fig.tight_layout()

    start = time.time()
    def print_status(line):
        if not args.status:
            return
        cols = shutil.get_terminal_size(fallback=(120, 20)).columns
        if len(line) >= cols:
            line = line[:cols-1]
        # Clear current line and rewrite without newline
        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()

    def parse_rails(msg):
        rails = {}
        for name, val in re.findall(r'([A-Z0-9]+):\s*([-]?\d+(?:\.\d+)?)', msg):
            if name == "-5VA":
                rails["5VA"] = float(val)
            else:
                rails[name] = float(val)
        return rails

    try:
        while True:
            loop_time = time.time() - start
            rails_read = False

            for afe in afes:
                try:
                    out = read_one(s, args.route, afe)
                except zmq.Again:
                    print(f"[timeout] afe={afe} no reply")
                    continue
                except Exception as e:
                    print(f"[error] afe={afe} {e}")
                    continue

                if not out.success:
                    print(f"[server error] afe={afe} message='{out.message}'")
                    continue

                mv = out.biasVoltageValue
                bias_volts = mv / 1000.0
                afe_idx = out.afeBlock
                history.setdefault(f"BIAS{afe_idx}", deque(maxlen=args.max_points))
                history[f"BIAS{afe_idx}"].append(bias_volts)

                if not rails_read:
                    rail_vals = parse_rails(out.message)
                    for name in names_rails:
                        if name in rail_vals:
                            history[name].append(rail_vals[name])
                    rails_read = True

            history["t"].append(loop_time)
            parts = []
            if rails_read:
                parts.append("Rails: " + " ".join(f"{n}={history[n][-1]:.3f}" for n in names_rails if history[n]))
            parts.append("Biases: " + " ".join(f"{n}={history[n][-1]:.3f}" for n in names_biases if history[n]))
            print_status(" | ".join(parts))

            if plot_enabled:
                tvals = list(history["t"])
                for name in names_rails:
                    rail_lines[name].set_data(tvals, list(history[name]))
                for name in names_biases:
                    bias_lines[name].set_data(tvals, list(history[name]))
                if tvals:
                    ax1.relim(); ax1.autoscale_view()
                    ax2.relim(); ax2.autoscale_view()
                if rails_read:
                    rail_text.set_text("\n".join(f"{n}: {history[n][-1]:.3f} V" for n in names_rails if history[n]))
                bias_text.set_text("\n".join(f"{n}: {history[n][-1]:.3f} V" for n in names_biases if history[n]))
                plt.pause(0.001)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    sys.exit(main())
