#!/bin/bash

AFE0_FRAME_REG=0x90008000
AFE1_FRAME_REG=0x90011000
AFE2_FRAME_REG=0x9001A000
AFE3_FRAME_REG=0x90023000
AFE4_FRAME_REG=0x9002C000

# Trigger
sudo poke 0x88000008 0xBABA
###########

for i in $(seq 0x0 0x3FF);
do
    sudo peek $((AFE1_FRAME_REG + 4 * i))
done