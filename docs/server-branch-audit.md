# DAPHNE server branch-divergence audit

Audit baseline: `feature/slow-control-emulator` at `578346b`, whose parent
already contains `origin/main` at `b18075e`.

Most remote feature branches are ancestors of the baseline and therefore do
not contain missing work. Four branch tips report commits not reachable from
the baseline; their status is below.

| Branch | Unique work | Disposition |
|---|---|---|
| `marroyav/ps-system-status-protobuf` | Adds messages 324/325 and a second, string-heavy system-status schema, but no server handler or collector. | Superseded by the typed v8 snapshot (1002/1003). Do not merge both monitoring contracts. |
| `feature/read_dead_time` | Adds the former spy-buffer dead-time bit and moves/removes several FPGA register definitions. | Deprecated. New firmware uses `Spy.Trigger.SourceSelector` and `Spy.Trigger.Inhibit` at `FRONT_END_S_AXI+0x34`; do not merge the legacy bit. Its register-map edits also conflict with the versioned-map work. |
| `marroyav/server_threshold_xc` | Changes trigger thresholds to 28 bits. | Functionality is already present in the baseline in a newer implementation (`MASK_28BIT`, explicit threshold-source selection, readback). Do not duplicate it. |
| `marroyav/server_bringup_thresholds` | Carries the same threshold change plus endpoint-script policy and documentation. | Threshold logic is already present. Review the endpoint success-state policy separately; it changes service admission behavior and is not a telemetry merge. |

## Result for the v8 path

There is no missing branch-only telemetry implementation that should be copied
into the new producer. The only branch-only monitoring proposal is a schema
without implementation, and the v8 contract replaces it with typed values,
quality, timestamps, source, diagnostics, filtering, and a generated registry.

Future hardware features should enter through a versioned register-map adapter
and a collector. They should not redefine addresses directly inside a feature
branch or add another top-level status protobuf.
