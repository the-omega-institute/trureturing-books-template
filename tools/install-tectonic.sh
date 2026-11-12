#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Pinned release binaries. Destination is explicit: no implicit global install.
set -euo pipefail
tectonic_dest="${1:?usage: tools/install-tectonic.sh DESTINATION}"
case "$(uname -m)" in
  x86_64) tectonic_arch=x86_64; tectonic_sum=60b13a0826ae7ad9ce34b4a2df06bff2cfcfa6dda8a915477c0cbb84e1a4a902 ;;
  aarch64|arm64) tectonic_arch=aarch64; tectonic_sum=f9aa39017dbd51f111fdb93dda222178cbe51c8193508fc567b523cc74fff9c1 ;;
  *) echo 'Unsupported Tectonic architecture' >&2; exit 1 ;;
esac
if [ "$(uname -s)" != Linux ]; then
  echo 'This installer supplies Linux CI/container binaries. On other systems set TECTONIC to Tectonic 0.16.9.' >&2
  exit 1
fi
mkdir -p "$tectonic_dest"
tectonic_archive="$tectonic_dest/tectonic-0.16.9.tar.gz"
curl -fsSL --retry 3 "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-${tectonic_arch}-unknown-linux-musl.tar.gz" -o "$tectonic_archive"
echo "$tectonic_sum  $tectonic_archive" | sha256sum --check
tar -xzf "$tectonic_archive" -C "$tectonic_dest" tectonic
rm "$tectonic_archive"
"$tectonic_dest/tectonic" --version
