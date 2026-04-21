# Reflash `daphne-15` From Bridge Host (USB/XSCT + Network Stream)

This procedure uses:
- `np04-onl-004.cern.ch` as bridge (files already in `/nfs/home/marroyav/daphne_v3/linux_13`)
- U-Boot/XSCT only to boot `daphne-15` into RAM shell
- network streaming (`nc | dd`) to write eMMC partitions

It avoids writing rootfs while booted from that same rootfs.

## Preconditions

- Bridge has these files:
  - `/nfs/home/marroyav/daphne_v3/linux_13/rootfs.ext4`
  - `/nfs/home/marroyav/daphne_v3/linux_13/Image`
  - `/nfs/home/marroyav/daphne_v3/linux_13/system.dtb`
  - `/nfs/home/marroyav/daphne_v3/linux_13/ramdisk.cpio.gz.u-boot`
- Serial console to `daphne-15` is available.
- `daphne-15` can reach bridge IP `10.73.138.64`.

## 1) Boot `daphne-15` to RAM shell (U-Boot prompt)

```bash
mmc dev 0
load mmc 0:1 ${kernel_addr_r} Image
load mmc 0:1 ${fdt_addr_r} system.dtb
load mmc 0:1 ${ramdisk_addr_r} ramdisk.cpio.gz.u-boot
setenv bootargs 'console=ttyPS1,115200 earlycon root=/dev/ram rw rdinit=/bin/sh'
booti ${kernel_addr_r} ${ramdisk_addr_r} ${fdt_addr_r}
```

You should land in `/#`.

## 2) Prepare minimal RAM environment on `daphne-15` (`/#`)

```sh
mkdir -p /proc /sys
mount -t proc proc /proc
mount -t sysfs sysfs /sys
echo /sbin/mdev > /proc/sys/kernel/hotplug
mdev -s

ip link set eth0 up 2>/dev/null || true
ip link set eth1 up 2>/dev/null || true
for i in eth0 eth1; do echo -n "$i carrier="; cat /sys/class/net/$i/carrier 2>/dev/null; done
```

Pick the interface with `carrier=1`.

For `daphne-15`, networking may only work if the exact registered identity is used:
- MAC: `ba:be:ba:d1:cc:ff`
- IPv4: `10.73.137.16/24`
- GW: `10.73.137.1`

Use this exact sequence (example keeps `eth0` as the active uplink):

```sh
# choose active interface after checking carrier
IFACE=eth0

# avoid duplicate routes/ARP confusion
for i in eth0 eth1; do
  ip addr flush dev $i 2>/dev/null || true
  ip link set $i down 2>/dev/null || true
done

ip link set $IFACE down
ip link set $IFACE address ba:be:ba:d1:cc:ff
ip link set $IFACE up
ip addr add 10.73.137.16/24 dev $IFACE
ip route replace default via 10.73.137.1 dev $IFACE
ping -c 3 10.73.138.64
```

## 3) Flash `mmcblk0p2` (rootfs) from bridge

### Terminal A (bridge: `np04-onl-004.cern.ch`)

```bash
cd /nfs/home/marroyav/daphne_v3/linux_13
nc -l 9002 < rootfs.ext4
```

If needed on your `nc` variant:

```bash
nc -l -p 9002 < rootfs.ext4
```

### Terminal B (`daphne-15` RAM shell)

```sh
nc 10.73.138.64 9002 | dd of=/dev/mmcblk0p2 bs=4M conv=fsync status=progress
sync
```

## 4) Update `mmcblk0p1` boot files

### On `daphne-15` RAM shell

```sh
mkdir -p /mnt/p1
mount -t vfat /dev/mmcblk0p1 /mnt/p1
```

### Copy `Image`

Bridge:

```bash
cd /nfs/home/marroyav/daphne_v3/linux_13
nc -l 9003 < Image
```

`daphne-15`:

```sh
nc 10.73.138.64 9003 > /mnt/p1/Image
sync
```

### Copy `system.dtb`

Bridge:

```bash
nc -l 9004 < system.dtb
```

`daphne-15`:

```sh
nc 10.73.138.64 9004 > /mnt/p1/system.dtb
sync
```

### Copy `ramdisk.cpio.gz.u-boot`

Bridge:

```bash
nc -l 9005 < ramdisk.cpio.gz.u-boot
```

`daphne-15`:

```sh
nc 10.73.138.64 9005 > /mnt/p1/ramdisk.cpio.gz.u-boot
sync
umount /mnt/p1
reboot -f
```

## 5) Post-boot checks on `daphne-15`

```bash
hostname
ldd --version | head -1
strings /usr/lib/libstdc++.so.6 | grep -oE 'GLIBCXX_[0-9.]+' | sort -Vu | tail -1
```

Expected runtime compatibility target:
- `glibc 2.36`
- `GLIBCXX_3.4.30`

## 6) Re-pin board identity/profile (`daphne-15`)

```bash
echo daphne-15 | sudo tee /etc/hostname
sudo sed -i '/^127\.0\.1\.1 /d' /etc/hosts
echo '127.0.1.1 daphne-15' | sudo tee -a /etc/hosts
sudo systemd-machine-id-setup

cd ~/daphne-server/utils
sudo FW_APP=MEZ_SELF_TRIG_V15_OL_UPGRADED ./bootstrap_blank_board.sh daphne-15
sudo reboot
```

## Quick troubleshooting

- `nc` errors on listen syntax:
  - try `nc -l 900X`
  - if that fails, try `nc -l -p 900X`
- No link in RAM shell:
  - check carrier on both interfaces and set IP on the one with `carrier=1`
- DNS/hostname mismatch during recovery:
  - use bridge IP directly (`10.73.138.64`) instead of hostname.
