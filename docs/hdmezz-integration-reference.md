# HD Mezzanine Control and Integration Reference

## Purpose and scope

This document defines the implemented HD mezzanine communication contract in `daphneZMQ`. It is intended for another application that must control or monitor the HD mezzanine through `daphneServer` without depending on the existing Python UI.

It covers:

- physical I2C topology and device addresses;
- server-side state and safety behavior;
- configuration values, validation, and INA232 scaling;
- ZeroMQ and Protocol Buffers request/response framing;
- command payloads and message IDs;
- correct operating sequences;
- telemetry units and freshness;
- compatibility constraints;
- validation and deployment recommendations.

The preferred integration boundary is the ZeroMQ/Protobuf API. Direct access to `/dev/i2c-2` should be reserved for diagnostics because it bypasses server locking, cached state, monitoring, and safety sequencing.

## Terminology: CE versus legacy `3V3`

The second monitored HD-mezzanine path is electrically **CE**, not a generic 3.3 V supply rail.

User-facing applications should display this path as **CE**. However, the current protobuf schema and some internal C++ identifiers retain `3V3` in their names for wire and source compatibility. Therefore:

| User-visible meaning | Current protobuf/internal name |
|---|---|
| CE power request | `power3V3` |
| CE shunt resistance | `r_shunt_3V3` |
| CE current scale | `max_current_3V3_scale` |
| CE cutoff | `max_current_3V3_shutdown` |
| CE voltage/current/power | `measured_*3V3` |
| CE alert | `alert_3V3` |

Do not reinterpret those legacy field names as a different physical rail. Their protobuf field numbers must not be changed in a compatible implementation.

## Architecture

```text
External application
    |
    | ZeroMQ DEALER -> ROUTER, TCP port 9876 by default
    | ControlEnvelopeV2 + command-specific protobuf payload
    v
daphneServer
    |
    | handler serialization + i2c_2_mutex
    v
HDMezzDriver
    |
    | /dev/i2c-2
    v
TCA9548-style mezzanine mux, address 0x71
    |
    +-- AFE0: mux byte 0x01
    +-- AFE1: mux byte 0x02
    +-- AFE2: mux byte 0x04
    +-- AFE3: mux byte 0x08
    +-- AFE4: mux byte 0x10
         |
         +-- INA232 CE       0x40
         +-- TCA9536 GPIO    0x41
         +-- INA232 5V       0x42
```

Every downstream operation selects the AFE mux channel immediately before accessing the target device. The HD driver also has an internal mutex. Server handlers and the monitoring thread coordinate through the server's `i2c_2_mutex`.

A separate process must not access `/dev/i2c-2` while `daphneServer` is operating. The mux selection and downstream transfer form one logical transaction and must not be interleaved.

## Low-level I2C behavior

### Register reads

INA232 register reads use Linux `I2C_RDWR` with two messages:

1. write the one-byte register pointer;
2. repeated-start and read the requested bytes.

This is a combined transaction, not independent `write()` and `read()` calls. Word registers are transferred most-significant byte first.

Interrupted system calls are retried. Short transfers and ioctl errors raise contextual exceptions containing the adapter path, slave address, and register address.

### Device probing

Enabling an AFE block performs a safe GPIO initialization and then probes:

- TCA9536 output/configuration registers;
- INA232 manufacturer ID register `0x3E` at `0x40` and `0x42`.

Both INA232 devices must return manufacturer ID `0x5449`. A wrong ID or I2C failure prevents the block from becoming enabled.

## GPIO and power-request semantics

TCA9536 register usage:

| Register | Address | Use |
|---|---:|---|
| Input port | `0x00` | GPIO input state |
| Output port | `0x01` | 5V and CE request latches |
| Polarity inversion | `0x02` | Standard TCA9536 register |
| Configuration | `0x03` | GPIO direction |

The safe configuration writes output bits low before changing their direction:

- P0: 5V request;
- P1: CE request;
- P2/P3: inputs;
- configuration value: `0xFC` (lower nibble verifies as `0x0C` plus output/input layout; the implementation verifies the lower four bits);
- output bits 0 and 1 are verified after every change.

Power requests are updated together using one read-modify-write operation:

```text
bit 0 = requested 5V state
bit 1 = requested CE state
```

The API reports requested GPIO state, not an independent proof that electrical power is present. Use measured voltage to determine whether a rail is electrically active.

A request to turn either rail on is rejected unless the block is both enabled and configured. Requests that turn both rails off are allowed for an enabled block even when it is not configured.

## Driver state model

Each AFE block has two software state flags:

```text
Disabled
  -> enable(true) performs safe-off + identity probe
Enabled, unconfigured
  -> configure(...) performs safe-off + INA programming/readback
Enabled, configured
  -> power requests and telemetry are allowed
```

Important transitions:

- `enable(false)` always enforces hardware safe-off, even if software already considers the block disabled;
- enabling never turns rails on;
- configuration always turns both rail requests off first;
- configuration must be repeated before power-on after a disable/re-enable cycle;
- failed configuration leaves the block unconfigured and both requests off;
- failed transactional configuration restores the previous software configuration values;
- reading a detected INA232 alert immediately removes both rail requests.

## INA232 configuration

The driver programs each INA232 with verified write/readback operations.

| Register | Address | Programmed meaning |
|---|---:|---|
| Configuration | `0x00` | `0x4127` |
| Shunt calibration | `0x05` | Derived `SHUNT_CAL` |
| Mask/Enable | `0x06` | `0x8001`: SOL alert + latch enable |
| Alert limit | `0x07` | Derived shunt-over-limit threshold |
| Manufacturer ID | `0x3E` | Expected readback `0x5449` |

Dynamic/read-only bits are masked during verification where required.

### Configuration inputs

For both 5V and CE, the external API supplies:

- shunt resistance in ohms;
- maximum measurable current/full-scale current in amperes;
- shutdown/cutoff current in amperes.

All values must be finite and greater than zero. The cutoff must not exceed the measurement scale.

The following additional constraints are enforced:

```text
max_current_scale * r_shunt <= 0x7FFF * 2.5 uV
1 <= SHUNT_CAL <= 0x7FFF
1 <= alert_limit <= 0x7FFF
```

### Scaling formulas

```text
current_lsb = max_current_scale / 32768                    [A/LSB]
SHUNT_CAL   = floor(0.00512 / (current_lsb * r_shunt))
alert_limit = floor((shutdown_current * r_shunt) / 2.5e-6)
max_power   = nominal_voltage * shutdown_current            [W]
```

The alert uses INA232 **shunt-over-limit (SOL)**. It is a current-derived threshold and does not vary with bus voltage.

### Current defaults

| Parameter | 5V | CE |
|---|---:|---:|
| Shunt resistance | `0.036 ohm` | `0.300 ohm` |
| Measurement scale | `0.200 A` | `0.200 A` |
| Shutdown/cutoff | `0.120 A` | `0.050 A` |
| Current LSB | `6.103515625 uA/LSB` | `6.103515625 uA/LSB` |
| SHUNT_CAL | `23301` (`0x5B05`) | `2796` (`0x0AEC`) |
| SOL alert limit | `1728` (`0x06C0`) | `6000` (`0x1770`) |
| Derived max power | `0.600 W` | `0.165 W` |

The CE cutoff was raised from 10 mA to 50 mA after observed startup/transient alerts. A controlled alert-injection validation remains pending.

## Telemetry conversion and units

The server exposes:

| Value | Conversion in driver | API unit |
|---|---|---|
| Voltage | raw bus register × `1.6e-3` | V |
| Current | signed 16-bit raw × `current_lsb × 1000` | mA |
| Power | raw power register × `32 × current_lsb × 1000` | mW |

Current is explicitly decoded as signed 16-bit. Small negative current readings with the rails off are normal measurement offset/noise and must not be interpreted as unsigned full-scale current.

`readHDMezzStatus` returns values cached by the monitoring thread; it does not perform a synchronous hardware read. Monitoring is enabled by default with a 200 ms period and can be changed using the server's `--monitor-period-ms` option. Applications should allow at least one or two monitor periods after a state change before evaluating telemetry.

The current status response contains no timestamp or stale-data flag. A consuming application should timestamp receipt locally and treat repeated RPC failures as stale telemetry.

## ZeroMQ transport

### Endpoint and socket pattern

Default server bind endpoint:

```text
tcp://*:9876
```

The server uses a ZeroMQ `ROUTER` socket. The reference client uses a `DEALER` socket with an explicit identity and connects to:

```text
tcp://<board-address>:9876
```

A request is one serialized `ControlEnvelopeV2` frame. The ROUTER reply is delivered to the client identity; a DEALER client reads the final frame as the serialized response envelope.

Recommended client settings:

- finite send and receive timeout, for example 5000 ms;
- `ZMQ_LINGER = 0` on shutdown;
- unique or stable DEALER identity per client instance;
- only one outstanding request per DEALER socket unless the application implements correlation and concurrent dispatch.

### `ControlEnvelopeV2`

```protobuf
message ControlEnvelopeV2 {
  uint32 version      = 1;   // must be 2
  Direction dir       = 2;   // DIR_REQUEST=0, DIR_RESPONSE=1
  MessageTypeV2 type  = 3;
  bytes payload       = 4;   // serialized command message
  uint64 task_id      = 10;
  uint64 msg_id       = 11;
  uint64 correl_id    = 12;
  string route        = 13;
  uint64 timestamp_ns = 20;
}
```

For each request:

- set `version = 2`;
- set `dir = DIR_REQUEST`;
- select the request message type;
- serialize the corresponding command into `payload`;
- generate a unique nonzero `msg_id`;
- set `task_id` as desired for higher-level operation tracking;
- set `timestamp_ns` when available;
- use route `mezz/0` unless deployment routing defines another value.

For each response:

- verify `dir == DIR_RESPONSE`;
- verify the expected response type;
- verify `correl_id == request.msg_id` when `correl_id` is nonzero;
- parse `payload` as the expected response message;
- require the command response's `success` field to be true.

The deprecated `ControlEnvelope` v1 format is ignored by the v2-only router server.

## HD mezzanine RPC catalogue

| Operation | Request type | Response type | IDs |
|---|---|---|---:|
| Enable/disable block | `MT2_SET_HDMEZZ_BLOCK_ENABLE_REQ` | `..._RESP` | 400 / 401 |
| Configure block | `MT2_CONFIGURE_HDMEZZ_BLOCK_REQ` | `..._RESP` | 402 / 403 |
| Read configuration | `MT2_READ_HDMEZZ_BLOCK_CONFIG_REQ` | `..._RESP` | 404 / 405 |
| Set both power requests | `MT2_SET_HDMEZZ_POWER_STATES_REQ` | `..._RESP` | 406 / 407 |
| Read cached status | `MT2_READ_HDMEZZ_STATUS_REQ` | `..._RESP` | 408 / 409 |
| Clear cached alerts | `MT2_CLEAR_HDMEZZ_ALERT_FLAG_REQ` | `..._RESP` | 410 / 411 |

All operations use AFE block indices `0..4`.

### Enable or disable

Request payload:

```protobuf
cmd_setHDMezzBlockEnable {
  id: integer application ID
  afeBlock: 0..4
  enable: true or false
}
```

Enabling performs safe-off and identity probing. Disabling enforces safe-off and clears cached telemetry/alert state in the server.

### Configure

Request payload fields:

```text
afeBlock
r_shunt_5V
r_shunt_3V3              # CE
max_current_5V_scale
max_current_3V3_scale    # CE
max_current_5V_shutdown
max_current_3V3_shutdown # CE
```

Units are ohms and amperes. Configuration is transactional at the driver boundary: both candidate rail configurations are validated before I2C mutation; hardware is forced safe-off; both INA232 devices are programmed and verified; software configuration is committed only on success. On failure, previous software values are restored and the block remains unconfigured.

Configuration always clears both rail requests. The client must explicitly request power again after a successful configuration.

### Read configuration

The response returns configured input values plus:

- derived maximum power in W;
- current LSB in A/LSB;
- integer INA232 shunt calibration value.

The legacy `*3V3` response fields describe CE.

### Set power states

Both requested states are sent together:

```protobuf
cmd_setHDMezzPowerStates {
  int32 id       = 1;
  uint32 afeBlock = 2;
  bool power5V   = 3;
  bool power3V3  = 4; // CE
}
```

Do not implement this as two independent rail commands. A paired request avoids lost updates and intermediate mixed states.

### Read status

The response contains:

- requested 5V state;
- requested CE state (`power3V3` on the wire);
- measured voltage in V;
- measured current in mA;
- measured power in mW;
- latched server alert flags for 5V and CE.

Because the values are cached, a successful response means the server returned its state; it does not by itself prove that the most recent monitor pass succeeded.

### Clear alert flags

This command clears the server's cached alert booleans. It does not override the driver's safety behavior and must not be used to re-enable power automatically. If the hardware condition persists, monitoring may latch the alert again.

## Required operating sequence

A safe controller should use this sequence for one block:

```text
1. set block enable = true
2. configure both rails
3. read configuration and verify returned values
4. explicitly set both power requests = false
5. wait at least 1-2 monitoring periods
6. request one rail or both rails on
7. wait at least 1-2 monitoring periods
8. read status and verify requested state, voltage, current, power, alerts
9. set both power requests = false before shutdown/disconnect
10. optionally disable the block
```

Recommended bring-up progression:

1. 5V off, CE off;
2. 5V on, CE off;
3. 5V off, CE on;
4. 5V on, CE on;
5. both off.

Never infer that configuration preserves the previous power request; configuration deliberately clears it.

## Example Python integration

The repository's complete implementation is `client/hdmezz_control_v2.py`. The essential RPC pattern is:

```python
import time
import zmq
from srcs.protobuf import daphneV3_high_level_confs_pb2 as high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as low

ctx = zmq.Context.instance()
sock = ctx.socket(zmq.DEALER)
sock.setsockopt(zmq.IDENTITY, b"my-hdmezz-controller")
sock.setsockopt(zmq.LINGER, 0)
sock.setsockopt(zmq.SNDTIMEO, 5000)
sock.setsockopt(zmq.RCVTIMEO, 5000)
sock.connect("tcp://193.206.157.36:9876")

next_msg_id = time.time_ns() & ((1 << 63) - 1)
request = low.cmd_readHDMezzStatus(id=0, afeBlock=4)

envelope = high.ControlEnvelopeV2(
    version=2,
    dir=high.DIR_REQUEST,
    type=high.MT2_READ_HDMEZZ_STATUS_REQ,
    payload=request.SerializeToString(),
    task_id=next_msg_id,
    msg_id=next_msg_id,
    route="mezz/0",
    timestamp_ns=time.time_ns(),
)
sock.send(envelope.SerializeToString())

reply_envelope = high.ControlEnvelopeV2()
reply_envelope.ParseFromString(sock.recv())
assert reply_envelope.type == high.MT2_READ_HDMEZZ_STATUS_RESP
assert not reply_envelope.correl_id or reply_envelope.correl_id == envelope.msg_id

reply = low.cmd_readHDMezzStatus_response()
reply.ParseFromString(reply_envelope.payload)
if not reply.success:
    raise RuntimeError(reply.message)

print("5V", reply.measured_voltage5V, "V")
print("CE", reply.measured_voltage3V3, "V")
```

A production implementation should check protobuf parse success, envelope version/direction, response type, correlation ID, command success, and timeouts on every request.

## CLI examples

Enable and configure AFE 4:

```bash
python client/hdmezz_control_v2.py set-block-enable \
  --ip 193.206.157.36 --port 9876 --afe 4 --enable 1

python client/hdmezz_control_v2.py configure-block \
  --ip 193.206.157.36 --port 9876 --afe 4 \
  --max-current-ce-shutdown 0.05
```

Set both requests off:

```bash
python client/hdmezz_control_v2.py set-power-states \
  --ip 193.206.157.36 --port 9876 --afe 4 \
  --power-5v 0 --power-ce 0
```

Read status:

```bash
python client/hdmezz_control_v2.py read-status \
  --ip 193.206.157.36 --port 9876 --afe 4
```

The old CLI names containing `3v3` remain aliases, but new applications should use CE terminology.

## Concurrency and polling recommendations

- Serialize commands per DEALER socket.
- Do not poll faster than the server monitoring period; 500-1000 ms is appropriate for a UI.
- Keep command controls separate from observed state. Telemetry polling must update indicators, not pending ON/OFF commands.
- Never automatically resend an ON request because a status poll reports OFF. OFF may be the result of an alert or safety action.
- Treat power requests and measured voltage as separate signals.
- After configuration, disable, alert, connection loss, or server restart, require an explicit user/application decision before re-energizing rails.
- If multiple applications can control the same block, implement ownership/arbitration above this API. The server serializes bus access but does not provide per-client control leases.

## Error and recovery behavior

An application should handle these cases explicitly:

| Condition | Expected behavior |
|---|---|
| Block index outside `0..4` | Request fails |
| HD driver initialization failed | Request fails with driver unavailable |
| Enable probe/identity mismatch | Block remains disabled, rails off |
| Configure before enable | Request fails |
| Power-on before configuration | Request fails |
| Invalid configuration | No I2C mutation; request fails |
| INA/TCA write-readback mismatch | Rails remain off; block unconfigured |
| Alert observed | Both rail requests removed; alert cached |
| Monitoring I2C error | Error logged; other blocks continue |
| Client timeout | State is uncertain; read status/config before retrying |

For a timed-out mutating request, do not blindly toggle the opposite state. Reconnect if necessary, read status/configuration, and reconcile from observed server state.

## Validation status

Completed validation includes:

- dependency-injected fake I2C bus unit tests;
- mux encoding and select-before-transfer ordering;
- safe TCA initialization;
- INA232 identity failure behavior;
- exact configuration/register byte order;
- masked readback verification;
- rail-off ordering before INA programming;
- transactional configuration rollback;
- per-block power isolation;
- idempotent safe disable;
- power-on rejection before configuration;
- alert observation removing rail requests;
- signed current decoding;
- invalid-input rejection without I2C traffic;
- concurrent mux transaction coherence;
- optional read-only Linux hardware smoke test;
- successful live client test on AFE 4 with 5V and CE telemetry.

Observed live values during initial validation were approximately:

```text
5V: 4.94 V, 94.2 mA, 466 mW
CE: 3.26 V, 3.5 mA, 11.5 mW
```

Both values were internally consistent (`P ~= V * I`) and returned to approximately zero after power-off.

Pending validation:

- controlled over-current/alert injection;
- long-duration multi-block soak testing;
- automated Linux syscall-level test of the raw `I2C_RDWR` transport;
- stale-telemetry indication and reconnect handling at the UI/application layer.

## Read-only hardware smoke test

The optional target-side smoke test selects one mux channel, reads both INA232 IDs using combined transfers, and reads the TCA configuration register. It does not request either rail on.

Example:

```bash
ctest --test-dir build -R i2c_hdmezz_smoke --output-on-failure
```

The test defaults to `/dev/i2c-2`, AFE 0. The executable also accepts adapter path and AFE index. Run it only while `daphneServer` and any other I2C bus owner are stopped.

## Relevant source files

| File | Responsibility |
|---|---|
| `srcs/I2CDevice.hpp/.cpp` | Linux I2C transport and combined reads |
| `srcs/DaphneI2CDrivers.hpp/.cpp` | HD mezzanine hardware driver and safety state |
| `srcs/defines.hpp` | Device/register addresses and mux encodings |
| `srcs/server_controller/handlers.cpp` | Protobuf command handlers |
| `srcs/server_controller/monitoring.cpp` | Cached telemetry and alert monitoring |
| `srcs/server_controller/router_server.cpp` | ZeroMQ ROUTER and envelope dispatch |
| `srcs/protobuf/daphneV3_high_level_confs.proto` | Envelope and message type IDs |
| `srcs/protobuf/daphneV3_low_level_confs.proto` | HD command payload definitions |
| `client/hdmezz_control_v2.py` | Reference CLI, RPC client, and visual UI |
| `tests/hdmezz_driver_tests.cpp` | Hardware-driver unit/fault tests |
| `tests/i2c_hdmezz_smoke.cpp` | Read-only target hardware smoke test |

## Compatibility checklist for another project

Before declaring a new client compatible, verify that it:

- uses `ControlEnvelopeV2`, not the deprecated envelope;
- uses a DEALER-compatible ZeroMQ request/reply pattern;
- preserves all protobuf field numbers;
- maps legacy `3V3` protobuf fields to user-facing CE;
- sends both power states in one request;
- enables and configures before requesting power;
- expects configuration to turn both requests off;
- interprets voltage as V, current as mA, power as mW;
- treats status as monitored/cached rather than synchronous;
- never lets polling overwrite pending command controls;
- never automatically re-enables power after an alert or communication failure;
- implements timeouts, correlation checks, and explicit error reporting.
