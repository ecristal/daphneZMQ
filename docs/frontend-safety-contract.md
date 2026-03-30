# Frontend Safety Contract

This document records the frontend alignment and safety constraints that the
software stack must preserve when configuring or operating the DAPHNE frontend.

It is the server-side counterpart to the firmware-side isolation/contracts
work in `daphne-firmware`.

## Why this exists

The frontend register ABI is stable, but correct use of that ABI depends on
operational constraints that are easy to lose if they live only in RTL source
comments or alignment scripts.

These constraints must remain visible in the software repo because
`daphne-server` is the component that actually drives configure, align, and
runtime register access from the PS side.

## Current frontend register contract

The software-visible frontend control path is:

- `frontendControl`
  - `DELAY_EN_VTC`
  - `SERDES_RESET`
  - `DELAYCTRL_RESET`
- `frontendStatus`
  - `DELAYCTRL_READY`
- `frontendTrigger`
- `frontendDelay_<afe>`
- `frontendBitslip_<afe>`

This contract is implemented in:

- `srcs/FpgaRegDict.cpp`
- `srcs/FrontEnd.cpp`
- `srcs/Daphne.cpp`

## Safety and correctness constraints

### AFE serialization assumptions

The firmware frontend boundary assumes:

- AFE serialized output is configured for `16-bit` transmission mode
- serialized ordering is `LSb-first`

Software must treat those assumptions as required frontend configuration, not
as optional tuning knobs.

### Alignment sequencing constraints

The frontend alignment procedure assumes:

1. reset delay control and SERDES before alignment;
2. disable delay VTC before loading IDELAY tap values;
3. do not trust alignment state until `DELAYCTRL_READY == 1`;
4. scan delay first, then bitslip;
5. re-enable delay VTC after alignment is complete.

These are operational constraints, not just implementation details.

### Training-pattern expectation

The software bitslip search currently looks for:

- `0x00FF00FF` in the 32-bit spy-visible frame-clock sample

That is the software-visible form of the firmware-side 16-bit FCLK expectation:

- `0x00FF`

Any future change to the frontend framing, spybuffer packing, or alignment
logic must preserve that relationship or update both sides together.

### Boolean naming caveat

The configure path writes the AFE `LSB_MSB_FIRST` bit from the protobuf
`sb_first` field. The field name alone is not sufficiently self-explanatory to
serve as the authoritative definition of the wire ordering.

Until this is made explicit in the config schema documentation, the firmware
contract remains the authority for the required deserialize assumption:

- `16-bit`, `LSb-first`

## Safe access policy

As the firmware becomes more modular, software should preserve these rules:

- do not treat absent or disabled blocks as silently safe to poke;
- prefer explicit capability checks before configuration or runtime access;
- document when a register window is optional, board-dependent, or gated by
  earlier initialization;
- fail explicitly in server code when a prerequisite block is not enabled.

The existing AFE guardrails in `DaphneI2CDrivers.cpp` are the correct style to
extend to other optional blocks.

## Future work

- Make frontend alignment preconditions explicit in the configuration schema,
  not only in handler code.
- Add an explicit software-visible "frontend valid/aligned" concept instead of
  inferring readiness only from procedural sequencing.
- Keep this file aligned with the firmware-side frontend and control-plane
  contracts during modularization.
