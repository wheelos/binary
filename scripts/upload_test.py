import functools
import hashlib
import http.server
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).with_name("upload.sh")
PREFIX = "release/public/livekit_sdk/1.13.0-wheelos.1/linux-x86_64"
NAME = "livekit-sdk-1.13.0-wheelos.1-linux-x86_64.tar.gz"
FAKE_AWS = """#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
def value(flag):
    return args[args.index(flag) + 1]

root = Path(os.environ["TEST_REMOTE"])
key = value("--key")
target = root / key
with Path(os.environ["TEST_CALLS"]).open("a") as log:
    log.write(" ".join(args) + "\\n")
if "head-object" in args:
    if os.environ.get("TEST_FORBIDDEN"):
        print("An error occurred (403): Forbidden", file=sys.stderr)
        sys.exit(1)
    if target.exists():
        sys.exit(0)
    print("An error occurred (404): Not Found", file=sys.stderr)
    sys.exit(1)
assert "put-object" in args
assert value("--if-none-match") == "*"
assert value("--bucket") == "test-bucket"
assert value("--endpoint-url") == "https://test-account.r2.cloudflarestorage.com"
if os.environ.get("TEST_RACE"):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"concurrent release")
if target.exists():
    print("An error occurred (412): PreconditionFailed", file=sys.stderr)
    sys.exit(1)
target.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(value("--body"), target)
if os.environ.get("TEST_CORRUPT") and key.endswith(".tar.gz"):
    target.write_bytes(b"corrupted")
if os.environ.get("TEST_CORRUPT_SIDECAR") and key.endswith(".sha256"):
    target.write_bytes(b"corrupted sidecar")
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = self.root / NAME
        self.archive.write_bytes(b"release archive")
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.sidecar = self.root / (NAME + ".sha256")
        self.sidecar.write_text(f"{self.digest}  {NAME}\n")
        remote = self.root / "remote"
        remote.mkdir()
        tools = self.root / "bin"
        tools.mkdir()
        aws = tools / "aws"
        aws.write_text(FAKE_AWS)
        aws.chmod(0o755)
        self.calls = self.root / "calls"
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(remote))
        )
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.env = {
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "R2_ACCESS_KEY_ID": "test-key",
            "R2_SECRET_ACCESS_KEY": "test-secret",
            "R2_ACCOUNT_ID": "test-account",
            "R2_BUCKET_NAME": "test-bucket",
            "PUBLIC_DOWNLOAD_BASE_URL": f"http://127.0.0.1:{self.server.server_port}",
            "TEST_REMOTE": str(remote),
            "TEST_CALLS": str(self.calls),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
        }

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def run_upload(self, prefix=PREFIX):
        return subprocess.run(
            ["bash", str(SCRIPT), str(self.archive), prefix],
            env=self.env, capture_output=True, text=True, timeout=15,
        )

    def test_upload_and_verify_public_archive_and_sidecar(self):
        result = self.run_upload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"/{PREFIX}/{NAME}", result.stdout)
        self.assertIn(self.digest, result.stdout)
        self.assertEqual(self.calls.read_text().count("put-object"), 2)
        self.assertIn(self.digest, (self.root / "summary").read_text())

    def test_existing_object_is_never_overwritten(self):
        existing = Path(self.env["TEST_REMOTE"]) / PREFIX / NAME
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"existing release")
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to overwrite", result.stderr)
        self.assertEqual(existing.read_bytes(), b"existing release")
        self.assertNotIn("put-object", self.calls.read_text())

    def test_permission_error_is_not_treated_as_missing(self):
        self.env["TEST_FORBIDDEN"] = "1"
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("403", result.stderr)
        self.assertNotIn("put-object", self.calls.read_text())

    def test_conditional_write_prevents_concurrent_overwrite(self):
        self.env["TEST_RACE"] = "1"
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("412", result.stderr)
        target = Path(self.env["TEST_REMOTE"]) / PREFIX / NAME
        self.assertEqual(target.read_bytes(), b"concurrent release")
        self.assertNotIn("Download:", result.stdout)

    def test_invalid_archive_or_sidecar_fails_before_upload(self):
        self.archive.write_bytes(b"modified")
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())
        self.sidecar.write_text(f"{self.digest}  ../other.tar.gz\n")
        result = self.run_upload()
        self.assertIn("Invalid SHA256 sidecar", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_public_download_corruption_is_reported(self):
        self.env["TEST_CORRUPT"] = "1"
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout)
        self.assertNotIn("Download:", result.stdout)

    def test_private_or_traversing_prefix_is_rejected(self):
        for prefix in ("release/private/livekit", "release/public/../livekit"):
            result = self.run_upload(prefix)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid public release prefix", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_public_sidecar_corruption_is_reported(self):
        self.env["TEST_CORRUPT_SIDECAR"] = "1"
        result = self.run_upload()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Download:", result.stdout)


if __name__ == "__main__":
    unittest.main()
