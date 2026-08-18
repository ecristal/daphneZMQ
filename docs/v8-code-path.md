# V8 telemetry code path: start here

This is the shortest route through the implementation. Schema 2.0 declares
all 316 board-variable patterns as named Protobuf fields. Repeated hardware
families carry explicit instance keys, producing 1,370 samples for one HD
board. The code is split only at real boundaries so the request can be
followed without reading the legacy handlers.

```text
request 1002
  -> MakeHardwareSnapshotHandler()
  -> CollectHardwareSnapshot()
  -> SnapshotBuilder
  -> response 1003
```

## Files in reading order

| Step | File and symbol | Responsibility |
|---|---|---|
| 1 | `srcs/protobuf/daphne_v8_telemetry.proto` | Canonical wire schema: request, response, all 316 board-variable fields, value types, quality, timestamps, ownership, source, unit, and OPC-UA pattern. |
| 2 | `srcs/server_controller/v8_telemetry_service.cpp`: `MakeSnapshotHandler` | Parse the request and serialize the response. This is the only protobuf-facing handler. |
| 3 | `srcs/server_controller/v8_hardware_telemetry.cpp`: `CollectHardwareSnapshot` | Orchestrate host, runtime, cached-monitor, and MMIO collection. |
| 4 | `srcs/server_controller/v8_telemetry.cpp`: `SnapshotBuilder` | Enforce catalog types, quality/value rules, timestamps, filtering, and unavailable values. `CollectPlatformTelemetry` visibly sequences the Linux/platform collectors. |
| 5 | `srcs/server_controller/v8_telemetry_runtime.cpp`: `CollectRuntimeTelemetry` | Publish active DAQ configuration readback and last-command audit state. |
| 6 | `srcs/server_controller/router_server.cpp`: `run_router_server` | Carry the serialized protobuf inside `ControlEnvelopeV2` over ZMQ. This code is generic and contains no telemetry fields. |

The emulator uses the same step 2 handler. It substitutes
`EmulatedDaphneBackend::read_telemetry_snapshot` for the hardware collector.

## Spy-trigger firmware transition

The v8 path does not implement `spyBufferDeadtimeEnable`. That older feature
branch is deprecated because current firmware exposes an atomic trigger-source
selector and inhibit at `FRONT_END_S_AXI+0x34`:

- `Spy.Trigger.SourceSelector` is bits `[1:0]` (`0` software, `1` external,
  `2` timing/ad-hoc, `3` legacy/all).
- `Spy.Trigger.Inhibit` is bit `[2]`.

The hardware collector reads both values together. The emulator publishes the
firmware reset state (`3`, `false`) so the complete protobuf/ZMQ/OPC-UA chain
can be tested without hardware. There is deliberately no dead-time point in the
generated catalog.

## Files not to read first

`daphne_v8_telemetry.proto` and `v8_telemetry_catalog.inc` are generated data,
not hand-written logic. Generate both from the reviewed Interface2 CSV. The
trace CSV is the append-only Protobuf field-number ledger:

```sh
scripts/generate_v8_explicit_proto.py \
  ../Interface2/interface-data/daphne/exports/tag_list.csv \
  srcs/protobuf/daphne_v8_telemetry.proto \
  --trace ../Interface2/interface-data/daphne/exports/protobuf_field_trace.csv
```

The expanded catalog is the server collector's NodeId lookup:

```sh
scripts/generate_v8_telemetry_catalog.py \
  ../Interface2/interface-data/daphne/exports/tag_list.csv \
  srcs/server_controller/v8_telemetry_catalog.inc \
  --expected 1370
```

The large legacy `handlers.cpp` contains all older DAPHNE commands. For v8 it
only associates message type `1002` with `MakeHardwareSnapshotHandler()`.

## Adding or changing one variable

1. Change the canonical Interface2 workbook and regenerate `tag_list.csv`.
2. Regenerate `daphne_v8_telemetry.proto`, its field trace, and
   `v8_telemetry_catalog.inc`.
3. Review the new named field, field number, type, instance keys, NodeId
   pattern, unit, source, and owner in the `.proto` and trace CSV.
4. Add the real readback to `CollectHardwareSnapshot`,
   `CollectRuntimeTelemetry`, or the platform collector in `v8_telemetry.cpp`.
5. Copy the reviewed `.proto` byte-for-byte to
   `daphne-sc/proto/upstream`, then rebuild and run both repositories' tests.

Never reuse or renumber a released Protobuf field number. A variable is not in
the v8 wire contract until its named field is present in the `.proto`.

Do not add DAQ-owned settings as SC commands. The telemetry path may report
active DAQ configuration as readback; DAQ remains the configuration authority.
This snapshot request/response does not define configuration writes. Existing
DAQ command messages remain in `daphneV3_high_level_confs.proto`; any new DAQ
write must be declared there (and in `daphnemodules`), not invented by the
OPC-UA bridge.
