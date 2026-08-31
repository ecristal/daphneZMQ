# Gateware mode and register ABI contract

`daphneServer` requires an operator-selected gateware mode:

```bash
daphneServer --gateware-mode self-trigger \
  --expected-gateware-build-id 0x01234567

daphneServer --gateware-mode full-stream \
  --expected-gateware-build-id 0x09ABCDEF
```

Before constructing the hardware-control objects or issuing any MMIO write, the
server reads the common identity block:

| Address | Required value |
| --- | --- |
| `0x940000F0` | magic `0x44415048` (`DAPH`) |
| `0x940000F4` | register ABI `0x00020000` |
| `0x940000F8` | variant `1` (self-trigger) or `2` (full-stream) |
| `0x940000FC` | release-specific 32-bit build ID |

The build ID is the first seven hexadecimal characters of the gateware commit
SHA, zero-extended to 32 bits; its upper nibble is therefore always zero.

A magic, ABI, variant, or supplied build-ID mismatch fails closed before MMIO
writes and exits with status 78. Omitting `--expected-gateware-build-id` is
allowed for local development and produces a prominent warning; production
service profiles must always supply the release manifest's build ID.

## Register ownership

- Self-trigger owns trigger thresholds and counters at `0xA0010000`, plus the
  self-trigger control fields in the common `0x94000000` block. A configure
  request in this mode must have an empty `full_stream_channels` field.
- Full-stream owns 32 32-bit mux selector words at `0xA0020000` through
  `0xA002007C`. It never accesses the `0xA0010000` block or the legacy
  self-trigger control fields. Trigger-counter RPCs return unsupported.

For full-stream, `full_stream_channels` is ordered: list element 0 feeds output
0, list element 1 feeds output 1, and so on. The list may contain at most 32
unique board channels in the range 0 through 39. Board channel `n` is encoded
as `((n / 8) << 4) | (n % 8)`. Every unused output is written as `0xFF`.

Full-stream configuration is fail-safe: the server first writes and verifies
all 32 selectors as `0xFF`, performs reset, analog setup, and optional AFE
alignment while outputs remain disabled, then writes and verifies the requested
active plan. A failed activation is followed by a complete all-`0xFF` restore.

## Client integration status

The protobuf schema already contains `full_stream_channels`, and direct v2
clients can populate it. The current daphnemodules V3 configuration path does
not serialize that field, so it cannot yet select full-stream outputs. That is
an external integration blocker: update daphnemodules and its configuration
schema before declaring the full-stream release path automatic end to end.
