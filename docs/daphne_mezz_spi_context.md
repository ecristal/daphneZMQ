# DAPHNE Mezzanine SPI/MIO Context and Proposed Solution

## Purpose

This note summarizes the current investigation into the DAPHNE mezzanine SPI-like control lines, how they appear in Linux/PetaLinux, why they are not currently visible as `/dev/spidev*` devices, and the two practical implementation paths for software control.

The intended reader is a coding agent working on `daphne-server` or the PetaLinux/device-tree integration.

## Hardware and software context

Target system:

- DAPHNE motherboard with Kria SOM.
- PetaLinux system running on Zynq UltraScale+ MPSoC.
- Project context: `daphne-server` / `daphneZMQ`.
- Goal: access/control the mezzanine SPI-style signals used by the AFE mezzanine cards.
- Target device on the SoF receiver mezzanine: `ADC1283`.

The `ADC1283` is an STMicroelectronics 8-channel, 12-bit SAR ADC with a
4-wire SPI-compatible interface. Its key protocol constraints matter directly
for the mezzanine implementation:

- `CS` is active low and a falling edge starts conversion.
- `DIN` programs an 8-bit control register, but only bits `5:3` matter for
  channel selection (`ADD2:ADD0`).
- `DOUT` format is always `0000` followed by the 12-bit conversion result,
  MSB first.
- One full conversion requires `16` SCLK cycles:
  - `3` acquisition/track cycles
  - `13` conversion/hold cycles
- After `CS` goes high, the channel address register resets to `IN0`.
- At startup, the first 16-clock result is always `IN0`; to get a newly
  selected non-`IN0` channel after starting conversion, `32` SCLK cycles are
  required.
- Datasheet operating SCLK range is `0.8 MHz` to `3.2 MHz`, corresponding to
  `50 ksps` to `200 ksps`.

Reference:

- STMicroelectronics ADC1283 datasheet:
  https://www.st.com/resource/en/datasheet/adc1283.pdf

The schematic source is:

- `DAPHNE_Mezz Motherboard Schematic Prints.pdf`
- Relevant pages:
  - Page 2: AFE Front End / mezzanine connector `J5 (J5A, ...)`.
  - Page 13: Kria Module Connector 1, showing `MIO_MEZZ[0..4]` routed to Kria MIO pins.
  - Page 14: Kria Module Connector 2, mostly PL/HDIO/HPIO and I2C expanders.

## Linux SPI topology observed on the running system

The system currently reports one `/dev/spidev*` node:

```bash
ls -l /dev/spidev*
```

Observed:

```text
crw------- 1 root root 153, 0 Apr 24 12:41 /dev/spidev3.0
```

Linux SPI masters:

```text
spi0 -> ../../devices/platform/axi/ff0f0000.spi/spi_master/spi0
spi2 -> ../../devices/platform/axi/ff050000.spi/spi_master/spi2
spi3 -> ../../devices/platform/axi/9c020000.axi_quad_spi/spi_master/spi3
```

SPI device nodes:

```text
/sys/bus/spi/devices/spi0.0
/sys/bus/spi/devices/spi2.0
/sys/bus/spi/devices/spi3.0
```

Detailed device-tree/sysfs mapping:

```text
spi0:
  path:       /sys/devices/platform/axi/ff0f0000.spi
  of_node:    /sys/firmware/devicetree/base/axi/spi@ff0f0000
  compatible: xlnx,zynqmp-qspi-1.0
  child:      flash@0

spi0.0:
  modalias:   spi:mt25qu512a
  driver:     spi-nor
  spidev:     none
```

Conclusion: `spi0.0` is QSPI flash, not a mezzanine SPI bus.

```text
spi2:
  path:       /sys/devices/platform/axi/ff050000.spi
  of_node:    /sys/firmware/devicetree/base/axi/spi@ff050000
  compatible: cdns,spi-r1p6
  child:      tpm@0

spi2.0:
  modalias:   spi:slb9670
  driver:     tpm_tis_spi
  spidev:     none
```

Conclusion: `spi2.0` is a TPM on the PS SPI controller. It is not a mezzanine SPI bus.

```text
spi3:
  path:       /sys/devices/platform/axi/9c020000.axi_quad_spi
  of_node:    /sys/firmware/devicetree/base/axi/axi_quad_spi@9c020000
  compatible: xlnx,axi-quad-spi-3.2 xlnx,xps-spi-2.00.a
  child:      spidev@0

spi3.0:
  modalias:   spi:dh2228fv
  driver:     spidev
  spidev:     spidev3.0
```

Conclusion: `/dev/spidev3.0` is the PL AXI Quad SPI at `0x9c020000`. It is not the PS/MIO mezzanine SPI-like interface.

## Runtime PS GPIO/MIO information

The system exposes the PS GPIO controller:

```text
gpiochip0
label: zynqmp_gpio
base: 0
ngpio: 174
```

Debugfs GPIO dump shows named MIO functions:

```text
gpio-0   (QSPI_CLK)
gpio-1   (QSPI_DQ1)
gpio-2   (QSPI_DQ2)
gpio-3   (QSPI_DQ3)
gpio-4   (QSPI_DQ0)
gpio-5   (QSPI_CS_B)
gpio-6   (SPI_CLK)
gpio-9   (SPI_CS_B)
gpio-10  (SPI_MISO)
gpio-11  (SPI_MOSI)
gpio-23  (EMMC_RST)
gpio-24  (I2C1_SCL)
gpio-25  (I2C1_SDA)
```

The hardware PS SPI controller currently uses:

```text
MIO6   -> SPI_CLK
MIO9   -> SPI_CS_B
MIO10  -> SPI_MISO
MIO11  -> SPI_MOSI
```

But that PS SPI controller is assigned to the TPM device:

```text
spi2.0 -> tpm@0 -> slb9670 -> tpm_tis_spi
```

Therefore, do not use or modify `spi2.0` for the mezzanines unless the TPM design is intentionally removed or changed.

## Schematic-level mezzanine SPI-like signals

The DAPHNE mezzanine schematic shows the relevant mezzanine control bundles as:

```text
MIO_MEZZ0
MIO_MEZZ1
MIO_MEZZ2
MIO_MEZZ3
MIO_MEZZ4
```

Each bundle has these SPI-like pins:

```text
CS-1v8
SCK-1v8
SDO/RST-1v8
SDI/RST-1v8
```

Interpretation:

```text
CS-1v8       -> chip select, active-low in normal SPI convention
SCK-1v8      -> serial clock
SDO/RST-1v8  -> likely slave data output, i.e. master MISO
SDI/RST-1v8  -> likely slave data input, i.e. master MOSI
```

The `/RST` suffix is important. It suggests that these lines may have a reset-related or multiplexed function, depending on the mezzanine implementation. Validate with the mezzanine card schematic or firmware convention before assuming pure SPI behavior.

For the current SoF receiver target, these lines must be treated as the
`ADC1283` serial control/data interface first, and only treated as reset-like
signals if board-level validation shows that the mezzanine repurposes them.

## MIO mapping extracted from the schematic

From page 13 of the DAPHNE mezzanine schematic, the `MIO_MEZZx` nets map to Kria SOM MIO pins as follows.

Because the Linux `zynqmp_gpio` base is `0`, the Linux GPIO number equals the MIO number.

### MIO_MEZZ0

```text
MIO_MEZZ0.CS-1v8       -> MIO38 -> gpio-38
MIO_MEZZ0.SCK-1v8      -> MIO39 -> gpio-39
MIO_MEZZ0.SDO/RST-1v8  -> MIO40 -> gpio-40
MIO_MEZZ0.SDI/RST-1v8  -> MIO50 -> gpio-50
```

### MIO_MEZZ1

```text
MIO_MEZZ1.CS-1v8       -> MIO41 -> gpio-41
MIO_MEZZ1.SCK-1v8      -> MIO42 -> gpio-42
MIO_MEZZ1.SDO/RST-1v8  -> MIO43 -> gpio-43
MIO_MEZZ1.SDI/RST-1v8  -> MIO61 -> gpio-61
```

### MIO_MEZZ2

```text
MIO_MEZZ2.CS-1v8       -> MIO62 -> gpio-62
MIO_MEZZ2.SCK-1v8      -> MIO63 -> gpio-63
MIO_MEZZ2.SDO/RST-1v8  -> MIO73 -> gpio-73
MIO_MEZZ2.SDI/RST-1v8  -> MIO74 -> gpio-74
```

### MIO_MEZZ3

```text
MIO_MEZZ3.CS-1v8       -> MIO69 -> gpio-69
MIO_MEZZ3.SCK-1v8      -> MIO68 -> gpio-68
MIO_MEZZ3.SDO/RST-1v8  -> MIO67 -> gpio-67
MIO_MEZZ3.SDI/RST-1v8  -> MIO57 -> gpio-57
```

### MIO_MEZZ4

```text
MIO_MEZZ4.CS-1v8       -> MIO65 -> gpio-65
MIO_MEZZ4.SCK-1v8      -> MIO64 -> gpio-64
MIO_MEZZ4.SDO/RST-1v8  -> MIO46 -> gpio-46
MIO_MEZZ4.SDI/RST-1v8  -> MIO45 -> gpio-45
```

## Key conclusion

The mezzanine SPI-like lines are not currently exposed as hardware SPI buses in Linux.

They are best understood as independent PS MIO GPIO bundles:

```text
MIO_MEZZ[0..4] -> PS MIO GPIO lines -> zynqmp_gpio
```

They are separate from:

```text
/dev/spidev3.0 -> PL AXI Quad SPI at 0x9c020000
spi2.0        -> PS SPI TPM at 0xff050000
spi0.0        -> QSPI flash at 0xff0f0000
```

Therefore, using `/dev/spidev3.0` will not control the `MIO_MEZZx` pins.

## Implementation options

There are two practical approaches.

## Option A: application-level GPIO bit-banging

In this approach, `daphne-server` directly controls the GPIO lines.

For each bit transfer:

```text
1. Drive CS low.
2. Set MOSI according to the outgoing bit.
3. Toggle SCK.
4. Sample MISO.
5. Repeat for all bits.
6. Drive CS high.
```

Example for `MIO_MEZZ0`:

```text
CS   = gpio-38
SCK  = gpio-39
MISO = gpio-40  // SDO/RST-1v8
MOSI = gpio-50  // SDI/RST-1v8
```

### Pros

- Fastest path for board bring-up.
- Does not require device-tree changes.
- Does not require kernel rebuild.
- Gives complete control over timing, reset sequencing, and nonstandard behavior.
- Useful if `SDO/RST` and `SDI/RST` require special handling outside normal SPI transfers.
- Easy to add diagnostic logging in `daphne-server`.
- Useful for proving the `ADC1283` line mapping and frame formatting before
  changing the PetaLinux image.

### Cons

- Userspace GPIO toggling is not deterministic under Linux.
- Maximum reliable clock rate is limited.
- `/sys/class/gpio` is especially slow and deprecated.
- `libgpiod` is cleaner, but still not real-time.
- Custom SPI code in `daphne-server` is less reusable than the standard Linux SPI API.
- Existing SPI tools such as `spidev_test` cannot be used directly.
- Important for `ADC1283`: the datasheet specifies `0.8 MHz` to `3.2 MHz`
  SCLK. Slow userspace bit-banging is fine for electrical bring-up, but may be
  outside the ADC's functional operating range for real conversions.
- Therefore, Option A should be considered a validation and bring-up path
  first, not automatically the long-term acquisition path for the SoF receiver.

### Recommended low-level API for Option A

Prefer `libgpiod` over `/sys/class/gpio`.

Avoid `/sys/class/gpio` for long-term code because it is deprecated in modern Linux kernels.

Potential C++ structure:

```cpp
struct MezzSpiPins {
    unsigned cs;
    unsigned sck;
    unsigned miso;
    unsigned mosi;
};

static constexpr MezzSpiPins MEZZ0{38, 39, 40, 50};
static constexpr MezzSpiPins MEZZ1{41, 42, 43, 61};
static constexpr MezzSpiPins MEZZ2{62, 63, 73, 74};
static constexpr MezzSpiPins MEZZ3{69, 68, 67, 57};
static constexpr MezzSpiPins MEZZ4{65, 64, 46, 45};
```

For `ADC1283`, the low-level API should not be limited to generic byte
transfer. It should expose protocol-aware helpers such as:

```cpp
struct MezzSpiTransferResult {
    std::vector<uint8_t> rx_bytes;
    std::vector<uint16_t> samples;
};

uint8_t build_adc1283_control_byte(uint8_t channel);
MezzSpiTransferResult transfer_bits(const std::vector<uint8_t>& tx, size_t nbits);
uint16_t decode_adc1283_word(uint16_t raw16); // strips leading 4 zeros
uint16_t read_adc1283_channel_once(uint8_t channel);
std::array<uint16_t, 8> read_adc1283_scan();
```

Notes for the helper semantics:

- `build_adc1283_control_byte(channel)` should place the channel address in
  bits `5:3`, yielding control values `0x00, 0x08, 0x10, ..., 0x38`.
- `read_adc1283_channel_once(channel)` should account for the startup/pipeline
  behavior:
  - `IN0` can be read after the first `16` clocks.
  - any other channel needs `32` clocks after starting conversion if `CS` had
    gone high previously.
- `decode_adc1283_word(raw16)` should interpret the returned frame as
  `0000 D11 D10 ... D0`.

Recommended first validation:

1. Export or request GPIO lines for one mezzanine only.
2. Set `CS` and `SCK` as outputs.
3. Toggle `CS` and `SCK` slowly, around 1 Hz to 1 kHz.
4. Confirm with a scope or logic analyzer at the mezzanine connector.
5. Add MOSI toggling.
6. Sample MISO.
7. Only then implement `ADC1283` frame formatting.
8. After the electrical mapping is confirmed, verify whether the platform can
   sustain an SCLK close to the `ADC1283` minimum specified `0.8 MHz`.
9. If it cannot, treat Option A as bring-up only and move quickly to Option B.

## Option B: Linux `spi-gpio` device-tree implementation

In this approach, the MIO GPIO lines are described as software SPI controllers in the device tree using the kernel `spi-gpio` driver.

Linux then exposes the mezzanine interface as normal SPI devices, for example:

```text
/dev/spidevX.0
/dev/spidevY.0
...
```

A conceptual device-tree node for `MIO_MEZZ0` would look like this:

```dts
spi_mezz0 {
    compatible = "spi-gpio";

    sck-gpios  = <&gpio 39 GPIO_ACTIVE_HIGH>;
    mosi-gpios = <&gpio 50 GPIO_ACTIVE_HIGH>;
    miso-gpios = <&gpio 40 GPIO_ACTIVE_HIGH>;
    cs-gpios   = <&gpio 38 GPIO_ACTIVE_LOW>;

    num-chipselects = <1>;
    #address-cells = <1>;
    #size-cells = <0>;

    spidev@0 {
        compatible = "rohm,dh2228fv";
        reg = <0>;
        spi-max-frequency = <100000>;
    };
};
```

The exact GPIO controller label may not be `&gpio` in the PetaLinux device tree. It may need to match the label used by the generated DTS for `ff0a0000.gpio`.

Equivalent nodes can be created for all five mezzanines.

### Pros

- Creates standard Linux SPI devices.
- Allows `daphne-server` to use standard `spidev` `ioctl()` calls.
- Allows testing with tools such as `spidev_test`.
- Cleaner architecture for long-term maintenance.
- Keeps SPI bit toggling in the kernel instead of custom userspace code.
- Easier to integrate with other Linux SPI drivers if the target device later gets a kernel driver.
- More likely than userspace bit-banging to reach the `ADC1283` minimum
  functional clock range.

### Cons

- Requires device-tree changes.
- Requires PetaLinux image rebuild or device-tree overlay support.
- Still software SPI, not real hardware SPI.
- Timing is slower and less deterministic than a real SPI controller.
- Special reset/data multiplexing on `SDO/RST` and `SDI/RST` may not fit cleanly into plain `spi-gpio`.
- Debugging GPIO polarity and ownership can take time.
- `spidev` byte transfers still need an `ADC1283`-aware software layer on top,
  because channel selection and readback are pipelined rather than simple
  register read/write transactions.

## ADC1283-specific protocol notes

The `ADC1283` is the first concrete target for the mezzanine SPI implementation,
so the low-level API should be shaped around its behavior rather than around a
generic SPI flash-like model.

### Control byte

Only bits `5:3` are meaningful:

```text
bit:  7 6 5    4    3    2 1 0
      X X ADD2 ADD1 ADD0 X X X
```

Channel select values:

```text
IN0 -> 0x00
IN1 -> 0x08
IN2 -> 0x10
IN3 -> 0x18
IN4 -> 0x20
IN5 -> 0x28
IN6 -> 0x30
IN7 -> 0x38
```

### Readback framing

Each conversion result is returned as:

```text
0000 D11 D10 D9 D8 D7 D6 D5 D4 D3 D2 D1 D0
```

This means the software should collect a full 16-bit frame and then mask off
the upper 4 zero bits.

### Transaction model implication

The `ADC1283` behaves more like a continuously clocked sampled-data converter
than a conventional SPI peripheral with independent command and response
packets.

Practical implications:

- `CS` low starts conversion; `CS` high stops conversion and resets the channel
  address register to `IN0`.
- If `CS` is toggled high between reads, the software must expect the next
  first result to be `IN0`.
- For a stable multi-channel scan, it may be preferable to keep `CS` low and
  stream consecutive 16-clock frames.
- The software API should explicitly document whether a read helper uses:
  - single-shot `CS` pulses, or
  - continuous streaming with `CS` held low

### Timing implication for Option A

The biggest practical risk for Option A is not frame formatting but clock rate.

For the `ADC1283`, very slow bit-banging is still useful to:

- confirm MIO-to-mezzanine pin mapping
- confirm `CS`, `SCK`, `DIN`, and `DOUT` polarity
- verify that returned bits have the expected `0000 + 12-bit` structure

However, the datasheet operating range is `0.8 MHz` to `3.2 MHz`. If the
userspace GPIO implementation cannot approach that range on the target Linux
system, it should not be considered sufficient for the final SoF receiver test.

## Recommended development sequence

Use Option A first for electrical and protocol validation.

Suggested sequence:

1. Confirm the MIO/GPIO mapping from the schematic and, if possible, from the Altium netlist.
2. Use `libgpiod` or simple temporary sysfs GPIO access to toggle `CS` and `SCK` on one mezzanine port.
3. Verify signals on a scope or logic analyzer.
4. Implement a slow `ADC1283`-aware bit-bang transaction in `daphne-server` or
   in a standalone test utility.
5. Verify the `ADC1283` framing rules:
   - `16` clocks per conversion
   - `0000 + 12-bit result` on `DOUT`
   - channel select control bits on `DIN[5:3]`
6. Verify whether `SDO/RST` and `SDI/RST` behave as pure SPI data lines or
   require reset-mode handling.
7. Measure the achievable clock rate with the selected userspace GPIO
   implementation.
8. If the implementation cannot approach the `ADC1283` minimum specified
   `0.8 MHz`, move to Option B for the actual SoF receiver validation.
9. If standard SPI semantics are sufficient, implement Option B and expose
   `/dev/spidev*` nodes for the mezzanines.

## Suggested standalone test utility behavior

Create a small test program before integrating deeply into `daphne-server`.

Arguments:

```text
--mezz 0..4
--channel 0..7
--bits 16|32|48|64
--clock-hz approximate_delay_based_speed
--tx hex_string
--loop N
--hold-cs-low
--decode-adc1283
--verbose
```

Example usage:

```bash
./mezz_gpio_spi_test --mezz 2 --channel 0 --bits 16 --tx "00 00" --decode-adc1283 --verbose
./mezz_gpio_spi_test --mezz 2 --channel 3 --bits 32 --tx "18 00 18 00" --decode-adc1283 --verbose
```

For initial toggling only:

```bash
./mezz_gpio_spi_test --mezz 0 --toggle-sck --hz 10
./mezz_gpio_spi_test --mezz 0 --toggle-cs --hz 1
```

## Safety notes

- These are 1.8 V MIO-side signals. Do not drive them externally at 3.3 V.
- Avoid reconfiguring MIO6/MIO9/MIO10/MIO11 unless intentionally modifying the TPM/PS SPI design.
- `/dev/spidev3.0` controls the PL AXI Quad SPI, not the mezzanine `MIO_MEZZx` pins.
- Confirm `CS` polarity with hardware. The schematic uses `CS-1v8`; normal SPI convention implies active-low, but verify.
- Confirm whether `SDO/RST` and `SDI/RST` require reset behavior before using them as pure data lines.
- The `ADC1283` digital supply range is `2.7 V` to `5.5 V` per datasheet. Since
  the mezzanine control lines are shown as `1.8 V` MIO-side signals in the
  motherboard schematic context, the actual level translation and device-side
  IO domain on the SoF receiver must be confirmed before active testing.
- Do not assume that a slow successful bit exchange proves compliant `ADC1283`
  operation; it may only prove electrical connectivity.

## Useful commands for future debugging

List SPI masters:

```bash
for m in /sys/class/spi_master/spi*; do
    echo "$(basename "$m") -> $(readlink -f "$m")"
done
```

List SPI devices and drivers:

```bash
for d in /sys/bus/spi/devices/spi*.*; do
    echo "---- $d"
    echo -n "modalias: "; cat "$d/modalias" 2>/dev/null || echo none
    echo -n "driver:   "; basename "$(readlink -f "$d/driver" 2>/dev/null)" 2>/dev/null || echo none
    echo -n "spidev:   "; [ -d "$d/spidev" ] && ls "$d/spidev" || echo none
    echo
 done
```

Inspect GPIO controller:

```bash
for g in /sys/class/gpio/gpiochip*; do
    echo "---- $g"
    cat "$g/label" 2>/dev/null
    echo -n "base: "; cat "$g/base" 2>/dev/null
    echo -n "ngpio: "; cat "$g/ngpio" 2>/dev/null
 done
```

Dump GPIO names and current users:

```bash
sudo cat /sys/kernel/debug/gpio
```

Filter for relevant pins:

```bash
sudo cat /sys/kernel/debug/gpio | grep -Ei "mezz|mio|spi|sck|sdo|sdi|cs|rst"
```

## Summary

The mezzanine SPI-like signals are present in the schematic as `MIO_MEZZ0..4`,
each with `CS`, `SCK`, `SDO/RST`, and `SDI/RST` at 1.8 V. The Linux image does
not expose these as `/dev/spidev*`. The only current `/dev/spidev3.0` is the
PL AXI Quad SPI. The PS hardware SPI controller is already occupied by the TPM.

For the current SoF target, the device is `ADC1283`, which imposes specific
protocol requirements:

- `16` SCLK cycles per conversion
- `0000 + 12-bit` MSB-first output frame
- channel select bits on `DIN[5:3]`
- `32` clocks needed to obtain a freshly selected non-`IN0` channel after
  startup
- specified SCLK operating range of `0.8 MHz` to `3.2 MHz`

Therefore, the mezzanine interface should be implemented either by direct GPIO
bit-banging from `daphne-server` or by adding `spi-gpio` device-tree nodes to
expose the MIO GPIO bundles as software SPI buses. Recommended path: use
Option A first for electrical bring-up and protocol validation, then migrate to
Option B quickly if the userspace GPIO path cannot meet the `ADC1283` timing
needed for the SoF receiver test.
