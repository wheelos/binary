# WheelOS Binary

WheelOS Binary builds, tests, versions, and distributes native libraries. Binary artifacts are published to Cloudflare R2. Bazel registry metadata is maintained in its separate repository and references these immutable packages; Binary does not publish or modify BCR metadata.

Each library has an independent source pin, build/test scripts, version, and release workflow. The assets-infra Worker serves public assets from the `release/public/` R2 prefix at `https://dl.wheelos.cn`; immutable artifacts are stored below `/release/public/<library>/<version>/`.

## Platform and target contract

`platforms.json` defines the canonical native platforms. Each library's `metadata.json` selects its targets; build matrices, native-host checks, archive names and publication paths share `scripts/binary_release.py`.

| Canonical platform | Accepted architecture aliases | Native CI runner |
| --- | --- | --- |
| `linux-x86_64` | `x86_64`, `amd64` | Ubuntu 22.04 |
| `linux-aarch64` | `aarch64`, `arm64` | Ubuntu 22.04 |

Use aliases only at input boundaries. Archives, manifests, target IDs and URLs use canonical names. `x86` is not an alias for 64-bit x86. Docker's `amd64`/`arm64` labels are checked against the actual native host; an image tag is not proof of its architecture.

A **platform** identifies the OS and CPU architecture. A **target** adds library-specific ABI/runtime requirements: `linux-x86_64-cuda12.8-sm89`, for example. CUDA toolkit versions and GPU compute capabilities are separate from CPU architecture. Orin is hardware, not a third CPU architecture; an Orin-specific release must additionally establish its JetPack/L4T runtime baseline before activation. The native runner OS does not define a library's build ABI: LiveKit is built in Ubuntu 20.04 containers with glibc 2.31. Incompatible libc, C++ ABI or JetPack/L4T baselines need separate variants rather than replacement of existing artifacts.

| Library | Target | Pipeline |
| --- | --- | --- |
| LiveKit | `linux-x86_64` | Enabled |
| LiveKit | `linux-aarch64` | Enabled; native Actions runner configured |
| spconv | `linux-x86_64-cuda12.8-sm89` | Enabled |
| spconv | `linux-aarch64-cuda12.6-sm87` | Planned, disabled |

`enabled` means a build pipeline is available, not that hardware runtime acceptance or publication has occurred. Disabled targets carry a reason and are excluded from both the build and publication matrices. The spconv ARM64 target still needs architecture-correct codegen dependencies, generalized CUDA generation and a native Jetson environment; no environment is provisioned and no build is scheduled for it.

Artifact identity is symmetric:

```text
<archive-name>-<version>-<platform>[-cuda<major.minor>-sm<capability>].tar.gz
release/public/<library>/<version>/<platform>[/cuda<major.minor>-sm<capability>]/<archive>
```

Existing download paths are preserved. `livekit_sdk` remains the library ID and `livekit-sdk` its archive name. A requested target, the actual native host, the ELF64 shared-object architecture, and the archive name must agree; renaming an x86_64 library cannot produce an ARM64 release. `BINARY_TARGET` selects an enabled target, and `BINARY_PLATFORM` optionally asserts the expected host platform. Cross-compilation is not enabled implicitly.

The shared flow is **resolve version and enabled targets -> native build -> test -> package and SHA256 -> upload -> public download verification**. Both libraries use PR checks, independent version tags and manual build/publish dispatch. Workflow publication waits for every enabled target to succeed; the matrix publisher requires the complete enabled artifact set, while the low-level upload script transfers one archive. Failed builds or uploads are not silently skipped. Activate a planned target only after its source integration, native toolchain, ABI baseline and acceptance checks are ready; do not make unsupported targets look successful by merely changing metadata.

## Libraries

### spconv

The current build target is spconv 2.3.8 for Linux x86_64, CUDA 12.8, and SM89. The build reuses the pinned spconv Bazel integration in the Apollo-lite registry and the existing Apollo CUDA 12.8 build image. This is a build-only pilot: it does not claim runtime validation on GPU hardware or support for Orin, SM87, ARM64, or other CUDA versions.
Release archives use `https://dl.wheelos.cn/release/public/spconv/<version>/linux-x86_64/cuda12.8-sm89/`; the workflow prints the exact archive and checksum links after upload.

```bash
cd libraries/spconv
./build.sh
./test.sh
mkdir -p dist
python3 stage_headers.py --output dist/include
bazel build --compilation_mode=opt \
  --cxxopt=-std=c++17 \
  --@rules_cuda//cuda:enable=true \
  --@rules_cuda//cuda:archs=sm_89 \
  @spconv//:licenses
mapfile -t licenses < <(
  bazel cquery \
    --compilation_mode=opt \
    --cxxopt=-std=c++17 \
    --@rules_cuda//cuda:enable=true \
    --@rules_cuda//cuda:archs=sm_89 \
    --output=files @spconv//:licenses
)
python3 package.py \
  --binary bazel-bin/libspconv.so \
  --include-dir dist/include \
  --license "${licenses[0]}" \
  --license "${licenses[1]}" \
  --version 2.3.8-wheelos.1 \
  --output dist/spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz
```

Run the build inside the pinned Apollo CUDA 12.8 development container. Run it as the invoking user, not as root, and mount this repository into the container. The image supplies Bazel 8.8.1, CUDA 12.8, and TensorRT; Bazel resolves the library's pinned Bzlmod dependencies. Do not install CUDA, TensorRT, or library dependencies ad hoc.

### LiveKit SDK

LiveKit SDK is built from upstream `client-sdk-cpp` v1.13.0 and its pinned Rust submodule in native Ubuntu 20.04 containers on x86_64 and ARM64 runners, providing a glibc 2.31 build baseline. The release runs the upstream installed-SDK packaging smoke test before creating platform-specific archives. The separate BCR repository can reference the resulting platform-specific SDK archives and checksums.

Release tags use `livekit_sdk/v<version>`, for example `livekit_sdk/v1.13.0-wheelos.2`. Artifacts are published to:

- `https://dl.wheelos.cn/release/public/livekit_sdk/<version>/linux-x86_64/livekit-sdk-<version>-linux-x86_64.tar.gz`
- `https://dl.wheelos.cn/release/public/livekit_sdk/<version>/linux-aarch64/livekit-sdk-<version>-linux-aarch64.tar.gz`

For a local native source build, use Rust 1.97.1, LLVM 21 and CMake 3.31.10. On a dedicated Ubuntu 20.04 build machine, `sudo bash libraries/livekit_sdk/install-deps.sh` installs the non-Rust dependencies. The Dockerfile provides the complete isolated toolchain; run the SDK build as the invoking user, not root.

Check out the pinned upstream and build it:

```bash
git clone https://github.com/livekit/client-sdk-cpp.git /tmp/livekit-sdk
git -C /tmp/livekit-sdk checkout e7d33fd86201b288b43d7002516d52ab9b0d3641
git -C /tmp/livekit-sdk submodule update --init --recursive
git -C /tmp/livekit-sdk lfs pull
export CC=clang-21 CXX=clang++-21 LIBCLANG_PATH=/usr/lib/llvm-21/lib
export CMAKE_BUILD_PARALLEL_LEVEL=2 CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0
LIVEKIT_SOURCE_DIR=/tmp/livekit-sdk \
LIVEKIT_VERSION=1.13.0-wheelos.2 \
  ./libraries/livekit_sdk/build.sh
LIVEKIT_SOURCE_DIR=/tmp/livekit-sdk \
LIVEKIT_VERSION=1.13.0-wheelos.2 \
  ./libraries/livekit_sdk/test.sh
python3 libraries/livekit_sdk/package.py \
  --version 1.13.0-wheelos.2 \
  --output libraries/livekit_sdk/dist/livekit-sdk-1.13.0-wheelos.2-linux-x86_64.tar.gz
```

The standard bundle includes the C++ SDK and Rust FFI libraries without optional capture backends. Build ARM64 on a native ARM64 host; an x86_64 build does not validate ARM64.

To use the isolated toolchain with the source checkout above:

```bash
docker build -t wheelos-binary-livekit:local -f libraries/livekit_sdk/Dockerfile .
mkdir -p .cache/livekit-home
docker run --rm --cpus=3 --memory=10g --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" -v /tmp/livekit-sdk:/livekit-source \
  -e HOME=/workspace/.cache/livekit-home \
  -e LIVEKIT_SOURCE_DIR=/livekit-source -e LIVEKIT_VERSION=1.13.0-wheelos.2 \
  wheelos-binary-livekit:local bash -c \
  'libraries/livekit_sdk/build.sh && libraries/livekit_sdk/test.sh &&
   python3 libraries/livekit_sdk/package.py --version "$LIVEKIT_VERSION" \
     --output "libraries/livekit_sdk/dist/livekit-sdk-${LIVEKIT_VERSION}-linux-$(uname -m).tar.gz"'
```

Use a fresh source build directory when switching between host and container paths.

### Release configuration

The `spconv/v*` and `livekit_sdk/v*` tag workflows build and validate packages before uploading immutable objects directly to the `wheelos-assets` R2 bucket (override with `R2_BUCKET_NAME` or `R2_BUCKET` repository variables). Configure the `binary-release` GitHub environment, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_ACCOUNT_ID` secrets (`CF_ACCOUNT_ID` is accepted as a compatibility fallback). Objects are placed under `release/public/`, which the assets-infra Worker exposes without Basic Auth; other `release/` paths are private. The workflows form public URLs as `https://dl.wheelos.cn/<R2 object key>`, download through the Worker, verify SHA256, and print the links in the Actions summary. Build-image credentials are only needed if the pinned spconv image is private. The Worker route and its R2 binding must be configured in assets-infra.

Each release is immutable. A version bump is required for changed source, build inputs, ABI, or packaging. The spconv archive includes its shared object, generated C++ headers, upstream license notices, and a build manifest. The LiveKit archives include the SDK shared libraries, headers, CMake package files, license, and a build manifest. Workflows upload only release packages and SHA256 sidecars; the separate BCR repository owns module metadata and points to these public URLs. No `.so` is committed to the BCR.

### Script or Actions upload

Both library workflows use `scripts/upload.sh`. Locally, install a recent AWS CLI v2 supporting `s3api put-object --if-none-match`, and provide `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` through the environment (never commit them). `R2_BUCKET_NAME` defaults to `wheelos-assets`; `CF_ACCOUNT_ID`, `R2_BUCKET`, and standard AWS key variables are also accepted.

```bash
bash scripts/upload.sh \
  libraries/livekit_sdk/dist/livekit-sdk-1.13.0-wheelos.2-linux-x86_64.tar.gz \
  release/public/livekit_sdk/1.13.0-wheelos.2/linux-x86_64
```

The script validates the local SHA256 sidecar, refuses existing objects, uses atomic conditional writes, downloads both objects through the public Worker URL, and prints the verified download URL and SHA256. A partially uploaded release is reported as a failure, not success; inspect the objects before retrying with a new version.

Both libraries support manual Actions execution, with publishing disabled by default:

```bash
gh workflow run livekit-sdk-release.yml -f version=1.13.0-wheelos.2 -f publish=false
gh workflow run spconv-release.yml -f version=2.3.8-wheelos.1 -f publish=false
# Build and validate both native architectures, then publish using binary-release credentials:
gh workflow run livekit-sdk-release.yml -f version=1.13.0-wheelos.2 -f publish=true
```

The workflow file must be present on the repository's default branch before manual dispatch is available. Tag-based releases remain supported.

Inspect the enabled build matrix without running builds:

```bash
python3 scripts/binary_release.py matrix --library livekit_sdk
python3 scripts/binary_release.py matrix --library spconv
```

## Current boundary

The spconv Bazel target is compatible only with Linux x86_64 and CUDA 12.8 / SM89 flags; consumers must provide their CUDA toolchain and runtime. The WheelOS Bazel Central Registry revision is pinned in `libraries/spconv/.bazelrc` as the pilot's source-build integration. The Binary repo remains independently buildable from a pinned, public registry revision; the library build itself is not coupled to an Apollo-lite checkout. The R2 upload workflow is not a substitute for target-device validation: an SM89 release is not an Orin/SM87 release.
