#!/usr/bin/env python3
"""Stage generated spconv and cumm headers from the configured Bazel graph."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from binary_release import native_target


HEADER_SUFFIXES = {".h", ".hpp", ".cuh"}


def relative_header(path: str) -> Path | None:
    source = Path(path)
    parts = source.parts
    include_indexes = [index for index, part in enumerate(parts) if part == "include"]
    if not include_indexes:
        return None
    include_index = include_indexes[-1]
    prefix = parts[:include_index]
    if not any("generated" in part or "cumm_codegen" in part for part in prefix):
        return None
    relative = Path(*parts[include_index + 1 :])
    if relative.suffix not in HEADER_SUFFIXES:
        return None
    return relative


def stage_files(
    paths: list[str],
    output: Path,
    execution_root: Path | None = None,
    external_root: Path | None = None,
) -> int:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite staged headers: {output}")
    selected: dict[Path, Path] = {}
    for path in paths:
        relative = relative_header(path)
        if relative is None:
            continue
        source = Path(path)
        if not source.is_absolute():
            if source.parts[0] == "external" and external_root is not None:
                source = external_root.joinpath(*source.parts[1:])
            elif execution_root is not None:
                source = execution_root / source
        if not source.is_file():
            raise FileNotFoundError(f"Bazel header is missing: {source}")
        if relative in selected:
            if selected[relative].read_bytes() != source.read_bytes():
                raise ValueError(f"conflicting header paths map to {relative}")
            continue
        selected[relative] = source
    if not selected:
        raise ValueError("Bazel graph did not provide any spconv or cumm headers")

    output.mkdir(parents=True, exist_ok=True)
    for relative, source in selected.items():
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return len(selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = native_target("spconv")
    result = subprocess.run(
        [
            "bazel",
            "cquery",
            "--output=files",
            "--compilation_mode=opt",
            "--cxxopt=-std=c++17",
            "deps(@spconv//:headers)",
            "--@rules_cuda//cuda:enable=true",
            f"--@rules_cuda//cuda:archs=sm_{target['cuda_arch'].removeprefix('sm')}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    execution_root = Path(
        subprocess.run(
            ["bazel", "info", "execution_root"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    output_base = Path(
        subprocess.run(
            ["bazel", "info", "output_base"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    count = stage_files(
        result.stdout.splitlines(),
        args.output,
        execution_root,
        output_base / "external",
    )
    print(f"staged_headers={count}")


if __name__ == "__main__":
    main()
