# Endpoint Safety Contract

This document records the timing-endpoint safety constraints that the software
stack must preserve when configuring clock source, resets, and endpoint
readiness checks.

It is the server-side counterpart to the firmware-side timing subsystem
contract in `daphne-firmware`.

## Why this exists

The rest of the design depends on the timing subsystem being not merely
configured, but actually ready. Clock selection, lock status, endpoint FSM
state, and timestamp readiness are separate signals and should not be collapsed
informally into "timing works".

## Current software-visible endpoint contract

The server uses:

- `endpointClockControl`
  - `SOFT_RESET`
  - `MMCM_RESET`
  - `CLOCK_SOURCE`
- `endpointClockStatus`
  - `MMCM0_LOCKED`
  - `MMCM1_LOCKED`
- `endpointControl`
  - `RESET`
  - `ADDRESS`
- `endpointStatus`
  - `TIMESTAMP_OK`
  - `FSM_STATUS`

This contract is implemented in:

- `srcs/FpgaRegDict.cpp`
- `srcs/Endpoint.cpp`
- `srcs/server_controller/handlers.cpp`

## Safety and correctness constraints

### Clock-source selection is not readiness

Selecting `CLOCK_SOURCE=endpoint` only chooses the endpoint-derived clock path.
It does not by itself mean:

- MMCMs are locked
- endpoint FSM is ready
- timestamps are valid

Software must keep those checks separate.

### Lock checks are required before trusting derived clocks

The timing path should not be considered stable until:

- `MMCM0_LOCKED == 1`
- `MMCM1_LOCKED == 1`

This is already reflected in the server-side helpers that wait for the lock
bits after changing clock source or pulsing MMCM reset.

### Endpoint readiness is more than lock

Endpoint operation should not be considered ready until:

- endpoint FSM is in the ready state
- `TIMESTAMP_OK == 1`

The current server helper treats:

- `FSM_STATUS == 8`
- `TIMESTAMP_OK == 1`

as the "endpoint ready" condition. Any future firmware change that alters that
meaning must update the server-side readiness check together with the firmware
contract.

### Local-clock mode has different semantics

Local-clock operation is valid for bring-up and fallback, but it is not the
same as endpoint-synchronized running:

- local mode may use fake timestamp behavior
- local mode must not be reported or treated as endpoint-ready operation

## Safe access policy

The recommended bring-up order is:

1. configure the external clock chip over I2C;
2. load the PL and wait for FPGA manager `operating`;
3. switch clock source and pulse MMCM reset if required;
4. wait for both lock bits;
5. program endpoint address;
6. pulse endpoint reset if required;
7. wait for endpoint-ready condition before starting higher-level services.

When switching timing mode or initializing the endpoint:

1. set clock source deliberately;
2. pulse MMCM reset when required;
3. wait for both lock bits;
4. program endpoint address;
5. pulse endpoint reset when required;
6. wait for endpoint-ready condition before treating timing-derived behavior as
   valid downstream.

The external clock-chip step is a board-level prerequisite and should not be
hidden inside the PL endpoint step.

## Future work

- Add a single higher-level software-visible readiness concept that captures
  "timing usable" without losing the underlying raw status bits.
- Keep this document aligned with the firmware-side timing subsystem contract
  during modularization.
