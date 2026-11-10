#!/usr/bin/env python3
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import package


class PackageTest(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {"BINARY_PLATFORM": "", "BINARY_TARGET": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.host = mock.patch("package.platform.machine", return_value="x86_64")
        self.host.start()
        self.addCleanup(self.host.stop)

    def create_bundle(self, root: Path, version: str = "1.13.0-wheelos.1", machine: int = 62) -> Path:
        bundle = root / "sdk"
        elf = bytearray(64)
        elf[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HH", elf, 16, 3, machine)
        files = {
            "include/livekit/livekit.h": b"header\n",
            "include/livekit/build.h": f'#define LIVEKIT_BUILD_VERSION "{version}"\n'.encode(),
            "lib/liblivekit.so": elf,
            "lib/liblivekit_ffi.so": elf,
            "lib/cmake/LiveKit/LiveKitConfig.cmake": b"set(LiveKit_FOUND TRUE)\n",
            "share/livekit/LICENSE": b"Apache License\n",
            "share/livekit/build-info.json": json.dumps(
                {
                    "sdk_version": version,
                    "rust_submodule_commit": package.METADATA["rust_submodule_commit"],
                }
            ).encode(),
        }
        for relative, content in files.items():
            path = bundle / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return bundle

    def test_platform_mapping(self):
        self.assertEqual(package.target_platform("x86_64"), "linux-x86_64")
        self.assertEqual(package.target_platform("aarch64"), "linux-aarch64")
        with self.assertRaises(ValueError):
            package.target_platform("armv7l")

    def test_reproducible_archive_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.create_bundle(root)
            filename = "livekit-sdk-1.13.0-wheelos.1-linux-x86_64.tar.gz"
            first = root / "first" / filename
            second = root / "second" / filename
            package.create_archive(bundle, "1.13.0-wheelos.1", first, "x86_64")
            package.create_archive(bundle, "1.13.0-wheelos.1", second, "x86_64")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            expected = package.file_sha256(first)
            self.assertEqual(
                first.with_name(first.name + ".sha256").read_text(),
                f"{expected}  {first.name}\n",
            )

    def test_arm64_archive_has_canonical_name_and_matching_elf(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.create_bundle(root, machine=183)
            output = root / "livekit-sdk-1.13.0-wheelos.1-linux-aarch64.tar.gz"
            package.create_archive(bundle, "1.13.0-wheelos.1", output, "arm64")
            self.assertTrue(output.is_file())

    def test_rejects_mislabeled_archive_or_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.create_bundle(root)
            output = root / "livekit-sdk-1.13.0-wheelos.1-linux-aarch64.tar.gz"
            with self.assertRaisesRegex(ValueError, "expected output filename"):
                package.create_archive(bundle, "1.13.0-wheelos.1", output, "x86_64")
            with self.assertRaisesRegex(ValueError, "ELF.*architecture"):
                package.create_archive(bundle, "1.13.0-wheelos.1", output, "aarch64")
            self.assertFalse(output.exists())

    def test_rejects_version_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self.create_bundle(root)
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                package.validate_bundle(bundle, "1.13.0-wheelos.2")

    def test_rejects_unsafe_version(self):
        with self.assertRaisesRegex(ValueError, "invalid release version"):
            package.validate_bundle(Path("/does/not/matter"), "../outside")

    def test_upstream_abbreviated_rust_commit_matches_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.create_bundle(Path(tmp))
            info_path = bundle / "share/livekit/build-info.json"
            info = json.loads(info_path.read_text())
            info["rust_submodule_commit"] = package.METADATA["rust_submodule_commit"][:8]
            info_path.write_text(json.dumps(info))
            package.validate_bundle(bundle, "1.13.0-wheelos.1")

    def test_rejects_wrong_or_invalid_rust_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self.create_bundle(Path(tmp))
            info_path = bundle / "share/livekit/build-info.json"
            info = json.loads(info_path.read_text())
            for commit in ("00000000", "ede", None):
                with self.subTest(commit=commit):
                    info["rust_submodule_commit"] = commit
                    info_path.write_text(json.dumps(info))
                    with self.assertRaisesRegex(ValueError, "unexpected Rust submodule"):
                        package.validate_bundle(bundle, "1.13.0-wheelos.1")


if __name__ == "__main__":
    unittest.main()
