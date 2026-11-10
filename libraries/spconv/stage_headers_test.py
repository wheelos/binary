import tempfile
import unittest
from pathlib import Path

from stage_headers import relative_header, stage_files


class StageHeadersTest(unittest.TestCase):
    def test_selects_generated_and_cumm_headers(self):
        self.assertEqual(
            relative_header(
                "bazel-out/k8-opt/bin/external/spconv+/generated/include/"
                "spconvlib/ops.h"
            ),
            Path("spconvlib/ops.h"),
        )
        self.assertEqual(
            relative_header(
                "external/spconv+cumm_codegen/cumm/include/tensorview/tensor.h"
            ),
            Path("tensorview/tensor.h"),
        )
        self.assertIsNone(relative_header("external/cuda/include/cuda_runtime.h"))

    def test_stages_selected_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "external/spconv+/generated/include/spconvlib/ops.h"
            source.parent.mkdir(parents=True)
            source.write_text("#pragma once\n")
            output = root / "dist/include"

            self.assertEqual(stage_files([str(source)], output), 1)
            self.assertEqual(
                (output / "spconvlib/ops.h").read_text(),
                "#pragma once\n",
            )

    def test_resolves_external_files_from_output_base(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "external/spconv+cumm_codegen/cumm/include/tensorview/tensor.h"
            source.parent.mkdir(parents=True)
            source.write_text("#pragma once\n")
            output = root / "dist/include"

            self.assertEqual(
                stage_files(
                    ["external/spconv+cumm_codegen/cumm/include/tensorview/tensor.h"],
                    output,
                    root / "execroot",
                    root / "external",
                ),
                1,
            )
            self.assertTrue((output / "tensorview/tensor.h").is_file())

    def test_rejects_conflicting_files_with_same_include_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "external/spconv+/generated/include/spconvlib/ops.h"
            second = root / "external/other-generated/include/spconvlib/ops.h"
            for path, contents in ((first, "one"), (second, "two")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)

            with self.assertRaisesRegex(ValueError, "conflicting header"):
                stage_files([str(first), str(second)], root / "dist/include")


if __name__ == "__main__":
    unittest.main()
