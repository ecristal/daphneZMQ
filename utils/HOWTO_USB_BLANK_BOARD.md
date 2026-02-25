# USB-Only Blank Board Bootstrap (DAPHNE)

This runbook is for a board that boots but has no working network config yet.
Goal: bring link up from serial console, sync time, copy/update repo, and install persistent services.

## Fast path (single command)

If repo is already present on the board (`~/daphne-server`), run:

```bash
cd ~/daphne-server/utils
sudo ./bootstrap_blank_board.sh daphne-15
```

Options:

- skip firmware service install:
  - `sudo ./bootstrap_blank_board.sh daphne-15 --no-firmware`
- only temporary emergency bring-up (no persistent files):
  - `sudo ./bootstrap_blank_board.sh daphne-15 --bootstrap-only`

## 0) Known board values

Use these values (same as `ff0b_board_inventory.csv`):

- `daphne-13`
  - IPv4: `10.73.137.161/24`
  - GW: `10.73.137.1`
  - MAC ff0b: `ba:be:ba:d1:ca:ff`
  - MAC ff0c: `ba:be:ba:d1:ca:fe`
- `daphne-14`
  - IPv4: `10.73.137.160/24`
  - GW: `10.73.137.1`
  - MAC ff0b: `ba:be:ba:d1:cb:ff`
  - MAC ff0c: `ba:be:ba:d1:cb:fe`
- `daphne-15`
  - IPv4: `10.73.137.16/24`
  - GW: `10.73.137.1`
  - MAC ff0b: `ba:be:ba:d1:cc:ff`
  - MAC ff0c: `ba:be:ba:d1:cc:fe`

Common DNS:

- `137.138.16.5`
- `137.138.17.5`

## 1) Connect via serial

Use `115200 8N1` and disable HW/SW flow control.

Example:

```bash
screen -S daphne-15 /dev/ttyUSB2 115200
```

## 2) One-shot emergency network bring-up (from serial shell)

Set the board ID and run:

```bash
BOARD_ID=daphne-15   # change to daphne-13 or daphne-14

case "$BOARD_ID" in
  daphne-13) IPV4=10.73.137.161/24; GW=10.73.137.1; MAC_FF0B=ba:be:ba:d1:ca:ff; MAC_FF0C=ba:be:ba:d1:ca:fe ;;
  daphne-14) IPV4=10.73.137.160/24; GW=10.73.137.1; MAC_FF0B=ba:be:ba:d1:cb:ff; MAC_FF0C=ba:be:ba:d1:cb:fe ;;
  daphne-15) IPV4=10.73.137.16/24;  GW=10.73.137.1; MAC_FF0B=ba:be:ba:d1:cc:ff; MAC_FF0C=ba:be:ba:d1:cc:fe ;;
  *) echo "Unknown BOARD_ID"; exit 1 ;;
esac

FF0B_IF=$(basename /sys/devices/platform/axi/ff0b0000.ethernet/net/*)
FF0C_IF=$(basename /sys/devices/platform/axi/ff0c0000.ethernet/net/* 2>/dev/null || true)

sudo ip link set "$FF0B_IF" down || true
[ -n "$FF0C_IF" ] && sudo ip link set "$FF0C_IF" down || true

sudo ip addr flush dev "$FF0B_IF" || true
[ -n "$FF0C_IF" ] && sudo ip addr flush dev "$FF0C_IF" || true
while sudo ip route del default 2>/dev/null; do :; done

sudo ip link set "$FF0B_IF" address "$MAC_FF0B"
[ -n "$FF0C_IF" ] && sudo ip link set "$FF0C_IF" address "$MAC_FF0C" || true

sudo ip link set "$FF0B_IF" up
[ -n "$FF0C_IF" ] && sudo ip link set "$FF0C_IF" up || true

sudo ip addr replace "$IPV4" dev "$FF0B_IF"
sudo ip route replace default via "$GW" dev "$FF0B_IF"

sudo tee /etc/resolv.conf >/dev/null <<'EOF'
nameserver 137.138.16.5
nameserver 137.138.17.5
options timeout:1 attempts:2
EOF

ip -4 addr show dev "$FF0B_IF"
ip route
ping -c 3 10.73.137.1
```

## 3) Time sync first (required for TLS/git)

```bash
sudo mkdir -p /etc/systemd/timesyncd.conf.d
sudo tee /etc/systemd/timesyncd.conf.d/cern.conf >/dev/null <<'EOF'
[Time]
NTP=137.138.16.69 137.138.17.69 137.138.18.69
FallbackNTP=
EOF

sudo systemctl enable --now systemd-timesyncd
sudo timedatectl set-ntp true
timedatectl status
```

If date is still wrong and NTP does not converge quickly, set time manually once:

```bash
sudo timedatectl set-ntp false
sudo timedatectl set-time "2026-02-24 12:00:00"
sudo timedatectl set-ntp true
date -u
```

## 4) Proxy/git env for this shell

If repo already exists:

```bash
source ~/daphne-server/utils/web_proxy.sh -p
```

If repo does not exist yet:

```bash
export HTTP_PROXY=http://np04-web-proxy.cern.ch:3128
export HTTPS_PROXY=http://np04-web-proxy.cern.ch:3128
export NO_PROXY=.cern.ch
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export no_proxy=$NO_PROXY
```

## 5) Get repo onto the board

### Option A: clone from GitHub

```bash
cd ~
git clone https://github.com/ecristal/daphneZMQ.git daphne-server
cd ~/daphne-server
git checkout server
git pull --rebase origin server
```

### Option B: copy from another board (if git still blocked)

From destination board:

```bash
cd ~
scp -O -r petalinux@np04-daphne-013.cern.ch:~/daphne-server .
```

If `scp` is unavailable/broken, use tar over ssh:

```bash
ssh petalinux@np04-daphne-013.cern.ch 'tar -C ~ -cf - daphne-server' | tar -C ~ -xf -
```

Note: `-O` is required when remote misses `sftp-server`.

## 5.1) Build `daphne-server` and `hermes` (manual tarball copy explained)

### Why tarball copy is manual

For standalone `daphne-server` builds, the deps tarball is pinned by filename+SHA in
`deps/deps.lock.cmake`. The board-side script cannot reliably auto-download it because:

- source location differs (another board, local laptop, shared path),
- auth/network/proxy availability differs per board state,
- exact tarball name must match the lock file.

So transfer is a one-time manual step, then build is automatic.

### Build `daphne-server` (pinned deps tarball in checkout)

1. Check expected tarball name:

```bash
cd ~/daphne-server
grep DAPHNE_DEPS_TARBALL_NAME deps/deps.lock.cmake
```

2. Copy that tarball into `deps_tarballs/` (manual):

From another board:

```bash
cd ~/daphne-server
scp -O petalinux@np04-daphne-013.cern.ch:~/daphne-server/deps_tarballs/<exact-tarball-name>.tar.gz ./deps_tarballs/
```

From your laptop/workstation:

```bash
scp -O /path/to/<exact-tarball-name>.tar.gz \
  petalinux@np04-daphne-015.cern.ch:~/daphne-server/deps_tarballs/
```

3. Build:

```bash
cd ~/daphne-server
./scripts/petalinux_build.sh ./build-petalinux ./deps_tarballs
ls -l ./build-petalinux/daphneServer ./build-petalinux/daphne_zmq_server
```

### Build Hermes (`hermesmodules`)

```bash
cd ~
git clone https://github.com/DUNE-DAQ/hermesmodules.git -b thea/daphne_integration
cd ~/hermesmodules/soc
make clean && make
```

Install binary for the service path used in this repo (`/bin/hermes_udp_srv`):

```bash
sudo install -m 0755 ~/hermesmodules/soc/hermes_udp_srv /bin/hermes_udp_srv
ls -l /bin/hermes_udp_srv
```

If your build outputs a different binary name, install that one instead and update
`/etc/systemd/system/hermes.service` accordingly.

## 6) Install persistent baseline (network + dns + ntp + hostname + proxy/git)

```bash
cd ~/daphne-server/utils
sudo ./install_ff0b_network.sh daphne-15   # change per board
```

This installs:

- `/etc/systemd/network/10-ff0b.link`
- `/etc/systemd/network/11-ff0c.link`
- `/etc/systemd/network/20-ff0b.network`
- `/etc/systemd/network/21-ff0c.network`
- `/etc/default/ff0b-net.conf`
- `/usr/local/sbin/ff0b-net-apply.sh`
- `/etc/systemd/system/force-ff0b-net.service`
- `/etc/systemd/timesyncd.conf.d/cern.conf`
- `/etc/profile.d/np04-proxy.sh`

## 7) Install default firmware boot app

```bash
cd ~/daphne-server/utils
sudo FW_APP=MEZ_SELF_TRIG_V15_OL_UPGRADED ./setup_firmware_service.sh
sudo systemctl restart firmware.service
```

## 8) Verify and reboot test

```bash
systemctl status force-ff0b-net.service --no-pager
systemctl status firmware.service --no-pager
timedatectl status
ip -br link
ip -4 addr
ip route
xmutil listapps
```

Then reboot:

```bash
sudo reboot
```

After reboot, verify again:

```bash
hostname
ip -4 addr
ip route
timedatectl status
xmutil listapps
```

## 9) Known failure patterns

- `SSL certificate problem: certificate is not yet valid`
  - clock is wrong; fix step 3.
- `scp ... /usr/libexec/sftp-server: No such file or directory`
  - use `scp -O` or tar-over-ssh.
- `Input/output error` for basic binaries (`ls`, `sudo`, `ip`)
  - filesystem/storage issue; do not continue config, run fsck/recovery first.
