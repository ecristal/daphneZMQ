# HD Mezzanine Digital Control Context

This note captures the digital section of the HD mezzanine schematic provided in:

- `C:\Users\e_cri\Downloads\HD_Mezz_V2_1.pdf`

The goal is to anchor future `HDMezzDriver` work to the actual board wiring.

## Schematic scope

The HD mezzanine schematic has two pages.

- Page 1 contains the digital control, rail monitoring, enable gating, and the
  top-level connections to the AFE channels.
- Page 2 contains the repeated analog `diff2singleEnded` channel circuitry.

For driver work, page 1 is the relevant page.

## Digital components present on the HD mezzanine

From page 1, the main digital-control parts are:

- `U7`: `INA232AIDDFR`
  - 5 V rail monitor
  - I2C address shown in the schematic: `1000010` = `0x42`

- `U8`: `INA232AIDDFR`
  - CE rail monitor
  - I2C address shown in the schematic: `1000000` = `0x40`

- `U9`: `TCA9536DGKR`
  - 4-bit I2C GPIO expander
  - I2C address shown in the schematic: `1000001` = `0x41`

- `U5`, `U6`: `SN74LVC1G08DCKR`
  - single 2-input AND gates
  - these are used as hardware interlocks between GPIO outputs and alert lines

- `U3`, `U4`: `TPS7A9001DSKR`
  - adjustable LDO regulators in the power-enable path

The existing software address map already matches the schematic:

- `INA232_5V_ADDR = 0x42`
- `INA232_3V3_ADDR = 0x40`
- `TCA9536_ADDR = 0x41`

That mapping is defined in `srcs/defines.hpp`.

## What the current software gets right

The current `HDMezzDriver` correctly matches the board at a high level:

- it selects one mezzanine via `I2C_EXP_MEZZ`
- it talks to two `INA232` devices
- it talks to one `TCA9536`
- it configures current calibration and alert limits
- it uses the expander outputs to control the rail state

This confirms that the current driver is targeting the actual HD mezzanine
digital section, not a different board.

## Important hardware behavior from the schematic

### 1. The two monitored rails are 5 V and CE

The schematic does not label the second INA232 rail as `3V3`.

The second monitor is connected to:

- `INP_CE`
- `INN_CE`
- `ALERT_CE`

and the rail naming around that section is:

- `+CE`
- `+CE_F`

So the software names:

- `INA232_3V3_ADDR`
- `r_shunt_3V3`
- `max_current_3V3_scale`
- `readRailVoltage3V3()`

do not match the current schematic naming.

Functionally this may still work, but the naming is misleading. Based on the
schematic, that path is a CE rail, not a 3.3 V rail.

### 2. The TCA9536 outputs are not the final power enables

This is the most important digital-system detail in the schematic.

`U9` does not appear to drive the regulator enables directly.

Instead:

- `U9.P0 -> GPIO_P0`
- `U9.P1 -> GPIO_P1`

Those GPIO signals feed:

- `U5` together with `ALERT_5V`
- `U6` together with `ALERT_CE`

The outputs of the AND gates become:

- `EN_5V_J`
- `EN_CE_J`

So the actual rail-enable path is:

- software enable request from `TCA9536`
- AND hardware alert state from `INA232`
- output drives the regulator-enable net

This means the board has a built-in hardware interlock:

- the rail is only enabled if software requests it and the corresponding
  alert path permits it

### 3. Alert wiring exists but software only programs it partially

The current driver writes:

- INA232 calibration register
- INA232 alert-limit register
- INA232 mask-enable register

That is good, but the driver currently does not:

- read back the mask/enable register
- read the alert-limit register back for verification
- expose the alert flags or manufacturer ID through the API
- expose whether the alert line is actively inhibiting the enable path

Since the alert outputs are hardwired into the enable logic, this is worth
surfacing in software.

### 4. The enable logic is likely active-high after gating

From the sheet:

- `GPIO_P0` and `GPIO_P1` drive the AND gates
- `ALERT_5V` and `ALERT_CE` are the other AND inputs
- gate outputs are `EN_5V_J` and `EN_CE_J`

The current software assumes:

- `TCA9536` bit 0 controls the 5 V path
- `TCA9536` bit 1 controls the CE path
- setting the bit to `1` means power on

This is probably correct, but the real outcome also depends on the active level
of the INA232 alert output and the exact gate truth table in the fault case.

That behavior should be validated against the board during bring-up.

## Current driver limitations seen from the schematic

The following gaps are visible once the schematic is compared to the code.

### 1. CE path is mislabeled as 3V3 in software

Files affected conceptually:

- `srcs/DaphneI2CDrivers.hpp`
- `srcs/DaphneI2CDrivers.cpp`
- API messages and client strings

The software uses `3V3` naming for the second monitored rail, but the
schematic labels it as `CE`.

This is mostly a naming problem, but it can easily confuse future work and
mislead users of the client.

### 2. No explicit status API for alerts or gate state

Because the board uses:

- `INA232 ALERT`
- `SN74LVC1G08`
- `TCA9536 GPIO`

the system has more state than just voltage/current/power.

Useful future status fields would be:

- requested enable bit from TCA9536
- current TCA9536 output register
- INA232 mask/enable register
- INA232 alert status
- whether the rail is effectively enabled or being blocked by alert logic

### 3. No board-presence or identity checks

The INA232 devices expose manufacturer/device ID registers.

The driver currently does not verify:

- device presence
- expected manufacturer ID
- expected register readback after configuration

Those checks would make the bring-up path much safer.

### 4. The TCA9536 configuration is minimal

The current code writes:

- `TCA9536_CONF_REG = 0xF0`

and then toggles bits in the output port.

Future improvement should verify:

- actual port direction after write
- initial output-port contents
- whether unused bits need deterministic initialization

## Official datasheet references

These are the relevant vendor product pages for the digital section:

- INA232:
  - https://www.ti.com/product/INA232/part-details/INA232AIDDFR

- TCA9536:
  - https://www.ti.com/product/TCA9536/part-details/TCA9536DGKR

- SN74LVC1G08:
  - https://www.ti.com/product/SN74LVC1G08

- TPS7A9001 / TPS7A90:
  - https://www.ti.com/product/TPS7A90/part-details/TPS7A9001DSKR

## Recommended next driver improvements

The best next steps are:

1. Rename the second rail path from `3V3` to `CE` everywhere the public API
   allows it.

2. Add low-level helper methods for digital bring-up:
   - read INA232 manufacturer ID
   - read INA232 mask/enable register
   - read INA232 alert-limit register
   - read TCA9536 input register
   - read TCA9536 output register
   - read TCA9536 configuration register

3. Add a new status API that exposes not only telemetry but also the digital
   control state:
   - requested enable state
   - actual expander output state
   - alert-related state

4. Add configuration verification after `configureHdMezzAfeBlock()`:
   - write register
   - read it back
   - fail clearly if the value does not match

5. Decide whether the Python client should visually distinguish:
   - requested ON
   - alert-blocked OFF
   - measured rail present

That would make the console much closer to the actual hardware behavior.
