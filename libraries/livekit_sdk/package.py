#!/usr/bin/env python3
"""Create a reproducible LiveKit SDK archive for one native Linux platform."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import sys
import tarfile


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "scripts"))
from binary_release import artifact_name, native_target, platform_name, validate_elf, validate_version

METADATA = json.loads((ROOT / "metadata.json").read_text())


def target_platform(machine: str | None = None) -> str:
    return platform_name(machine or platform.machine())


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_bundle(bundle: Path, version: str, platform_name: str | None = None) -> list[Path]:
    validate_version(version)
    required = (
        "include/livekit/livekit.h",
        "include/livekit/build.h",
        "lib/liblivekit.so",
        "lib/liblivekit_ffi.so",
        "lib/cmake/LiveKit/LiveKitConfig.cmake",
        "share/livekit/build-info.json",
        "share/livekit/LICENSE",
    )
    missing = [item for item in required if not (bundle / item).is_file()]
    if missing:
        raise ValueError("SDK bundle is missing: " + ", ".join(missing))

    expected_platform = platform_name or native_target("livekit_sdk")["platform"]
    for library in ("liblivekit.so", "liblivekit_ffi.so"):
        validate_elf(bundle / "lib" / library, expected_platform)

    build_info = json.loads((bundle / "share/livekit/build-info.json").read_text())
    if build_info.get("sdk_version") != version:
        raise ValueError(
            f"SDK bundle version mismatch: expected {version}, "
            f"got {build_info.get('sdk_version')!r}"
        )
    rust_commit = build_info.get("rust_submodule_commit")
    if (
        not isinstance(rust_commit, str)
        or not re.fullmatch(r"[0-9a-f]{7,40}", rust_commit)
        or not METADATA["rust_submodule_commit"].startswith(rust_commit)
    ):
        raise ValueError("SDK bundle was built from an unexpected Rust submodule commit")

    paths = sorted(bundle.rglob("*"), key=lambda item: item.relative_to(bundle).as_posix())
    bundle_root = bundle.resolve()
    for path in paths:
        if path.is_symlink():
            target = os.readlink(path)
            resolved = (path.parent / target).resolve()
            if os.path.isabs(target) or (resolved != bundle_root and bundle_root not in resolved.parents):
                raise ValueError(f"SDK bundle contains an unsafe symlink: {path}")
    return [path for path in paths if not path.is_dir() and path.name != "manifest.json"]


def manifest_for(bundle: Path, files: list[Path], version: str, platform_name: str) -> bytes:
    file_entries = []
    for path in files:
        relative = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            file_entries.append({"path": relative, "symlink": os.readlink(path)})
        else:
            file_entries.append(
                {"path": relative, "sha256": file_sha256(path), "size": path.stat().st_size}
            )
    manifest = {
        "schema_version": 1,
        "name": METADATA["name"],
        "version": version,
        "upstream_tag": METADATA["upstream_tag"],
        "upstream_commit": METADATA["upstream_commit"],
        "rust_submodule_commit": METADATA["rust_submodule_commit"],
        "target": platform_name,
        "build": {
            "compiler": os.environ.get("CXX", ""),
            "rustc": os.environ.get("LIVEKIT_RUSTC_VERSION", ""),
            "cargo": os.environ.get("LIVEKIT_CARGO_VERSION", ""),
            "cmake": os.environ.get("LIVEKIT_CMAKE_VERSION", ""),
        },
        "files": file_entries,
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()


def add_bytes(archive: tarfile.TarFile, name: str, content: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def create_archive(bundle: Path, version: str, output: Path, machine: str | None = None) -> str:
    target = native_target("livekit_sdk", machine)
    platform_name = target["platform"]
    expected_name = artifact_name("livekit_sdk", version, target)
    if output.name != expected_name:
        raise ValueError(f"expected output filename {expected_name}")
    files = validate_bundle(bundle, version, platform_name)
    root_name = f"livekit-sdk-{version}-{platform_name}"
    manifest = manifest_for(bundle, files, version, platform_name)

    output.parent.mkdir(parents=True, exist_ok=True)
    checksum_path = output.with_name(output.name + ".sha256")
    if output.exists() or checksum_path.exists():
        raise FileExistsError(f"refusing to overwrite {output} or its checksum")

    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in files:
                    relative = path.relative_to(bundle).as_posix()
                    info = archive.gettarinfo(str(path), arcname=f"{root_name}/{relative}")
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if info.isfile():
                        info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                    else:
                        archive.addfile(info)
                add_bytes(archive, f"{root_name}/manifest.json", manifest)

    digest = file_sha256(output)
    checksum_path.write_text(f"{digest}  {output.name}\n")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/sdk")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = create_archive(args.bundle, args.version, args.output)
    print(f"{args.output}  sha256={digest}")


if __name__ == "__main__":
    main()
