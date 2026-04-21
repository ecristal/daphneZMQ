# DAPHNE-15 recovery helper for XSCT.
#
# Purpose:
#   1. Force JTAG boot.
#   2. Load PMUFW + FSBL + U-Boot + BL31 from a known-good boot-chain directory.
#   3. Preload the golden kernel, DTB, and ramdisk into DDR.
#   4. Hand control to U-Boot and print the exact booti command for a RAM shell.
#
# Default layout:
#   Golden bundle root:
#     /nfs/home/marroyav/golden/daphne14-2026-03-12
#   Legacy boot-chain ELFs:
#     /nfs/home/marroyav/daphne_v3/linux_13
#
# Overrides:
#   export DAPHNE_GOLDEN_DIR=/path/to/daphne14-2026-03-12
#   export DAPHNE_BOOT_ELF_DIR=/path/to/linux_13
#
# Usage:
#   source /nfs/home/marroyav/daphne_v3/linux_13/settings64.sh   ;# or Vitis settings
#   xsct /path/to/d15_golden_ram_boot.tcl
#   # or inside xsct:
#   source /path/to/d15_golden_ram_boot.tcl

proc require_file {path} {
  if {![file exists $path]} {
    error "Missing required file: $path"
  }
}

proc env_or_default {name default_value} {
  if {[info exists ::env($name)] && $::env($name) ne ""} {
    return $::env($name)
  }
  return $default_value
}

set script_dir [file normalize [file dirname [info script]]]
set default_golden_dir $script_dir
set golden_dir [file normalize [env_or_default "DAPHNE_GOLDEN_DIR" $default_golden_dir]]
set boot_dir [file join $golden_dir "boot"]

set default_elf_dir "/nfs/home/marroyav/daphne_v3/linux_13"
set elf_dir [file normalize [env_or_default "DAPHNE_BOOT_ELF_DIR" $default_elf_dir]]

set pmufw_elf [file join $elf_dir "pmufw.elf"]
set fsbl_elf [file join $elf_dir "zynqmp_fsbl.elf"]
set uboot_elf [file join $elf_dir "u-boot.elf"]
set bl31_elf [file join $elf_dir "bl31.elf"]

set kernel_img [file join $boot_dir "Image"]
set ramdisk_img [file join $boot_dir "ramdisk.cpio.gz.u-boot"]
set fdt_img [file join $boot_dir "system.dtb"]

foreach f [list $pmufw_elf $fsbl_elf $uboot_elf $bl31_elf $kernel_img $ramdisk_img $fdt_img] {
  require_file $f
}

set kernel_addr 0x30000000
set ramdisk_addr 0x38000000
set fdt_addr 0x40000000
set bootargs "console=ttyPS1,115200 earlycon root=/dev/ram rw rdinit=/bin/sh devtmpfs.mount=1"

puts stderr "Starting DAPHNE-15 golden RAM boot helper..."
puts stderr "Golden bundle: $golden_dir"
puts stderr "Boot-chain ELFs: $elf_dir"

connect

targets -set -nocase -filter {name =~ "PSU"}
puts stderr "INFO: Forcing JTAG boot and resetting PSU."
mwr 0xffca0010 0x0
mwr 0xff5e0200 0x0100
rst -system
after 2000

targets -set -nocase -filter {name =~ "PSU"}
mwr 0xffca0038 0x1ff

targets -set -nocase -filter {name =~ "MicroBlaze PMU"}
catch {stop}
after 1000
puts stderr "INFO: Downloading PMUFW: $pmufw_elf"
dow -force $pmufw_elf
after 2000
con

after 5000
targets -set -nocase -filter {name =~ "Cortex-A53*#0"}
rst -proc -clear-registers
after 2000
puts stderr "INFO: Downloading FSBL: $fsbl_elf"
dow -force $fsbl_elf
after 2000
con
after 4000
catch {stop}
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr "INFO: Downloading U-Boot ELF: $uboot_elf"
dow -force $uboot_elf
after 2000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr "INFO: Downloading BL31 ELF: $bl31_elf"
dow -force $bl31_elf
after 2000
con
after 8000

targets -set -nocase -filter {name =~ "*A53*#0"}
catch {stop}
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr [format "INFO: Loading golden kernel at 0x%08x from %s" $kernel_addr $kernel_img]
dow -data $kernel_img $kernel_addr
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr [format "INFO: Loading golden ramdisk at 0x%08x from %s" $ramdisk_addr $ramdisk_img]
dow -data $ramdisk_img $ramdisk_addr
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr [format "INFO: Loading golden DTB at 0x%08x from %s" $fdt_addr $fdt_img]
dow -data $fdt_img $fdt_addr
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
con

puts stderr ""
puts stderr "When the ZynqMP prompt appears, run exactly:"
puts stderr [format "  setenv bootargs '%s'" $bootargs]
puts stderr [format "  booti 0x%08x 0x%08x 0x%08x" $kernel_addr $ramdisk_addr $fdt_addr]
puts stderr ""
puts stderr "After the RAM shell comes up:"
puts stderr "  mount /proc, /sys, /dev and then configure eth with the daphne-15 MAC/IP."
puts stderr "  Stream /nfs/home/marroyav/golden/daphne14-2026-03-12/mmcblk0p2.ext4.img.gz into /dev/mmcblk0p2."
puts stderr "  Copy the files in boot/ into /dev/mmcblk0p1."
puts stderr ""
puts stderr "Finished."
