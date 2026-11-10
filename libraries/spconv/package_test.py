import hashlib
import json
import os
import struct
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

from package import package


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        environment = patch.dict(os.environ, {"BINARY_PLATFORM": "", "BINARY_TARGET": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.binary = self.root / "libspconv.so"
        elf = bytearray(64)
        elf[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HH", elf, 16, 3, 62)
        self.binary.write_bytes(elf)
        self.licenses = []
        for name in ("SPCONV-LICENSE", "CUMM-LICENSE"):
            path = self.root / name
            path.write_text(f"{name} notice\n")
            self.licenses.append(path)
        self.include_dir = self.root / "include"
        header = self.include_dir / "spconvlib" / "spconv.h"
        header.parent.mkdir(parents=True)
        header.write_text("#pragma once\n")

    @patch("package.platform.machine", return_value="x86_64")
    @patch("package.platform.system", return_value="Linux")
    def test_creates_deterministic_archive_and_manifest(self, _system, _machine):
        filename = "spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz"
        first = self.root / "first" / filename
        second = self.root / "second" / filename

        package(
            self.binary,
            self.include_dir,
            "2.3.8-wheelos.1",
            first,
            self.licenses,
        )
        first_manifest = json.loads(
            first.with_name(first.name.removesuffix(".tar.gz") + ".manifest.json").read_text()
        )
        package(
            self.binary,
            self.include_dir,
            "2.3.8-wheelos.1",
            second,
            self.licenses,
        )

        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(
            first_manifest["artifact"]["sha256"],
            hashlib.sha256(self.binary.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            first_manifest["artifact"]["object_key"],
            "release/public/spconv/2.3.8-wheelos.1/linux-x86_64/"
            "cuda12.8-sm89/spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz",
        )
        self.assertEqual(first_manifest["target"]["cuda_arch"], "sm89")
        self.assertEqual(first_manifest["headers"]["count"], 1)
        self.assertEqual(
            set(first_manifest["licenses"]),
            {"SPCONV-LICENSE", "CUMM-LICENSE"},
        )
        self.assertEqual(
            first.with_name(first.name + ".sha256").read_text().split()[0],
            hashlib.sha256(first.read_bytes()).hexdigest(),
        )
        with tarfile.open(first, "r:gz") as archive:
            self.assertEqual(
                set(archive.getnames()),
                {
                    "lib/libspconv.so",
                    "manifest.json",
                    "licenses/SPCONV-LICENSE",
                    "licenses/CUMM-LICENSE",
                    "include/spconvlib/spconv.h",
                },
            )

    @patch("package.platform.machine", return_value="aarch64")
    @patch("package.platform.system", return_value="Linux")
    def test_rejects_unimplemented_architecture(self, _system, _machine):
        with self.assertRaisesRegex(ValueError, "enabled target for linux-aarch64"):
            package(
                self.binary,
                self.include_dir,
                "2.3.8-wheelos.1",
                self.root
                / "unsupported"
                / "spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz",
                self.licenses,
            )

    @patch("package.platform.machine", return_value="x86_64")
    @patch("package.platform.system", return_value="Linux")
    def test_refuses_to_overwrite_an_existing_release(self, _system, _machine):
        output = self.root / (
            "spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz"
        )
        output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            package(
                self.binary,
                self.include_dir,
                "2.3.8-wheelos.1",
                output,
                self.licenses,
            )
        self.assertEqual(output.read_bytes(), b"preserve")

    @patch("package.platform.machine", return_value="x86_64")
    def test_rejects_mislabeled_elf_before_packaging(self, _machine):
        elf = bytearray(self.binary.read_bytes())
        struct.pack_into("<H", elf, 18, 183)
        self.binary.write_bytes(elf)
        output = self.root / "spconv-2.3.8-wheelos.1-linux-x86_64-cuda12.8-sm89.tar.gz"
        with self.assertRaisesRegex(ValueError, "ELF.*architecture"):
            package(self.binary, self.include_dir, "2.3.8-wheelos.1", output, self.licenses)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
