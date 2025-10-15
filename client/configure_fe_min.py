import zmq, sys, os

# Import generated protos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high

def set_adc_fields(adc, *, resolution=True, output_format=True, sb_first=True):
    # Be robust to sb_first vs SB_first naming
    if hasattr(adc, "resolution"):      adc.resolution = resolution
    if hasattr(adc, "output_format"):   adc.output_format = output_format
    for name in ("sb_first", "SB_first"):
        if hasattr(adc, name):
            setattr(adc, name, sb_first)
            break

def make_default_config(
    ip="10.73.137.161",
    slot=0,
    timeout_ms=500,
    biasctrl=1300,
    self_trigger_threshold=0x1F40,  # 8000
    self_trigger_xcorr=0x68,
    tp_conf=0x0010DB35,
    compensator=0xFFFFFFFFFF,       # 48-bit in uint64
    inverters=0xFF00000000,         # 48-bit in uint64
    per_ch_trim=0,
    per_ch_offset=2275,
):
    cfg = pb_high.ConfigureRequest()
    cfg.daphne_address         = ip
    cfg.slot                   = slot
    cfg.timeout_ms             = timeout_ms
    cfg.biasctrl               = biasctrl
    cfg.self_trigger_threshold = self_trigger_threshold
    cfg.self_trigger_xcorr     = self_trigger_xcorr
    cfg.tp_conf                = tp_conf
    cfg.compensator            = compensator
    cfg.inverters              = inverters

    # 40 channels
    for ch in range(40):
        c = cfg.channels.add()
        c.id     = ch
        c.trim   = per_ch_trim
        c.offset = per_ch_offset
        c.gain   = 1

    # 5 AFEs
    # NOTE: server passes LPF code straight to FW; for 10 MHz, code=4 in your setup/logs
    for afe in range(5):
        a = cfg.afes.add()
        a.id          = afe
        a.attenuators = 1600
        a.v_bias      = 0
        set_adc_fields(a.adc, resolution=True, output_format=True, sb_first=False)
        a.pga.lpf_cut_frequency  = 4
        a.pga.integrator_disable = True
        a.pga.gain              = 0
        a.lna.clamp               = 0
        a.lna.gain                = 2
        a.lna.integrator_disable  = True

    # optional: cfg.full_stream_channels.extend([])
    return cfg

def main(host="127.0.0.1", port=9876):
    ctx = zmq.Context.instance()
    s   = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.IDENTITY, b"client-compat")  # ROUTER expects an identity frame
    s.connect(f"tcp://{host}:{port}")

    cfg = make_default_config(ip=host)

    env = pb_high.ControlEnvelope()
    env.type = pb_high.CONFIGURE_FE
    env.payload = cfg.SerializeToString()

    s.send(env.SerializeToString())

    # ROUTER replies as [id][payload]; DEALER receives both; last frame is payload
    frames = [s.recv()]
    while s.getsockopt(zmq.RCVMORE):
        frames.append(s.recv())
    reply_bytes = frames[-1]

    reply_env = pb_high.ControlEnvelope()
    reply_env.ParseFromString(reply_bytes)
    if reply_env.type != pb_high.CONFIGURE_FE:
        print(f"Unexpected reply type: {reply_env.type}")
        return 1

    out = pb_high.ConfigureResponse()
    out.ParseFromString(reply_env.payload)
    print("Success:", out.success)
    print("Message:\n", out.message)
    return 0

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9876
    sys.exit(main(host, port))
