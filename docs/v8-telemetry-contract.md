# Proposed-v8 DAPHNE telemetry contract

## Boundary and topology

The DAPHNE process is the producer for board-owned state. It does not host an
OPC-UA stack and an OPC-UA client cannot consume its protobuf messages without
an adapter. The deployed data path is:

```text
DAPHNE inner logic and collectors
  -> daphne.telemetry.v8 protobuf
  -> ControlEnvelopeV2 over ZeroMQ/TCP
  -> daphne-sc ZMQ client and OPC-UA server
  -> OPC-UA clients (Ignition/DCS)
```

For a source-level walkthrough, start with
[`v8-code-path.md`](v8-code-path.md). The server branch-divergence decisions are
recorded in [`server-branch-audit.md`](server-branch-audit.md).

Configuration used for data taking remains DAQ-owned. Slow Controls owns the
configuration and supervision needed to keep the endpoint powered, safe, and
available. The board snapshot can report active configuration as readback, but
does not turn an SC consumer into the authority for DAQ configuration.

## Wire contract

- Schema: `srcs/protobuf/daphne_v8_telemetry.proto`
- Request: `MT2_READ_TELEMETRY_SNAPSHOT_REQ` (`1002`)
- Response: `MT2_READ_TELEMETRY_SNAPSHOT_RESP` (`1003`)
- Envelope: existing `ControlEnvelopeV2`
- Schema version: `1.0`
- Registry revision: proposed PDS/DAQ ICD v8 draft dated 2026-08-17

The response repeats the request sequence, identifies the board and schema,
and carries per-point type, engineering unit, source, quality, source timestamp,
and optional diagnostic detail. Enum and field numbers are append-only after a
release. The schema SHA-256 is the hash of the canonical `.proto` source used
for the build.

The board-owned catalog is generated from Interface2's exported
`interface-data/daphne/exports/tag_list.csv`:

```bash
scripts/generate_v8_telemetry_catalog.py \
  ../Interface2/interface-data/daphne/exports/tag_list.csv \
  srcs/server_controller/v8_telemetry_catalog.inc \
  --expected 1370
```

Do not edit the generated include manually. The generator excludes the
`Authority`, `Endpoint Status`, and `OPC-UA Bridge` subsystems because their
normal producers are outside DAPHNE. The current HD inventory expands 316
board-owned patterns into 1,370 points.

## Quality rules

- `GOOD`: a real readback or authoritative local state is available.
- `STALE`: the last valid cached sample is older than five seconds.
- `INVALID`: a value was obtained but cannot safely be interpreted or trusted.
- `UNAVAILABLE`: the source is absent, disabled, or has not produced data.
- `NOT_APPLICABLE`: the point does not apply to the installed hardware profile.

Unavailable values have no protobuf `oneof` value. Numeric zero is never used
as a substitute for missing data. The bridge maps these qualities to OPC-UA
`Good`, `UncertainLastUsableValue`, `BadInvalidState`,
`BadWaitingForInitialData`, and `BadNotSupported`, respectively, and preserves
the source timestamp.

Cached board-rail and HD-mezzanine monitor samples carry the monitor sample
time rather than the snapshot creation time. ZMQ routing identities are not
authenticated principals; any recorded requester or authority derived from
them is marked invalid.

## Commissioning mode

Use `--telemetry-only` on a spare endpoint for side-by-side validation. This
mode:

- registers only the telemetry request handler;
- skips HD-mezzanine, regulator, ADS7138, and SPI current-monitor construction;
- disables monitoring threads and streaming handlers;
- performs only sysfs/procfs/service reads and FPGA MMIO reads.

The legacy FPGA mapping classes open `/dev/mem` read/write even though this
collector issues no writes. Consequently, telemetry-only mode reduces the
command surface and avoids peripheral configuration but is not an OS-enforced
read-only sandbox.

I²C/PMBus/HD live values remain unavailable in this mode. In the full server,
they become Good only after real driver initialization or a valid monitor
sample, and cached measurements become Stale after five seconds without a
successful refresh.

## Register-map hold

The local `FpgaRegDict` assigns physical addresses `0x9400002C`,
`0x94000030`, and `0x94000034` to `idSlot`, `idCrate`, and `idDetector`.
Another proposed map assigns those addresses to self-trigger configuration,
delay, and filter readbacks. The collector therefore publishes the identity
fields but withholds the three conflicting self-trigger raw fields and emits a
diagnostic. Resolve and version this map with firmware before enabling those
readbacks.

## Consumer validation

The bridge must reject a snapshot if its schema major, board ID, request
sequence, point prefix, or NodeId uniqueness is wrong. A complete HD bridge
instance exposes 1,416 typed read nodes and 21 non-executable policy methods;
the remaining 46 read nodes are supplied by the gateway or external authority
services rather than this 1,370-point board snapshot.
