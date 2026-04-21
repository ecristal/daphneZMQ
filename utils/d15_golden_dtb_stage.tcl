# DAPHNE-15 DTB staging helper for XSCT.
#
# Purpose:
#   1. Force JTAG boot.
#   2. Load PMUFW + FSBL + U-Boot + BL31 from a known-good boot-chain directory.
#   3. Wait for U-Boot to come up.
#   4. Halt A53 briefly and stage the golden DTB into DDR.
#   5. Resume execution so the user can fatwrite the DTB from the U-Boot prompt.
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
#   export DAPHNE_GOLDEN_DIR=/nfs/home/marroyav/golden/daphne14-2026-03-12
#   export DAPHNE_BOOT_ELF_DIR=/nfs/home/marroyav/daphne_v3/linux_13
#   source /nfs/sw/fpga/Xilinx/Vitis/2024.1/settings64.sh
#   xsct /path/to/d15_golden_dtb_stage.tcl
#
# After the script finishes, use the serial console and run:
#   fdt addr 0x40000000
#   fdt header
#   mmc dev 0
#   fatwrite mmc 0:1 0x40000000 system.dtb ${filesize}
#   fatwrite mmc 0:1 0x40000000 system-zynqmp-sck-kr-g-revB.dtb ${filesize}

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
set fdt_img [file join $boot_dir "system.dtb"]

foreach f [list $pmufw_elf $fsbl_elf $uboot_elf $bl31_elf $fdt_img] {
  require_file $f
}

set fdt_addr 0x40000000

puts stderr "Starting DAPHNE-15 golden DTB staging helper..."
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

# Give FSBL/BL31/U-Boot time to run and stop at the serial prompt.
after 8000

targets -set -nocase -filter {name =~ "*A53*#0"}
catch {stop}
after 1000

targets -set -nocase -filter {name =~ "*A53*#0"}
puts stderr [format "INFO: Loading golden DTB at 0x%08x from %s" $fdt_addr $fdt_img]
dow -data $fdt_img $fdt_addr
after 1000
con

puts stderr ""
puts stderr "Golden DTB staged in DDR."
puts stderr "At the ZynqMP prompt, run exactly:"
puts stderr "  fdt addr 0x40000000"
puts stderr "  fdt header"
puts stderr "  mmc dev 0"
puts stderr "  fatwrite mmc 0:1 0x40000000 system.dtb \${filesize}"
puts stderr "  fatwrite mmc 0:1 0x40000000 system-zynqmp-sck-kr-g-revB.dtb \${filesize}"
puts stderr ""
puts stderr "Then boot your RAM shell again from eMMC."
