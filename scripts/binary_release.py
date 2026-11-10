#!/usr/bin/env python3
"""Shared native-platform, artifact and release-matrix contract."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = json.loads((ROOT / "platforms.json").read_text())
LIBRARIES = tuple(sorted(path.parent.name for path in (ROOT / "libraries").glob("*/metadata.json")))
ALIASES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
ELF_MACHINES = {"linux-x86_64": 62, "linux-aarch64": 183}


def platform_name(machine: str | None = None, system: str | None = None) -> str:
    machine = machine or platform.machine()
    system = system or platform.system()
    if system != "Linux" or machine not in ALIASES:
        raise ValueError(f"unsupported native build host: {system} {machine}")
    return f"linux-{ALIASES[machine]}"


def normalize_platform(name: str) -> str:
    if not name.startswith("linux-"):
        raise ValueError(f"unsupported platform: {name}")
    return platform_name(name.removeprefix("linux-"), "Linux")


def validate_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid release version: {version!r}")


def metadata_for(library: str) -> dict:
    if library not in LIBRARIES:
        raise ValueError(f"unknown library: {library}")
    return json.loads((ROOT / "libraries" / library / "metadata.json").read_text())


def target_variant(target: dict) -> str:
    cuda = target.get("cuda_version")
    arch = target.get("cuda_arch")
    if cuda is None and arch is None:
        return ""
    if not isinstance(cuda, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", cuda):
        raise ValueError(f"invalid CUDA version: {cuda!r}")
    if not isinstance(arch, str) or not re.fullmatch(r"sm[0-9]{2,3}", arch):
        raise ValueError(f"invalid CUDA architecture: {arch!r}")
    return f"cuda{cuda}-{arch}"


def targets_for(library: str, enabled_only: bool = True) -> dict[str, dict]:
    targets = metadata_for(library)["targets"]
    result = {}
    for name, target in targets.items():
        canonical = normalize_platform(target["platform"])
        if canonical != target["platform"] or canonical not in PLATFORMS:
            raise ValueError(f"target {name} must use a canonical platform")
        variant = target_variant(target)
        expected = canonical + (f"-{variant}" if variant else "")
        if name != expected:
            raise ValueError(f"expected target ID {expected}, got {name}")
        if not isinstance(target["enabled"], bool):
            raise ValueError(f"target {name} needs an explicit enabled boolean")
        if not target["enabled"] and not target.get("reason"):
            raise ValueError(f"disabled target {name} needs a reason")
        if not enabled_only or target["enabled"]:
            result[name] = target
    return result


def native_target(library: str, machine: str | None = None) -> dict:
    native = platform_name(machine)
    expected = os.environ.get("BINARY_PLATFORM")
    if expected and normalize_platform(expected) != native:
        raise ValueError(f"native host is {native}, not requested platform {expected}")
    targets = targets_for(library)
    selected = os.environ.get("BINARY_TARGET")
    if selected:
        if selected not in targets:
            raise ValueError(f"target is not enabled for {library}: {selected}")
        target = targets[selected]
        if target["platform"] != native:
            raise ValueError(f"target {selected} cannot build on native host {native}")
        return target
    matches = [target for target in targets.values() if target["platform"] == native]
    if len(matches) != 1:
        raise ValueError(f"{library} needs one enabled target for {native}; select BINARY_TARGET")
    return matches[0]


def validate_elf(path: Path, expected_platform: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
    if len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError(f"not a little-endian ELF64 shared object: {path}")
    elf_type, machine = struct.unpack_from("<HH", header, 16)
    if elf_type != 3 or machine != ELF_MACHINES[expected_platform]:
        raise ValueError(f"ELF shared-object architecture does not match {expected_platform}: {path}")


def artifact_name(library: str, version: str, target: dict) -> str:
    validate_version(version)
    variant = target_variant(target)
    suffix = f"-{variant}" if variant else ""
    return f"{metadata_for(library)['archive_name']}-{version}-{target['platform']}{suffix}.tar.gz"


def object_prefix(library: str, version: str, target: dict) -> str:
    validate_version(version)
    variant = target_variant(target)
    suffix = f"/{variant}" if variant else ""
    return f"release/public/{library}/{version}/{target['platform']}{suffix}"


def build_matrix(library: str) -> dict:
    entries = []
    for name, target in targets_for(library).items():
        entry = {
            **target,
            "target": name,
            "runner": PLATFORMS[target["platform"]]["runner"],
        }
        entries.append(entry)
    if not entries:
        raise ValueError(f"no enabled build targets for {library}")
    return {"include": entries}


def release_version(library: str) -> str:
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        version = os.environ.get("MANUAL_VERSION", "")
    elif os.environ.get("GITHUB_REF_TYPE") == "tag":
        ref = os.environ["GITHUB_REF_NAME"]
        prefix = f"{library}/v"
        if not ref.startswith(prefix):
            raise ValueError(f"expected release tag {prefix}<version>")
        version = ref.removeprefix(prefix)
    else:
        metadata = metadata_for(library)
        version = metadata.get("upstream_version") or metadata["upstream_tag"].removeprefix("v")
        version += "-wheelos.pr"
    validate_version(version)
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "native", "version", "check-elf", "publish"))
    parser.add_argument("--library", choices=LIBRARIES, required=True)
    parser.add_argument("--version")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("binaries", type=Path, nargs="*")
    args = parser.parse_intermixed_args()
    if args.command == "matrix":
        print(json.dumps(build_matrix(args.library), separators=(",", ":")))
    elif args.command == "version":
        print(release_version(args.library))
    elif args.command == "native":
        print(native_target(args.library)["platform"])
    elif args.command == "check-elf":
        target = native_target(args.library)
        if not args.binaries:
            parser.error("check-elf needs at least one shared library")
        for path in args.binaries:
            validate_elf(path, target["platform"])
    else:
        if not args.version or not args.directory:
            parser.error("publish needs --version and --directory")
        artifacts = [
            (
                args.directory / artifact_name(args.library, args.version, target),
                object_prefix(args.library, args.version, target),
            )
            for target in build_matrix(args.library)["include"]
        ]
        for archive, _prefix in artifacts:
            for path in (archive, archive.with_name(archive.name + ".sha256")):
                if not path.is_file():
                    raise FileNotFoundError(f"release matrix artifact is missing: {path}")
        for archive, prefix in artifacts:
            subprocess.run(
                [
                    "bash", str(ROOT / "scripts/upload.sh"),
                    str(archive), prefix,
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
