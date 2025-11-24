#!/usr/bin/env python3
import os, sys, argparse, time, zmq, random
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low
from client_dictionaries import *

# ---------- simple id generator ----------
_PID  = os.getpid()
_RAND = random.randrange(1 << 30)
_SEQ  = 0
def next_ids():
    global _SEQ
    _SEQ += 1
    now_ns = time.time_ns()
    task_id = (now_ns << 16) ^ (_PID << 8) ^ (_RAND & 0xFF)
    msg_id  = (now_ns << 1) ^ _SEQ
    return task_id & ((1<<63)-1), msg_id & ((1<<63)-1)

def v2_rpc(sock, mtype_req, req_msg, *, route="mezz/0", timeout_ms=60000):
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir     = pb_high.DIR_REQUEST
    env.type    = mtype_req
    env.payload = req_msg.SerializeToString()
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    env.route = route

    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.send(env.SerializeToString())

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply_bytes = frames[-1]

    rep = pb_high.ControlEnvelopeV2()
    if not rep.ParseFromString(reply_bytes):
        raise RuntimeError("Bad V2 reply")
    if rep.dir != pb_high.DIR_RESPONSE or rep.correl_id != env.msg_id:
        raise RuntimeError("V2 correlation/type mismatch")

    return env, rep

def main():
    p = argparse.ArgumentParser(description="DAPHNE configuration over EnvelopeV2")
    p.add_argument("-ip", default="127.0.0.1")
    p.add_argument("-port", type=int, default=9876)
    p.add_argument("-vgain", type=int, default=1600)
    p.add_argument("-ch_offset", type=int, default=2275)
    p.add_argument("-align_afes", action="store_true")
    p.add_argument("-enable_integrators", action="store_true")
    p.add_argument("-lpf_cutoff", type=int, choices=[10,15,20,30], default=10)
    p.add_argument("-pga_clamp_level", type=str, choices=["-2 dBFS","0 dBFS","-2 dBFS_lowpower","0 dBFS_lowpower"], default="0 dBFS")
    p.add_argument("-pga_gain_control", type=str, choices=["24 dB","30 dB"], default="24 dB")
    p.add_argument("-lna_gain_control", type=str, choices=["18 dB","24 dB","12 dB"], default="12 dB")
    p.add_argument("-lna_input_clamp",  type=str, choices=["auto","1.5 Vpp","1.15 Vpp","0.6 Vpp"], default="auto")
    args = p.parse_args()

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, b"client-v2-config")
    sock.connect(f"tcp://{args.ip}:{args.port}")

    # dictionary lookups (same as legacy)
    lpf_code   = lpf_dict[args.lpf_cutoff]
    pga_clamp  = pga_clamp_level_dict[args.pga_clamp_level]
    pga_gain   = pga_gain_control_dict[args.pga_gain_control]
    lna_gain   = lna_gain_control_dict[args.lna_gain_control]
    lna_clamp  = lna_input_clamp_dict[args.lna_input_clamp]

    # ---------- 1) per-channel offset ----------
    for ch in range(40):
        req = pb_low.cmd_writeOFFSET_singleChannel()
        req.offsetChannel = ch
        req.offsetValue   = args.ch_offset
        req.offsetGain    = False
        _, rep = v2_rpc(sock, pb_high.MT2_WRITE_OFFSET_CH_REQ, req)
        msg = pb_low.cmd_writeOFFSET_singleChannel_response()
        msg.ParseFromString(rep.payload)
        print(f"[OFFSET ch{ch:02d}] success={msg.success} :: {msg.message}")

    # ---------- 2) per-AFE VGAIN/attenuation ----------
    for afe in range(5):
        req = pb_low.cmd_writeAFEVGAIN()
        req.afeBlock   = afe
        req.vgainValue = args.vgain
        _, rep = v2_rpc(sock, pb_high.MT2_WRITE_AFE_VGAIN_REQ, req)
        msg = pb_low.cmd_writeAFEVGAIN_response()
        msg.ParseFromString(rep.payload)
        print(f"[VGAIN AFE{afe}] success={msg.success} :: {msg.message}")

    # ---------- 3) AFE resets / powerstate ----------
    # do reset
    _, rep = v2_rpc(sock, pb_high.MT2_DO_AFE_RESET_REQ, pb_low.cmd_doAFEReset())
    msg = pb_low.cmd_doAFEReset_response(); msg.ParseFromString(rep.payload)
    print(f"[AFE DO_RESET] success={msg.success} :: {msg.message}")

    # power on
    req = pb_low.cmd_setAFEPowerState(); req.powerState = True
    _, rep = v2_rpc(sock, pb_high.MT2_SET_AFE_POWERSTATE_REQ, req)
    msg = pb_low.cmd_setAFEPowerState_response(); msg.ParseFromString(rep.payload)
    print(f"[AFE POWER] success={msg.success} :: {msg.message}")

    # ---------- 4) AFE function programming ----------
    def prog_fun(afe, name, val):
        r = pb_low.cmd_writeAFEFunction()
        r.afeBlock = afe; r.function = name; r.configValue = val
        _, rep2 = v2_rpc(sock, pb_high.MT2_WRITE_AFE_FUNCTION_REQ, r)
        m = pb_low.cmd_writeAFEFunction_response(); m.ParseFromString(rep2.payload)
        print(f"[{name} AFE{afe}] success={m.success} :: {m.message}")

    for afe in range(5):
        prog_fun(afe, "SERIALIZED_DATA_RATE", 1)
        prog_fun(afe, "ADC_OUTPUT_FORMAT",   1)
        prog_fun(afe, "LPF_PROGRAMMABILITY", lpf_code)
        prog_fun(afe, "PGA_INTEGRATOR_DISABLE", int(not args.enable_integrators))
        prog_fun(afe, "PGA_CLAMP_LEVEL", pga_clamp)
        prog_fun(afe, "ACTIVE_TERMINATION_ENABLE", 0)
        prog_fun(afe, "LNA_INPUT_CLAMP_SETTING", lna_clamp)
        prog_fun(afe, "LNA_GAIN", lna_gain)
        prog_fun(afe, "LNA_INTEGRATOR_DISABLE", int(not args.enable_integrators))

    # ---------- 5) Align AFEs (optional) ----------
    if args.align_afes:
        _, rep = v2_rpc(sock, pb_high.MT2_ALIGN_AFE_REQ, pb_low.cmd_alignAFEs())
        msg = pb_low.cmd_alignAFEs_response(); msg.ParseFromString(rep.payload)
        print(f"[ALIGN] success={msg.success} :: {msg.message}")

    sock.close()

if __name__ == "__main__":
    sys.exit(main())
