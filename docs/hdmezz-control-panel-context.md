# HD Mezzanine Monitoring And Control

This document records the current HD mezzanine control path, monitoring model,
API surface, client behavior, and the main implementation choices that were
added in this repo.

It is intended as future context for anyone extending the HD mezzanine support
without having to rediscover the protocol, server wiring, or client workflow.

## Scope

The HD mezzanine support now covers:

- server-side API exposure through EnvelopeV2
- configuration of one AFE mezzanine block at a time
- enable/disable state per AFE block
- power control for the 5 V and 3.3 V rails
- monitoring readback through the background monitor thread cache
- a Python CLI client
- a PyQt6 visual control panel

The implementation is split across:

- low-level driver: `srcs/DaphneI2CDrivers.hpp`, `srcs/DaphneI2CDrivers.cpp`
- shared board state: `srcs/Daphne.hpp`
- monitoring thread: `srcs/server_controller/monitoring.cpp`
- server handlers: `srcs/server_controller/handlers.cpp`
- protobuf transport and payloads:
  - `srcs/protobuf/daphneV3_low_level_confs.proto`
  - `srcs/protobuf/daphneV3_high_level_confs.proto`
- user client: `client/hdmezz_control_v2.py`

## Driver model

The HD mezzanine hardware is managed by `I2CMezzDrivers::HDMezzDriver`.

The class owns:

- per-block enable state
- per-block configuration values
- calibration values derived from the configured shunt and current range
- direct I2C readback of voltage, current, and power

The current default configuration in `srcs/DaphneI2CDrivers.hpp` is:

- `r_shunt_5V = 36e-3 ohm`
- `r_shunt_3V3 = 0.3 ohm`
- `max_current_5V_scale = 200e-3 A`
- `max_current_3V3_scale = 200e-3 A`
- `max_current_5V_shutdown = 120e-3 A`
- `max_current_3V3_shutdown = 10e-3 A`

These same defaults are mirrored in the Python client so that the CLI and the
visual tool start from the same known operating point as the C++ driver.

## Monitoring model

The HD mezzanine readback exposed by the API is cached monitoring data, not a
fresh on-demand I2C transaction.

`srcs/server_controller/monitoring.cpp` performs the measurements on the I2C-2
monitoring thread and stores them into `Daphne`:

- `HDMezz_5V_voltage`
- `HDMezz_5V_current`
- `HDMezz_3V3_voltage`
- `HDMezz_3V3_current`
- `HDMezz_5V_power`
- `HDMezz_3V3_power`

These are fixed-size arrays:

- `std::array<std::atomic<double>, 5>`

One entry exists for each AFE block `0..4`.

Only enabled blocks are monitored. The monitor thread checks
`hd->isAfeBlockEnabled(i)` before polling a given AFE block.

## Server API

### Low-level protobuf messages

The low-level payloads live in `srcs/protobuf/daphneV3_low_level_confs.proto`:

- `cmd_setHDMezzBlockEnable`
- `cmd_setHDMezzBlockEnable_response`
- `cmd_configureHDMezzBlock`
- `cmd_configureHDMezzBlock_response`
- `cmd_readHDMezzBlockConfig`
- `cmd_readHDMezzBlockConfig_response`
- `cmd_setHDMezzPowerStates`
- `cmd_setHDMezzPowerStates_response`
- `cmd_readHDMezzStatus`
- `cmd_readHDMezzStatus_response`

### High-level EnvelopeV2 message types

The EnvelopeV2 transport mapping lives in
`srcs/protobuf/daphneV3_high_level_confs.proto`:

- `MT2_SET_HDMEZZ_BLOCK_ENABLE_REQ = 400`
- `MT2_SET_HDMEZZ_BLOCK_ENABLE_RESP = 401`
- `MT2_CONFIGURE_HDMEZZ_BLOCK_REQ = 402`
- `MT2_CONFIGURE_HDMEZZ_BLOCK_RESP = 403`
- `MT2_READ_HDMEZZ_BLOCK_CONFIG_REQ = 404`
- `MT2_READ_HDMEZZ_BLOCK_CONFIG_RESP = 405`
- `MT2_SET_HDMEZZ_POWER_STATES_REQ = 406`
- `MT2_SET_HDMEZZ_POWER_STATES_RESP = 407`
- `MT2_READ_HDMEZZ_STATUS_REQ = 408`
- `MT2_READ_HDMEZZ_STATUS_RESP = 409`

## Server handlers

The request handling is implemented in `srcs/server_controller/handlers.cpp`.

The helper functions are:

- `setHDMezzBlockEnable(...)`
- `configureHDMezzBlock(...)`
- `readHDMezzBlockConfig(...)`
- `setHDMezzPowerStates(...)`
- `readHDMezzStatus(...)`

The V2 dispatch table registers handler lambdas for the five `MT2_*` request
types listed above.

### Safety and robustness points

The handler path includes three important protections:

- null-driver protection
  - each HD mezz helper checks `daphne.getHDMezzDriver()`
  - if the driver is unavailable, the handler returns a controlled error
    instead of risking a null dereference

- I2C-2 configuration guard
  - configuration and power-control operations raise
    `daphne.isI2C_2_device_configuring`
  - this blocks the monitoring thread from polling the same bus concurrently
  - the implementation uses a scoped RAII guard so the flag is always cleared
    on both success and exception paths

- cached readout
  - `readHDMezzStatus(...)` reads the already-cached `Daphne` atomics
  - this avoids mixing live reads with the background monitor thread

## Current unit convention

The values currently returned by the server and displayed by the Python client
are:

- voltage in `V`
- current in `mA`
- power in `mW`

Configuration values are displayed as:

- shunts in `ohm`
- current scales and shutdown thresholds in `A`
- max power in `W`
- current LSB in `A/LSB`

## Important behavior notes

### Enable and configure order matters

Useful HD mezz operation follows this order:

1. enable the AFE block
2. configure the AFE block
3. set power states
4. wait for the monitor thread to refresh
5. read status

If a block is not enabled, the monitor thread skips it.

### Rail-off readback can still show voltage

Turning off the mezz power switch does not necessarily force the measured bus
voltage to zero. The INA232 bus-voltage measurement can still see the upstream
rail while the load current collapses to zero.

A plausible rail-off readback is therefore:

- voltage still present
- current near zero
- power near zero

This is expected behavior for this topology.

## Current signedness fix

During validation, a rail-off state produced current values near full scale,
for example about `399.98 mA`, which is not physically correct for an unloaded
path.

The root cause was the current register decode in
`srcs/DaphneI2CDrivers.cpp`:

- the INA232 current register had been interpreted as `uint16_t`
- near-zero negative values wrapped to the top of the range

The fix was applied in:

- `readRailCurrent5V(...)`
- `readRailCurrent3V3(...)`

These functions now interpret the current register as `int16_t` before
applying the current-LSB scaling.

This keeps small negative or noise values from wrapping to near-full-scale
positive current.

## Python client

The user-facing client is:

- `client/hdmezz_control_v2.py`

It supports both CLI mode and visual mode.

### CLI commands

- `set-block-enable`
- `configure-block`
- `read-block-config`
- `set-power-states`
- `read-status`

The `configure-block` command now uses the HD mezz defaults automatically, so
all config values do not need to be provided every time.

Example:

```bash
python client/hdmezz_control_v2.py configure-block --ip 193.206.157.36 --port 9876 --afe 4
```

### Visual mode

Launch with:

```bash
python client/hdmezz_control_v2.py --visual --ip 193.206.157.36 --port 9876
```

The visual client is implemented with PyQt6 and currently provides:

- one panel per AFE block
- horizontal layout per block
- enable and power switches
- knob-like controls for configuration parameters
- config readback
- status readback
- seven-segment style telemetry displays using `QLCDNumber`
- a console log pane

The current window title is:

- `HD MEZZANINE CONTROL PANEL`

## Practical validation sequence

A good manual validation sequence is:

1. enable one AFE block
2. configure the block
3. enable 5 V and 3.3 V power
4. wait one or two monitoring cycles
5. read status
6. turn rails off and verify voltage/current/power behavior remains plausible

## Known assumptions

- the read-status API returns cached monitoring values, not direct live reads
- the HD mezz driver may be unavailable on systems where initialization fails
- the monitor thread and configuration path share I2C bus 2 and must remain
  coordinated through `isI2C_2_device_configuring`

## Future extension ideas

- add periodic auto-refresh in the visual client
- expose block-enabled state in the status payload if desired
- add richer alert-state readback from the INA232 path
- add a compact multi-block summary view in the visual panel
