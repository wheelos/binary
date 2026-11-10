#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../.." && pwd)"
cd "${script_dir}"

target="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from binary_release import native_target; t = native_target("spconv"); print(t["cuda_version"], t["cuda_arch"])' "${repo_root}/scripts")"
read -r expected_cuda cuda_arch <<< "${target}"

if ! command -v nvcc >/dev/null 2>&1; then
    echo "nvcc is required; run this build in the pinned CUDA ${expected_cuda} container" >&2
    exit 1
fi
cuda_version="$(nvcc --version | sed -n 's/.*release \([0-9.]*\).*/\1/p')"
if [[ "${cuda_version}" != "${expected_cuda}" ]]; then
    echo "expected CUDA ${expected_cuda}, found ${cuda_version:-unknown}" >&2
    exit 1
fi

bazel_version="$(bazel version | sed -n 's/^Build label: //p')"
expected_bazel_version="$(cat "${repo_root}/.bazelversion")"
if [[ "${bazel_version}" != "${expected_bazel_version}" ]]; then
    echo "expected Bazel ${expected_bazel_version}, found ${bazel_version:-unknown}" >&2
    exit 1
fi

bazel build \
    --compilation_mode=opt \
    --cxxopt=-std=c++17 \
    --@rules_cuda//cuda:enable=true \
    "--@rules_cuda//cuda:archs=sm_${cuda_arch#sm}" \
    //:libspconv.so
