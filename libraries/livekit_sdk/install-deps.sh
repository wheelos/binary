#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" != 0 ]]; then
  echo "Run this dependency installer as root in an Ubuntu 20.04 build container or CI runner." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg git git-lfs build-essential ninja-build pkg-config \
  python3 python3-pip \
  libva-dev libdrm-dev libgbm-dev libx11-dev libgl1-mesa-dev \
  libxext-dev libxcomposite-dev libxdamage-dev libxfixes-dev \
  libxrandr-dev libxi-dev libxkbcommon-dev libasound2-dev libpulse-dev \
  libssl-dev libprotobuf-dev protobuf-compiler \
  libcurl4-openssl-dev libwayland-dev

curl --fail --silent --show-error https://apt.llvm.org/llvm-snapshot.gpg.key \
  | gpg --dearmor --yes --output /usr/share/keyrings/wheelos-llvm.gpg
printf '%s\n' \
  'deb [signed-by=/usr/share/keyrings/wheelos-llvm.gpg] https://apt.llvm.org/focal/ llvm-toolchain-focal-21 main' \
  > /etc/apt/sources.list.d/wheelos-llvm.list
apt-get update -qq
apt-get install -y --no-install-recommends clang-21 libclang-21-dev
python3 -m pip install --no-cache-dir cmake==3.31.10
