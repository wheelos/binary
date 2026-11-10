#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="${LIVEKIT_SOURCE_DIR:?set LIVEKIT_SOURCE_DIR to the checked-out upstream source}"
version="${LIVEKIT_VERSION:?set LIVEKIT_VERSION to the WheelOS release version}"
if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid LiveKit release version: ${version}" >&2
  exit 1
fi

expected_source_commit="$(python3 -c \
  'import json, pathlib, sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text())["upstream_commit"])' \
  "${script_dir}/metadata.json")"
expected_rust_commit="$(python3 -c \
  'import json, pathlib, sys; print(json.loads(pathlib.Path(sys.argv[1]).read_text())["rust_submodule_commit"])' \
  "${script_dir}/metadata.json")"
actual_source_commit="$(git -C "${source_dir}" rev-parse HEAD)"
actual_rust_commit="$(git -C "${source_dir}/client-sdk-rust" rev-parse HEAD)"

if [[ "${actual_source_commit}" != "${expected_source_commit}" ]]; then
  echo "LiveKit source commit mismatch: expected ${expected_source_commit}, got ${actual_source_commit}" >&2
  exit 1
fi
if [[ "${actual_rust_commit}" != "${expected_rust_commit}" ]]; then
  echo "LiveKit Rust submodule mismatch: expected ${expected_rust_commit}, got ${actual_rust_commit}" >&2
  exit 1
fi

platform="$(python3 "${script_dir}/../../scripts/binary_release.py" native --library livekit_sdk)"

bundle_dir="${script_dir}/dist/sdk"
mkdir -p "${script_dir}/dist"

(
  cd "${source_dir}"
  ./build.sh release \
    --bundle \
    --no-capture \
    --prefix "${bundle_dir}" \
    --version "${version}"
)

mkdir -p "${bundle_dir}/share/livekit"
cp "${source_dir}/LICENSE" "${bundle_dir}/share/livekit/LICENSE"

for required in \
  "${bundle_dir}/include/livekit/livekit.h" \
  "${bundle_dir}/include/livekit/build.h" \
  "${bundle_dir}/lib/liblivekit.so" \
  "${bundle_dir}/lib/liblivekit_ffi.so" \
  "${bundle_dir}/lib/cmake/LiveKit/LiveKitConfig.cmake" \
  "${bundle_dir}/share/livekit/build-info.json" \
  "${bundle_dir}/share/livekit/LICENSE"; do
  if [[ ! -f "${required}" ]]; then
    echo "LiveKit SDK bundle is missing ${required}" >&2
    exit 1
  fi
done

printf 'Built %s for %s\n' "${version}" "${platform}"
