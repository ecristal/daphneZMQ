# PS MIO SPI GPIO Beginner Guide

This guide is for the simplest possible setup:

- one laptop
- one DAPHNE board
- plain SSH access to the board
- a `daphne-server` checkout on the laptop
- a `daphne-server` checkout on the board

It assumes you know how to `ssh` to the board, but not much more.

The goal is:

1. check that the board is ready
2. apply the temporary runtime overlay
3. free the PS MIO pins that are currently owned by other peripherals
4. claim those pins as GPIO
5. pulse a few lines to prove you can control them
6. clean everything up again

This procedure does **not**:

- modify `/boot/system.dtb`
- require a reboot
- permanently change the board

This procedure **does**:

- use `sudo` on the board
- use a temporary runtime DT overlay through `configfs`
- copy one helper script into `~/daphne-server/client/` on the board

If you reboot the board, the overlay is gone.

## 1. What you need

On the laptop:

- `~/repo/daphne-server`
- `python3`
- `ssh`
- `scp`

On the board:

- Linux is up and reachable with SSH
- the account can run `sudo`
- `~/daphne-server` exists
- `python3` exists
- `dtc` exists
- `/sys/kernel/config/device-tree/overlays` exists

Important:

- for this overlay and GPIO test, you do **not** need to build the
  `daphneServer` C++ binary
- you only need the `daphne-server` repository because the test scripts live
  there

If later you want the normal DAPHNE server running, that is a separate build
step.

## 2. What the scripts do

There are two scripts involved.

Laptop-side wrapper:

- [client/ps_mio_spi_gpio_remote.py](../client/ps_mio_spi_gpio_remote.py)

Board-side helper:

- [client/ps_mio_spi_gpio_board.py](../client/ps_mio_spi_gpio_board.py)

The laptop-side wrapper does this:

1. copies the board helper into `~/daphne-server/client/` on the board
2. logs into the board with SSH
3. runs the board helper with `sudo`

You run only the laptop-side wrapper. You normally do not run the board helper
by hand.

## 3. Pin map used by the test

The current helper uses this mezzanine map:

| Mezz | CS | SCLK | SDO | SDI |
| --- | --- | --- | --- | --- |
| `MEZ0` | `MIO38` | `MIO39` | `MIO40` | `MIO50` |
| `MEZ1` | `MIO41` | `MIO42` | `MIO43` | `MIO61` |
| `MEZ2` | `MIO62` | `MIO63` | `MIO73` | `MIO74` |
| `MEZ3` | `MIO69` | `MIO68` | `MIO67` | `MIO57` |
| `MEZ4` | `MIO65` | `MIO64` | `MIO46` | `MIO45` |

For this test:

- `CS`, `SCLK`, and `SDO` are treated as outputs
- `SDI` is treated as an input

## 4. Choose the board name once

Open a terminal on the laptop and run:

```bash
cd ~/repo/daphne-server
export BOARD=petalinux@<board-host-or-ip>
```

Example:

```bash
export BOARD=petalinux@10.73.137.161
```

If you already have an SSH alias, you can use that instead:

```bash
export BOARD=daphne-13
```

## 5. Check the basic requirements

Run these commands from the laptop.

Check laptop tools:

```bash
cd ~/repo/daphne-server
python3 --version
ssh -V
```

Check that SSH to the board works:

```bash
ssh "$BOARD" 'hostname; whoami'
```

You should see:

- the board hostname
- the user name, usually `petalinux`

Check that the board-side `daphne-server` checkout exists:

```bash
ssh "$BOARD" 'cd ~/daphne-server && pwd'
```

You should see:

```text
/home/petalinux/daphne-server
```

Check that the board has the tools required by the helper:

```bash
ssh "$BOARD" 'command -v python3; command -v dtc; test -d /sys/kernel/config/device-tree/overlays && echo overlay-ok'
```

You should see:

- a path for `python3`
- a path for `dtc`
- `overlay-ok`

Check that `sudo` works.

Simplest version:

```bash
ssh "$BOARD" "printf '<sudo-password>\n' | sudo -S true && echo sudo-ok"
```

Replace `<sudo-password>` with the real sudo password.

If it works, you should see:

```text
sudo-ok
```

If any command in this section fails, stop here and fix that first.

## 6. First status check

This step is safe. It only reports the current state. It does not apply the
overlay and does not claim any GPIO.

Run:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

The script will prompt:

```text
Remote sudo password:
```

Type the board sudo password and press Enter.

What you want to see in the output:

- `overlay_active=False`
- the conflicted DT nodes still show `status=okay`
- the `MEZ*` lines show `not-exported`

That means:

- the board is still in its normal state
- the test has not changed anything yet

## 7. Apply the overlay only

This step disables the PS blocks that currently own the target MIO pins.

Run:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" apply-overlay
```

What this step does:

- applies a temporary runtime DT overlay
- disables:
  - `gem1`
  - `usb0`
  - `usb1`
  - the child `dwc3` nodes under those USB blocks

What you want to see:

- `overlay_active=True`
- these nodes show `status=disabled`
  - `/axi/ethernet@ff0c0000`
  - `/axi/usb@ff9d0000`
  - `/axi/usb@ff9d0000/usb@fe200000`
  - `/axi/usb@ff9e0000`
  - `/axi/usb@ff9e0000/usb@fe300000`

That means the conflicting PS owners have been disabled at runtime.

## 8. Check status again after the overlay

Run:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

You should still see:

- `overlay_active=True`
- the conflicted nodes are `disabled`
- GPIO lines still `not-exported`

This is expected. Applying the overlay frees the pins, but it does not yet
claim them as GPIO.

## 9. Run a simple control test

Now you will claim some pins as GPIO and pulse one of the output lines.

Start with a small test on one mezzanine:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py \
  --host "$BOARD" \
  smoketest \
  --mezz MEZ0 \
  --pulse-role SCLK \
  --pulse-count 2
```

What this command does:

1. applies the overlay if it is not already active
2. exports the `MEZ0` GPIO lines
3. sets `CS`, `SCLK`, and `SDO` as outputs
4. sets `SDI` as input
5. pulses `SCLK` two times
6. prints status
7. cleans up by default

What you want to see during the status print:

- `overlay_active=True`
- `MEZ0` lines show `exported`
- `CS`, `SCLK`, `SDO` show `direction=out`
- `SDI` shows `direction=in`

What cleanup means here:

- after the command finishes, exported GPIO lines are removed again
- the overlay is removed again

So after this test, the board should be back in its normal state.

## 10. Confirm cleanup

Run:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

You want to see:

- `overlay_active=False`
- conflicted nodes back to `status=okay`
- tested GPIO lines back to `not-exported`

If you see that, the test was clean and reversible.

## 11. Keep the pins active for a scope or multimeter

Sometimes you want the pins to stay active so you can probe them.

Use this:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py \
  --host "$BOARD" \
  smoketest \
  --mezz MEZ1 \
  --pulse-role SCLK \
  --pulse-count 2 \
  --keep-overlay \
  --keep-lines
```

This means:

- the overlay stays applied
- the GPIO lines stay exported
- the board remains in the test state after the command ends

Check the state:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

You want to see:

- `overlay_active=True`
- selected GPIO lines still `exported`

Now you can go to the hardware with a scope or multimeter and probe the lines.

## 12. Clean up after a kept test

If you used `--keep-overlay` or `--keep-lines`, run this when you are done:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" remove-overlay
```

Then confirm:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

You want to be back to:

- `overlay_active=False`
- conflicted nodes `status=okay`
- GPIO lines `not-exported`

## 13. Faster repeated use

If you do not want to type the sudo password every time, you can export it in
the current shell:

```bash
export DAPHNE_SUDO_PASSWORD=<sudo-password>
```

Then commands like this will use it automatically:

```bash
cd ~/repo/daphne-server
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

This is convenient, but remember it leaves the password in your shell
environment.

## 14. What exactly this proves

If the test works, you have proved three things:

1. the running kernel accepts the runtime overlay
2. the conflicting PS owners can be disabled live
3. the target MIO lines can be reclaimed and driven as GPIO

That is the bring-up step before writing a real SPI controller on top.

## 15. What this does not do

This test is **not** yet a full SPI implementation.

It does **not**:

- create a permanent device-tree change
- expose a Linux `spidev` device
- add a new `daphneServer` network API
- implement full SPI transactions with protocol-aware timing

Right now, it is a safe bring-up tool to prove that the pins can be freed and
controlled.

## 16. Common problems

If `ssh "$BOARD"` fails:

- fix SSH access first

If the wrapper asks for the sudo password and then fails:

- verify the password manually with:

```bash
ssh "$BOARD" "printf '<sudo-password>\n' | sudo -S true && echo sudo-ok"
```

If you see `run this script under sudo/root`:

- you probably ran the board helper directly
- use the laptop wrapper instead

If `dtc` is missing:

- install it on the board or use a board image that already has it

If `/sys/kernel/config/device-tree/overlays` does not exist:

- the running kernel does not expose the runtime overlay interface needed by
  this helper

If `overlay_active=True` but GPIO export fails:

- a pin may still be owned by something else
- run `status` again and check that the conflicting nodes are really
  `disabled`

## 17. One full example session

Here is the shortest complete sequence.

Set the board:

```bash
cd ~/repo/daphne-server
export BOARD=petalinux@<board-host-or-ip>
```

Check the baseline:

```bash
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

Apply the overlay:

```bash
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" apply-overlay
```

Run one control test:

```bash
python3 client/ps_mio_spi_gpio_remote.py \
  --host "$BOARD" \
  smoketest \
  --mezz MEZ0 \
  --pulse-role SCLK \
  --pulse-count 2
```

Check cleanup:

```bash
python3 client/ps_mio_spi_gpio_remote.py --host "$BOARD" status
```

If the last status shows `overlay_active=False` and the lines are
`not-exported`, you are back to the normal board state.
