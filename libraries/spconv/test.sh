#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}"

cuda_arch="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from binary_release import native_target; print(native_target("spconv")["cuda_arch"])' "${script_dir}/../../scripts")"
bazel test \
    --compilation_mode=opt \
    --cxxopt=-std=c++17 \
    --@rules_cuda//cuda:enable=true \
    "--@rules_cuda//cuda:archs=sm_${cuda_arch#sm}" \
    @spconv//bazel:generate_test

library="bazel-bin/libspconv.so"
if [[ ! -f "${library}" ]]; then
    echo "missing shared library: ${library}; run ./build.sh first" >&2
    exit 1
fi

python3 "${script_dir}/../../scripts/binary_release.py" check-elf --library spconv "${library}"
if readelf -d "${library}" | grep -E '\((RPATH|RUNPATH)\).*(/tmp/|/home/)'; then
    echo "artifact contains a host-specific runtime search path" >&2
    exit 1
fi
