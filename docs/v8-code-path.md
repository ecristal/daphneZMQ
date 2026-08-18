# V8 telemetry code path: start here

This is the shortest route through the implementation. The transport contract
and all 1,370 board-owned points are unchanged; the code is split only at real
boundaries so the request can be followed without reading the legacy handlers.

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
| 1 | `srcs/protobuf/daphne_v8_telemetry.proto` | Canonical wire schema. |
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

`v8_telemetry_catalog.inc` is generated data, not hand-written logic. It is the
expanded list of NodeIds and declared types. Regenerate it from the Interface2
CSV with:

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
2. Regenerate `v8_telemetry_catalog.inc`.
3. Add the real readback to `CollectHardwareSnapshot`, `CollectRuntimeTelemetry`, or
   the platform collector in `v8_telemetry.cpp`.
4. Change the `.proto` only when the wire model itself changes. Adding a normal
   variable does not require a new protobuf field because values are carried as
   typed `TelemetryPoint` records.
5. Rebuild and run `ctest`.

Do not add DAQ-owned settings as SC commands. The telemetry path may report
active DAQ configuration as readback; DAQ remains the configuration authority.
