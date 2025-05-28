#!/bin/bash

# This test to write and read the AFE registers.
# The issue is that AFE0 and AFE1 read anwrite succesfully but not AFE2, AFE3 and AFE4.
# The issue was though to be a hardware problem but the issue persists in the 
# DAPHNE Mezz at CERN. 

#Fisrt let's define the adress variables of each AFE
AFE0_ADDR=0x80000004
AFE1_ADDR=0x80000010
AFE2_ADDR=0x8000001C
AFE3_ADDR=0x80000028
AFE4_ADDR=0x80000034

#Ok now let's do a for loop of each AFE witring and reading specific registers
for AFE_ADDR in $AFE0_ADDR $AFE1_ADDR $AFE2_ADDR $AFE3_ADDR $AFE4_ADDR
do
    # Write to the register
    VALUE="0x332046"
    echo "Writing to AFE at address $AFE_ADDR the value $VALUE"
    sudo poke $AFE_ADDR $VALUE
    # Check if the write was successful
    echo "Verifying write to AFE at address $AFE_ADDR"
    sudo poke $AFE_ADDR 0x2
    sudo poke $AFE_ADDR 0x330000
    sudo peek $AFE_ADDR
    sudo poke $AFE_ADDR 0x0
done
