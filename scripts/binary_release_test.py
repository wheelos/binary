import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import binary_release as release


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        environment = mock.patch.dict(os.environ, {"BINARY_PLATFORM": "", "BINARY_TARGET": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def test_architecture_aliases_only_produce_canonical_platforms(self):
        for alias, canonical in (
            ("amd64", "linux-x86_64"),
            ("x86_64", "linux-x86_64"),
            ("arm64", "linux-aarch64"),
            ("aarch64", "linux-aarch64"),
        ):
            with self.subTest(alias=alias):
                self.assertEqual(release.platform_name(alias, "Linux"), canonical)
                self.assertEqual(release.normalize_platform(f"linux-{alias}"), canonical)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            release.platform_name("x86", "Linux")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            release.platform_name("arm64", "Darwin")

    def test_planned_targets_are_not_built_or_published(self):
        metadata = release.metadata_for("livekit_sdk")
        metadata["targets"]["linux-aarch64"].update(enabled=False, reason="Missing native toolchain")
        with mock.patch("binary_release.metadata_for", return_value=metadata):
            matrix = release.build_matrix("livekit_sdk")["include"]
            self.assertNotIn("linux-aarch64", [entry["target"] for entry in matrix])
            with mock.patch.dict(os.environ, {"BINARY_TARGET": "linux-aarch64"}):
                with self.assertRaisesRegex(ValueError, "not enabled"):
                    release.native_target("livekit_sdk", "aarch64")

    def test_empty_enabled_matrix_fails_explicitly(self):
        metadata = release.metadata_for("livekit_sdk")
        for target in metadata["targets"].values():
            target.update(enabled=False, reason="Missing native toolchain")
        with mock.patch("binary_release.metadata_for", return_value=metadata):
            with self.assertRaisesRegex(ValueError, "no enabled"):
                release.build_matrix("livekit_sdk")

    def test_native_runner_cannot_be_mislabeled(self):
        with mock.patch.dict(os.environ, {"BINARY_PLATFORM": "linux-aarch64"}):
            with self.assertRaisesRegex(ValueError, "native host"):
                release.native_target("livekit_sdk", "x86_64")
        with mock.patch.dict(os.environ, {"BINARY_TARGET": "linux-aarch64"}):
            with self.assertRaisesRegex(ValueError, "cannot build"):
                release.native_target("livekit_sdk", "x86_64")

    def test_artifact_identity_agrees_with_target_and_object_key(self):
        for library in ("livekit_sdk", "spconv"):
            for entry in release.build_matrix(library)["include"]:
                filename = release.artifact_name(library, "1.2.3-wheelos.1", entry)
                prefix = release.object_prefix(library, "1.2.3-wheelos.1", entry)
                self.assertIn(entry["platform"], filename)
                self.assertIn(f"/{entry['platform']}", prefix)
                self.assertNotIn("linux-arm64", filename)
                if release.target_variant(entry):
                    self.assertIn(release.target_variant(entry), filename)
                    self.assertTrue(prefix.endswith("/" + release.target_variant(entry)))

    def test_elf_architecture_and_shared_object_type_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "libtest.so"
            for name, machine in (("linux-x86_64", 62), ("linux-aarch64", 183)):
                elf = bytearray(64)
                elf[:7] = b"\x7fELF\x02\x01\x01"
                struct.pack_into("<HH", elf, 16, 3, machine)
                path.write_bytes(elf)
                release.validate_elf(path, name)
                other = "linux-aarch64" if machine == 62 else "linux-x86_64"
                with self.assertRaisesRegex(ValueError, "architecture"):
                    release.validate_elf(path, other)
                struct.pack_into("<H", elf, 16, 2)
                path.write_bytes(elf)
                with self.assertRaisesRegex(ValueError, "shared-object"):
                    release.validate_elf(path, name)
            path.write_bytes(b"not ELF")
            with self.assertRaisesRegex(ValueError, "ELF64"):
                release.validate_elf(path, "linux-x86_64")

    def test_manual_tag_and_pr_versions_share_validation(self):
        cases = (
            ({"GITHUB_EVENT_NAME": "workflow_dispatch", "MANUAL_VERSION": "1.2.3-wheelos.1"}, "1.2.3-wheelos.1"),
            ({"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "spconv/v2.3.8-wheelos.1"}, "2.3.8-wheelos.1"),
            ({}, "2.3.8-wheelos.pr"),
        )
        for environment, expected in cases:
            with mock.patch.dict(os.environ, environment, clear=True):
                self.assertEqual(release.release_version("spconv"), expected)
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch", "MANUAL_VERSION": "../invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "invalid release version"):
                release.release_version("spconv")

    def test_check_elf_cli_accepts_paths_after_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "libtest.so"
            elf = bytearray(64)
            elf[:7] = b"\x7fELF\x02\x01\x01"
            struct.pack_into("<HH", elf, 16, 3, 62)
            path.write_bytes(elf)
            with mock.patch("sys.argv", ["binary_release.py", "check-elf", "--library", "livekit_sdk", str(path)]):
                with mock.patch("binary_release.platform.machine", return_value="x86_64"):
                    release.main()

    def test_publish_requires_complete_enabled_artifact_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = release.targets_for("livekit_sdk")["linux-x86_64"]
            archive = root / release.artifact_name("livekit_sdk", "1.2.3", target)
            archive.touch()
            archive.with_name(archive.name + ".sha256").touch()
            with mock.patch("sys.argv", [
                "binary_release.py", "publish", "--library", "livekit_sdk",
                "--version", "1.2.3", "--directory", str(root),
            ]):
                with mock.patch("binary_release.subprocess.run") as upload:
                    with self.assertRaisesRegex(FileNotFoundError, "linux-aarch64"):
                        release.main()
                    upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
