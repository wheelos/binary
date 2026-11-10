FROM ubuntu:22.04

COPY libraries/livekit_sdk/install-deps.sh /tmp/install-livekit-deps.sh
RUN bash /tmp/install-livekit-deps.sh && rm -rf /var/lib/apt/lists/

ARG RUST_VERSION=1.97.1
ENV RUSTUP_HOME=/opt/rustup
RUN curl --fail --silent --show-error https://sh.rustup.rs --output /tmp/rustup-init.sh \
    && CARGO_HOME=/opt/cargo sh /tmp/rustup-init.sh -y --profile minimal \
       --default-toolchain "${RUST_VERSION}" --no-modify-path \
    && rm /tmp/rustup-init.sh

ENV PATH="/opt/cargo/bin:${PATH}"
ENV CC=clang-21 \
    CXX=clang++-21 \
    LIBCLANG_PATH=/usr/lib/llvm-21/lib \
    CMAKE_BUILD_PARALLEL_LEVEL=2 \
    CARGO_BUILD_JOBS=2 \
    CARGO_INCREMENTAL=0

WORKDIR /workspace
