#!/usr/bin/env python3
"""Create a reproducible spconv release archive and SHA256 sidecar."""

import argparse
import gzip
import hashlib
import json
import os
import platform
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "scripts"))
from binary_release import artifact_name, native_target, object_prefix, validate_elf, validate_version

METADATA = json.loads((ROOT / "metadata.json").read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(
    binary: Path,
    include_dir: Path,
    version: str,
    output: Path,
    licenses: list[Path],
) -> Path:
    validate_version(version)
    target = native_target("spconv", platform.machine())
    expected_name = artifact_name("spconv", version, target)
    if output.name != expected_name:
        raise ValueError(f"expected output filename {expected_name}")
    if not binary.is_file():
        raise FileNotFoundError(f"shared library not found: {binary}")
    validate_elf(binary, target["platform"])
    if not include_dir.is_dir():
        raise FileNotFoundError(f"header directory not found: {include_dir}")
    headers = sorted(include_dir.rglob("*"))
    headers = [path for path in headers if path.suffix in {".h", ".hpp", ".cuh"}]
    if not headers:
        raise ValueError(f"no spconv headers found in {include_dir}")
    if any(path.is_symlink() or not path.is_file() for path in headers):
        raise ValueError("header directory must contain regular files only")
    license_files = {path.name: path for path in licenses}
    expected_licenses = {"SPCONV-LICENSE", "CUMM-LICENSE"}
    if license_files.keys() != expected_licenses:
        raise ValueError(
            "expected Bazel license outputs named SPCONV-LICENSE and CUMM-LICENSE"
        )
    for path in license_files.values():
        if not path.is_file():
            raise FileNotFoundError(f"license file not found: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    checksum_path = output.with_name(output.name + ".sha256")
    if output.exists() or checksum_path.exists():
        raise FileExistsError(f"refusing to overwrite release output: {output}")

    manifest = {
        "schema_version": 1,
        "name": "spconv",
        "version": version,
        "source": {
            "upstream_version": METADATA["upstream_version"],
            "commit": METADATA["upstream_commit"],
        },
        "target": {
            "os": "linux",
            "architecture": target["platform"].removeprefix("linux-"),
            "cuda_version": target["cuda_version"],
            "cuda_arch": target["cuda_arch"],
        },
        "build": {
            "bazel_version": "8.8.1",
            "image": os.environ.get("BINARY_BUILD_IMAGE", ""),
            "image_id": os.environ.get("BINARY_BUILD_IMAGE_ID", ""),
            "binary_revision": os.environ.get("BINARY_SOURCE_REVISION", ""),
        },
        "artifact": {
            "path": "lib/libspconv.so",
            "object_key": f"{object_prefix('spconv', version, target)}/{output.name}",
            "sha256": sha256(binary),
        },
        "headers": {
            "count": len(headers),
            "sha256": hashlib.sha256(
                b"".join(
                    path.relative_to(include_dir).as_posix().encode()
                    + b"\0"
                    + sha256(path).encode()
                    + b"\n"
                    for path in headers
                )
            ).hexdigest(),
        },
        "licenses": {
            name: sha256(path) for name, path in sorted(license_files.items())
        },
    }

    manifest_path = output.with_name(output.name.removesuffix(".tar.gz") + ".manifest.json")
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite release manifest: {manifest_path}")
    manifest_created = False
    output_created = False
    checksum_created = False
    try:
        with manifest_path.open("x") as manifest_file:
            manifest_created = True
            manifest_file.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        with output.open("xb") as destination:
            output_created = True
            with gzip.GzipFile(
                filename="",
                fileobj=destination,
                mode="wb",
                mtime=0,
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for source, name in [
                        (binary, "lib/libspconv.so"),
                        (manifest_path, "manifest.json"),
                        *[
                            (path, f"licenses/{name}")
                            for name, path in sorted(license_files.items())
                        ],
                        *[
                            (path, f"include/{path.relative_to(include_dir).as_posix()}")
                            for path in headers
                        ],
                    ]:
                        info = archive.gettarinfo(str(source), arcname=name)
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ""
                        info.mode = 0o755 if name.endswith(".so") else 0o644
                        info.pax_headers = {}
                        with source.open("rb") as contents:
                            archive.addfile(info, contents)
        archive_digest = sha256(output)
        with checksum_path.open("x") as checksum_file:
            checksum_created = True
            checksum_file.write(f"{archive_digest}  {output.name}\n")
    except Exception:
        if output_created:
            output.unlink(missing_ok=True)
        if checksum_created:
            checksum_path.unlink(missing_ok=True)
        if manifest_created:
            manifest_path.unlink(missing_ok=True)
        raise
    return checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--include-dir", type=Path, required=True)
    parser.add_argument("--license", type=Path, action="append", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checksum = package(
        args.binary,
        args.include_dir,
        args.version,
        args.output,
        args.license,
    )
    print(f"artifact={args.output}")
    print(f"sha256={checksum.read_text().split()[0]}")


if __name__ == "__main__":
    main()
