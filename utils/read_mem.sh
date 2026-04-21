#!/usr/bin/env bash
# read_mem.sh
ADDR=0xa0000004
COUNT=2048        # number of reads
LOG=log.txt
rm log.txt
devmem 0xA0000000 32 0x1

#devmem 0xA0000000 
for ((i=0; i<COUNT; i++)); do
  val=$(sudo devmem $ADDR)
  printf  "%s %s\n" "$val" >> "$LOG"
done
