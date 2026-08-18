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
- Schema version: `2.0`
- Registry revision: proposed PDS/DAQ ICD v8 explicit-field draft dated
  2026-08-18

The response repeats the request sequence, identifies the board and schema,
and contains `BoardTelemetry`. Its 316 named fields declare every board-owned
variable pattern individually. A scalar variable has a typed sample directly;
an indexed family has a typed repeated wrapper with explicit hardware keys
such as `afe`, `channel`, `bus`, or `address`. Field annotations declare its
OPC-UA NodeId pattern, engineering unit, source, and control owner. Each sample
carries quality, source timestamp, and optional diagnostic detail. Enum and
field numbers are append-only after a release. The schema SHA-256 is the hash
of the canonical `.proto` source used for the build.

The bridge reads those compiled declarations mechanically. It does not own a
parallel variable-name/type table and cannot create an undeclared DAPHNE
telemetry field. The reviewable one-row-per-field ledger is
`Interface2/interface-data/daphne/exports/protobuf_field_trace.csv`. Retired
ledger entries remain reserved in Protobuf, preventing accidental reuse of a
released field number or name.

The explicit schema and board-owned catalog are generated from Interface2's
exported `interface-data/daphne/exports/tag_list.csv`:

```bash
scripts/generate_v8_explicit_proto.py \
  ../Interface2/interface-data/daphne/exports/tag_list.csv \
  srcs/protobuf/daphne_v8_telemetry.proto \
  --trace ../Interface2/interface-data/daphne/exports/protobuf_field_trace.csv
```

```bash
scripts/generate_v8_telemetry_catalog.py \
  ../Interface2/interface-data/daphne/exports/tag_list.csv \
  srcs/server_controller/v8_telemetry_catalog.inc \
  --expected 1370
```

Do not edit either generated contract manually. The generators exclude the
`Authority`, `Endpoint Status`, and `OPC-UA Bridge` subsystems because their
normal producers are outside DAPHNE. The current HD inventory expands 316
board-owned fields into 1,370 keyed samples.

The snapshot protocol is deliberately read-only: request `1002` identifies the
request sequence and response `1003` returns the complete explicit telemetry
message. DAQ configuration commands remain in the DAQ-owned high-level
configuration protobuf and `daphnemodules`. Adding a write path requires a
reviewed request and response contract; the bridge must not infer one from an
OPC-UA node.

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
sequence, declared field annotations, rendered NodeId, instance keys, or NodeId
uniqueness is wrong. A complete HD bridge
instance exposes 1,416 typed read nodes and 21 non-executable policy methods;
the remaining 46 read nodes are supplied by the gateway or external authority
services rather than this 1,370-point board snapshot.
