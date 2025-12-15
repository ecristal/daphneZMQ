# This file pins the exact dependency tarball required to build this repo in
# "standalone" mode (no external prefix like ~/zmq, no network downloads).
#
# How to create/update:
#   - On a reference Petalinux machine (or in a matching SDK container), build
#     your deps prefix (protobuf + abseil + zeromq + headers).
#   - Run: scripts/make_deps_tarball_from_prefix.sh /path/to/prefix out/
#   - Paste the emitted name+sha256 into this file and commit.
#
# The build will refuse to configure if the tarball name or SHA256 does not
# match.

set(DAPHNE_DEPS_TARBALL_NAME "daphne-deps-petalinux2024.1-aarch64-glibc2.36-protobuf30.1-zeromq4.3.4.tar.gz")
set(DAPHNE_DEPS_TARBALL_SHA256 "PUT_REAL_SHA256_HERE")

