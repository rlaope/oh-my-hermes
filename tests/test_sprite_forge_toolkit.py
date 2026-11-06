"""Offline contracts plus separately opted-in Pillow-backed QA for the sprite-forge toolkit."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from _local_package import load_local_package
from _module_patch import patch_modules

load_local_package()
ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "src/skills/sprite_forge_toolkit"
SCRIPT = TOOLKIT / "scripts/forge.py"

HAS_PIL = importlib.util.find_spec("PIL") is not None


def helper_api():
    spec = importlib.util.spec_from_file_location("sprite_forge_helper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ForgeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "sheet.png"
        self.output = self.root / "out"

    def run_main(self, api, argv, block_pil=False):
        stderr = io.StringIO()
        blocked = {"PIL": None, "PIL.Image": None} if block_pil else {}
        with contextlib.redirect_stderr(stderr), patch_modules(blocked):
            code = api.main(list(argv))
        return code, stderr.getvalue()

    def refused(self, code, err, message):
        self.assertEqual(code, 2, err)
        self.assertIn(message, err)
        self.assertFalse(self.output.exists(), "a refused run created output")


class OfflineCliTests(ForgeFixture):
    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "--help"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("process", result.stdout)
        self.assertIn("selftest", result.stdout)
        result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "process", "--help"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--input", "--rows", "--cols", "--output", "--key",
                     "--tolerance", "--target-height"):
            self.assertIn(flag, result.stdout)

    def test_process_without_pillow_fails_closed(self):
        api = helper_api()
        self.input.write_bytes(b"\x89PNG\r\n\x1a\n-not-really-a-sheet")
        code, err = self.run_main(api, ["process", "--input", str(self.input),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)], block_pil=True)
        self.assertEqual(code, 2, err)
        self.assertIn("dependency missing", err)
        self.assertIn("Pillow", err)
        self.assertFalse(self.output.exists(), "a refused run created output")

    def test_existing_output_dir_refused_offline(self):
        api = helper_api()
        self.input.write_bytes(b"\x89PNG\r\n\x1a\n-not-really-a-sheet")
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        code, err = self.run_main(api, ["process", "--input", str(self.input),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)])
        self.assertEqual(code, 2, err)
        self.assertIn("must be new", err)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(list(self.output.iterdir()), [sentinel])


class ProvenanceManifestTests(unittest.TestCase):
    def test_manifest_digests_match_bytes(self):
        manifest = json.loads((TOOLKIT / "upstream-manifest.json").read_text())
        self.assertEqual(manifest["schema"], "omh_sprite_forge_provenance/v1")
        self.assertEqual(set(manifest["files"]),
                         {"LICENSE.upstream", "README.md", "examples/layout.json",
                          "scripts/forge.py"})
        for name, entry in manifest["files"].items():
            digest = hashlib.sha256((TOOLKIT / name).read_bytes()).hexdigest()
            self.assertEqual(entry["local_sha256"], digest, name)
            self.assertEqual(entry["source_sha256"], digest, name)
            self.assertEqual(entry["source_path"], f"src/skills/sprite_forge_toolkit/{name}")
            self.assertEqual(entry["classification"], "original_omh", name)
            self.assertEqual(entry["upstream"], [], name)
            self.assertEqual(entry["license"], "MIT", name)


@unittest.skipUnless(HAS_PIL, "optional Pillow backend")
class PillowCliTests(ForgeFixture):
    def magenta_sheet(self, name, *, rows, cols, heights=None, bleed_cell=None):
        from PIL import Image, ImageDraw
        sheet = Image.new("RGB", (cols * 256, rows * 256), (255, 0, 255))
        draw = ImageDraw.Draw(sheet)
        heights = heights or (170, 176, 164, 172, 168, 174)
        for index in range(rows * cols):
            row, col = divmod(index, cols)
            body_h = heights[index % len(heights)]
            x0 = col * 256 + 108
            bottom = row * 256 + 244
            if bleed_cell is not None and index == bleed_cell:
                x0 = col * 256
            draw.rectangle([x0, bottom - body_h, x0 + 40, bottom], fill=(230, 235, 240))
        path = self.root / name
        sheet.save(path, "PNG")
        return path

    def test_selftest_passes(self):
        out = self.root / "self"
        result = subprocess.run([sys.executable, str(SCRIPT), "selftest", "--output", str(out)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        qc = json.loads((out / "qc.json").read_text())
        self.assertEqual(qc["verdict"], "PASS")
        self.assertEqual(qc["frame_count"], 4)
        self.assertEqual(qc["rows"], 2)
        self.assertEqual(qc["cols"], 2)

    def lifted_sheet(self, name, lifts, key=(255, 0, 255), body=(230, 235, 240)):
        from PIL import Image, ImageDraw
        sheet = Image.new("RGB", (512, 512), key)
        draw = ImageDraw.Draw(sheet)
        for index, lift in enumerate(lifts):
            row, col = divmod(index, 2)
            x0 = col * 256 + 108
            bottom = row * 256 + 244 - lift
            draw.rectangle([x0, bottom - 170, x0 + 40, bottom], fill=body)
        path = self.root / name
        sheet.save(path, "PNG")
        return path

    def test_misaligned_feet_in_source_fail_the_gate(self):
        # One pose stands 40 px above the others in its cell: feet differ by
        # more than 5% of the 256 px cell. The gate used to read back the row
        # the code had just pinned, so this exited 0 with anchor_y_std == 0.
        api = helper_api()
        path = self.lifted_sheet("lifted.png", (0, 0, 40, 0))
        code, err = self.run_main(api, ["process", "--input", str(path), "--rows", "2",
                                        "--cols", "2", "--output", str(self.output)])
        self.assertEqual(code, 3, err)
        qc = json.loads((self.output / "qc.json").read_text())
        self.assertEqual(qc["verdict"], "REGENERATE")
        self.assertGreater(qc["anchor_y_std"], 0.05)

    def test_aligned_feet_keep_zero_anchor_error(self):
        api = helper_api()
        path = self.lifted_sheet("flat.png", (0, 0, 0, 0))
        code, err = self.run_main(api, ["process", "--input", str(path), "--rows", "2",
                                        "--cols", "2", "--output", str(self.output)])
        self.assertEqual(code, 0, err)
        qc = json.loads((self.output / "qc.json").read_text())
        self.assertEqual(qc["anchor_y_std"], 0.0)

    def test_cell_alignment_keeps_an_airborne_frame_off_the_ground(self):
        from PIL import Image
        api = helper_api()
        path = self.lifted_sheet("jump.png", (0, 0, 40, 0))
        code, err = self.run_main(api, ["process", "--input", str(path), "--rows", "2",
                                        "--cols", "2", "--align", "cell",
                                        "--output", str(self.output)])
        self.assertEqual(code, 0, err)
        qc = json.loads((self.output / "qc.json").read_text())
        self.assertFalse(qc["anchor_y_std_gated"])
        feet = []
        for i in (0, 2):
            box = Image.open(self.output / f"frame_{i:03d}.png").convert("RGBA").getchannel("A").getbbox()
            feet.append(box[3])
        self.assertEqual(feet[0] - feet[1], 40)

    def test_key_spill_is_reported(self):
        api = helper_api()
        # A body colour inside twice the tolerance of the key but outside it.
        path = self.lifted_sheet("spill.png", (0, 0, 0, 0), body=(255, 0, 255 - 45))
        code, err = self.run_main(api, ["process", "--input", str(path), "--rows", "2",
                                        "--cols", "2", "--output", str(self.output)])
        self.assertEqual(code, 0, err)
        qc = json.loads((self.output / "qc.json").read_text())
        self.assertGreater(qc["key_spill_pixels"], 0)

    def test_alpha_input_passthrough(self):
        api = helper_api()
        from PIL import Image, ImageDraw
        sheet = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        for index, body_h in enumerate((170, 176, 164, 172)):
            row, col = divmod(index, 2)
            x0 = col * 256 + 108
            bottom = row * 256 + 244
            draw.rectangle([x0, bottom - body_h, x0 + 40, bottom], fill=(240, 244, 248, 255))
        # An interior key-colored, fully opaque region must survive untouched:
        # the alpha channel, not the key color, decides the background.
        draw.rectangle([115, 60, 145, 90], fill=(255, 0, 255, 255))
        path = self.root / "alpha.png"
        sheet.save(path, "PNG")
        code, err = self.run_main(api, ["process", "--input", str(path),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)])
        self.assertEqual(code, 0, err)
        first = Image.open(self.output / "frame_000.png").convert("RGBA")
        magenta_kept = sum(1 for p in first.getdata() if p[:3] == (255, 0, 255))
        self.assertGreater(magenta_kept, 0,
                           "opaque key-colored pixel was dropped: key guessed on alpha input")
        self.assertGreater(sum(1 for p in first.getdata() if p[3] == 0), 0,
                           "transparent background was not preserved")

    def test_cell_bleed_rejected(self):
        api = helper_api()
        path = self.magenta_sheet("bleed.png", rows=2, cols=2, bleed_cell=0)
        code, err = self.run_main(api, ["process", "--input", str(path),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)])
        self.assertEqual(code, 2, err)
        self.assertIn("bleed", err)
        self.assertIn("cell 0", err)
        self.assertFalse(self.output.exists())

    def test_existing_output_refused(self):
        api = helper_api()
        path = self.magenta_sheet("grid.png", rows=2, cols=2)
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("keep")
        code, err = self.run_main(api, ["process", "--input", str(path),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)])
        self.assertEqual(code, 2, err)
        self.assertIn("must be new", err)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_oversize_refused(self):
        api = helper_api()
        path = self.magenta_sheet("small.png", rows=2, cols=2)
        with patch.object(api, "MAX_SIDE_PX", 32):
            code, err = self.run_main(api, ["process", "--input", str(path),
                                            "--rows", "2", "--cols", "2",
                                            "--output", str(self.output)])
        self.assertEqual(code, 2, err)
        self.assertIn("side length", err)
        self.assertFalse(self.output.exists())
        path2 = self.root / "tiny.png"
        path2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        with patch.object(api, "MAX_FILE_BYTES", 4):
            code, err = self.run_main(api, ["process", "--input", str(path2),
                                            "--rows", "2", "--cols", "2",
                                            "--output", str(self.output)])
        self.assertEqual(code, 2, err)
        self.assertIn("maximum size", err)
        self.assertFalse(self.output.exists())

    def test_strip_layout_refused(self):
        api = helper_api()
        path = self.magenta_sheet("strip.png", rows=1, cols=4)
        code, err = self.run_main(api, ["process", "--input", str(path),
                                        "--rows", "1", "--cols", "4",
                                        "--output", str(self.output)])
        self.refused(code, err, "grid")

    def test_regenerate_verdict_exit_3(self):
        api = helper_api()
        path = self.magenta_sheet("varied.png", rows=2, cols=2,
                                  heights=(120, 210, 90, 200))
        code, err = self.run_main(api, ["process", "--input", str(path),
                                        "--rows", "2", "--cols", "2",
                                        "--output", str(self.output)])
        self.assertEqual(code, 3, err)
        qc = json.loads((self.output / "qc.json").read_text())
        self.assertEqual(qc["verdict"], "REGENERATE")
        self.assertGreater(qc["body_scale_cv"], api.THRESHOLDS["body_scale_cv"])
        self.assertEqual(len(list(self.output.glob("frame_*.png"))), 4)
        self.assertTrue((self.output / "sheet.png").exists())


if __name__ == "__main__":
    unittest.main()
