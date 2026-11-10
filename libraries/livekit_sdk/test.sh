#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="${LIVEKIT_SOURCE_DIR:?set LIVEKIT_SOURCE_DIR to the checked-out upstream source}"
bundle_dir="${LIVEKIT_BUNDLE_DIR:-${script_dir}/dist/sdk}"
version="${LIVEKIT_VERSION:?set LIVEKIT_VERSION to the WheelOS release version}"

platform="$(python3 "${script_dir}/../../scripts/binary_release.py" native --library livekit_sdk)"
python3 "${script_dir}/../../scripts/binary_release.py" check-elf --library livekit_sdk \
  "${bundle_dir}/lib/liblivekit.so" "${bundle_dir}/lib/liblivekit_ffi.so"

if ! readelf -d "${bundle_dir}/lib/liblivekit.so" | grep -Fq "\$ORIGIN"; then
  echo "liblivekit.so must locate its bundled FFI library through \$ORIGIN" >&2
  exit 1
fi

test_build_dir="$(mktemp -d "${TMPDIR:-/tmp}/livekit-sdk-packaging.XXXXXX")"
trap 'rm -rf -- "${test_build_dir}"' EXIT
cmake -S "${source_dir}/src/tests/packaging" -B "${test_build_dir}" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="${bundle_dir}" \
  -DLIVEKIT_CAPTURE=none \
  -DLIVEKIT_EXPECT_VERSION="${version}" \
  -DLIVEKIT_VERIFY_PIXEL_SOURCES=OFF
cmake --build "${test_build_dir}" --config Release --parallel 2
ctest --test-dir "${test_build_dir}" -C Release --output-on-failure -L packaging

printf 'Validated %s on %s\n' "${version}" "${platform}"
