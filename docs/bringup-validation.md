# Bring-Up Validation

This is the narrow validation path for a target that should:

1. configure the external clock chip,
2. load the PL,
3. configure the timing endpoint,
4. start Hermes,
5. start `daphneServer`.

It assumes the service chain created by
`utils/setup_firmware_service.sh`.

## Current blocker

Do not treat this service chain as meaningful unless the firmware overlay has
already restored the Linux-visible PL I2C path used to reach the external clock
chip.

During the March 31, 2026 validation of `daphne-firmware` commit `7f032ac` on
`NP04-DAPHNE-014`, the overlay loaded through `xmutil`, but the expected PL I2C
bus did not reappear in Linux. In that state:

- `clockchip.service` fails immediately
- endpoint probing can hang the board because the external timing clock path is
  not configured

That is a firmware/DT integration blocker, not a `daphne-server` service-order
bug.

## 1. Build `daphneServer`

On the target or on a matching Petalinux build environment:

```bash
cd "$HOME/daphne-server"
cmake -S . -B build-petalinux -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build-petalinux --parallel
```

If you are using the pinned deps tarball flow instead, keep using:

```bash
cd "$HOME/daphne-server"
./scripts/petalinux_build.sh ./build-petalinux ./deps_tarballs
```

Expected binary:

```bash
ls -l ./build-petalinux/daphneServer
```

## 2. Install or refresh the service chain

```bash
cd "$HOME/daphne-server"
sudo DAPHNE_ROOT="$PWD" \
     DAPHNE_BUILD_DIR="$PWD/build-petalinux" \
     DAPHNE_BIN="$PWD/build-petalinux/daphneServer" \
     FW_APP=MEZ_SELF_TRIG_V15_OL_UPGRADED \
     ENDPOINT_ADDR_HEX=0x20 \
     ENDPOINT_SUCCESS_STATES=0x8 \
     ./utils/setup_firmware_service.sh
```

Adjust `FW_APP` and `ENDPOINT_ADDR_HEX` if your board inventory requires a
different overlay or endpoint address.

If a board is expected to pause in a non-error endpoint FSM state while waiting
for an external timing action, set `ENDPOINT_SUCCESS_STATES` accordingly. For
example, `ENDPOINT_SUCCESS_STATES=0x6,0x8` treats `ST_W_SETUP` and full ready
as acceptable endpoint outcomes for the service chain.

## 3. Restart and validate the chain

```bash
cd "$HOME/daphne-server"
sudo ./utils/check_bringup_chain.sh --restart --ts 4 --journal-lines 20
```

This checks:

- `clockchip.service`
- `firmware.service`
- `endpoint.service`
- `hermes.service`
- `daphne.service`
- FPGA manager state
- endpoint status and timestamp probe
- recent journal lines for each unit

The endpoint step is expected to require:

- both MMCMs locked,
- endpoint FSM state `ST_READY`,
- `TIMESTAMP_OK = 1`.

## 4. Minimal runtime smoke tests

After the service chain is up:

```bash
systemctl is-active clockchip.service firmware.service endpoint.service hermes.service daphne.service
journalctl -u endpoint.service -n 50 --no-pager
journalctl -u daphne.service -n 50 --no-pager
```

If the server is listening:

```bash
ss -ltnp | grep 40001
```

Then run a minimal client-side configure or align request against the target.
The important point for this stage is not physics-quality data taking; it is:

- clock chip config succeeds,
- PL reaches `operating`,
- endpoint reaches ready with valid timestamps,
- Hermes starts only after endpoint ready,
- `daphneServer` starts only after the chain is healthy.

## Failure interpretation

- `clockchip.service` failure:
  external timing infrastructure is not configured; endpoint readiness is not
  meaningful yet.
- `firmware.service` failure:
  the PL was not loaded, so endpoint and server checks are invalid.
- `endpoint.service` failure:
  do not continue to Hermes or `daphneServer`; inspect MMCM lock, endpoint
  state, and timestamp validity first.
- `endpoint.service` success with a non-ready state:
  this can be intentional if `ENDPOINT_SUCCESS_STATES` includes an accepted
  waiting state such as `0x6` (`ST_W_SETUP`) for a board-specific workflow.
- `daphne.service` failure with healthy endpoint:
  usually means a userspace build/dependency/runtime issue rather than a PL
  bring-up issue.
