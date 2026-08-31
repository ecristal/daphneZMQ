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
- Full-stream owns 32 32-bit mux selector shadow words at `0xA0020000` through
  `0xA002007C` and an activation control word at `0xA0020080`. It never
  accesses the `0xA0010000` block or the legacy self-trigger control fields.
  Trigger-counter RPCs return unsupported.

For full-stream, `full_stream_channels` is ordered: list element 0 feeds output
0, list element 1 feeds output 1, and so on. The list must contain 1 through 32
unique board channels in the range 0 through 39. An empty list is rejected
before any hardware access. Board channel `n` is encoded as
`((n / 8) << 4) | (n % 8)`; gateware applies the physical PL AFE
permutation only when selecting sample data so packet channel IDs remain in
board order. Every unused output is written as `0xFF`.

Control bit 0 is the enable/commit request and read-only bit 1 acknowledges that
the stream-clock domain is active. Full-stream configuration is fail-safe: the
server process also clears bit 0 and waits for bit 1 to clear immediately after
identity admission and before constructing any hardware drivers. Configuration
again clears bit 0 and waits for bit 1 to clear, then writes and verifies all
32 shadow selectors as `0xFF`, and performs reset, analog setup, and optional
AFE alignment while outputs remain disabled. It then writes and verifies the
requested shadow plan and commits all selectors atomically with one bit-0
write. A failed activation clears the gate and restores every shadow selector
to `0xFF`.

## Client integration status

The protobuf schema contains `full_stream_channels`. `daphnemodules` 3.0.4
serializes and validates the ordered list for full-stream operation; its empty
list remains the explicit self-trigger selection. Earlier `daphnemodules`
versions do not support full-stream selection.
