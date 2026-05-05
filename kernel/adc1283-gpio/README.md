# ADC1283 GPIO/IIO Kernel Driver for DAPHNE MEZ0

This driver is an ADC1283-specific GPIO bit-banged IIO driver for the DAPHNE
mezzanine PS MIO pins.

It is not a generic SPI master and it does not expose `/dev/spidevX.0`.

The driver binds to:

```dts
compatible = "daphne,adc1283-gpio";