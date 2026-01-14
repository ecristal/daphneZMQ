#!/usr/bin/env python3
# Align all DAPHNE V3 AFEs using only 'devmem' (no poke/peek).
# Runs with sudo automatically.

import os, sys, shutil, subprocess

DEVMEM = shutil.which("devmem") or "/sbin/devmem"

# --- Address map (these match your running image) ---
FRONTEND_CTRL     = 0x88000000  # [0]=idelayctl_rst, [1]=iserdes_rst, [2]=idelay_en_vtc
FRONTEND_TRIGGER  = 0x88000008  # write 0xBABA to snapshot spies
AFE_TAP_BASE      = 0x8800000C  # +4*afe (0..4)
AFE_BITSLIP_BASE  = 0x88000020  # +4*afe (0..4)
SPY_FCLK_AFE0     = 0x90008000  # first 32b word of AFE0 spy
SPY_STRIDE        = 0x00009000  # add per AFE
TRIG_MAGIC        = 0xBABA
WANT_PATTERN      = 0x00FF00FF

def require_root():
    if os.geteuid() != 0 and shutil.which("sudo"):
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

def run(args, desc):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode != 0:
        # devmem errors land in stderr; propagate clearly
        raise RuntimeError(f"{desc} failed (rc={p.returncode}): {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()

def read32(addr, desc="read"):
    out = run([DEVMEM, f"0x{addr:08x}", "32"], desc)
    # util-linux devmem prints like "0x00000001"
    return int(out.split()[0], 16)

def write32(addr, value, desc="write"):
    run([DEVMEM, f"0x{addr:08x}", "32", f"0x{value:x}"], desc)

def tap_addr(afe):     return AFE_TAP_BASE     + 4*afe
def bitslip_addr(afe): return AFE_BITSLIP_BASE + 4*afe
def spy_addr(afe):     return SPY_FCLK_AFE0    + SPY_STRIDE*afe

def trigger_spy():
    write32(FRONTEND_TRIGGER, TRIG_MAGIC, "trigger spy")

def read_fclk(afe):
    trigger_spy()
    return read32(spy_addr(afe), f"read AFE{afe} FCLK")

def align_one_afe(afe):
    print(f"\n=== AFE{afe} ===")

    # Resets: assert idelayctl then iserdes, then release
    write32(FRONTEND_CTRL, 0x1, "assert IDELAYCTL_RST")
    write32(FRONTEND_CTRL, 0x2, "assert ISERDES_RST")
    write32(FRONTEND_CTRL, 0x0, "release resets")

    # Prime
    write32(tap_addr(afe), 0x0, f"AFE{afe} set TAP=0")
    base = read_fclk(afe)

    # Find longest stable run of identical FCLK word over taps 0..511
    longest = (1, 0, 0, base)  # (len, start, end, word)
    curr_word = base
    curr_len, start = 1, 0

    for i in range(1, 512):
        write32(tap_addr(afe), i, f"AFE{afe} TAP={i}")
        val = read_fclk(afe)
        if val == curr_word:
            curr_len += 1
        else:
            # close the previous run
            end = i - 1
            if curr_len > longest[0]:
                longest = (curr_len, start, end, curr_word)
            # start a new run
            curr_word = val
            curr_len, start = 1, i

    # close final run
    end = 511
    if curr_len > longest[0]:
        longest = (curr_len, start, end, curr_word)

    L, a, b, word = longest
    mid = a + (b - a)//2
    write32(tap_addr(afe), mid, f"AFE{afe} set TAP mid")
    print(f"AFE{afe}: window {a}..{b} (len={L}), pattern=0x{word:08x} → TAP={mid}")

    # Pulse VTC (temperature tracking)
    write32(FRONTEND_CTRL, 0x4, "enable VTC")
    write32(FRONTEND_CTRL, 0x0, "disable VTC")

    # Bitslip hunt
    found = None
    for j in range(16):
        write32(bitslip_addr(afe), j, f"AFE{afe} bitslip={j}")
        val = read_fclk(afe)
        print(f"  bitslip {j:2d} → FCLK=0x{val:08x}")
        if val == WANT_PATTERN:
            found = j
            break

    if found is None:
        print(f"AFE{afe}: WARNING — 0x{WANT_PATTERN:08x} never observed; keeping TAP={mid}.")
    else:
        print(f"AFE{afe}: FOUND 0x{WANT_PATTERN:08x} at bitslip={found}")

    return mid, found

def main():
    require_root()

    results = []
    for afe in range(5):  # attempt AFE0..AFE4
        try:
            # quick probe: ensure TAP register exists for this AFE
            _ = read32(tap_addr(afe), f"probe AFE{afe} TAP (readback allowed)")
            mid, bs = align_one_afe(afe)
            results.append((afe, mid, bs))
        except Exception as e:
            print(f"AFE{afe}: skipped due to access error:\n{e}")

    print("\nSummary")
    for afe, mid, bs in results:
        print(f"  AFE{afe}: TAP={mid}, BITSLIP={'-' if bs is None else bs}")

if __name__ == "__main__":
    main()
