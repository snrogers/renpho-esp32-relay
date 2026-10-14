import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
  "package_release", Path(__file__).resolve().parent / "firmware" / "package_release.py"
)
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)

FLASHER_ARGS = {
  "extra_esptool_args": {"after": "hard_reset", "before": "default_reset", "chip": "esp32s3", "stub": True},
  "flash_files": {
    "0x0": "bootloader/bootloader.bin",
    "0x20000": "renpho_relay.bin",
    "0x8000": "partition_table/partition-table.bin",
  },
  "flash_settings": {"flash_freq": "80m", "flash_mode": "dio", "flash_size": "16MB"},
}


class PackageReleaseTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.build = Path(self.directory.name) / "build"
    self.out = Path(self.directory.name) / "out"
    for relative, size in (
      ("bootloader/bootloader.bin", 3),
      ("partition_table/partition-table.bin", 2),
      ("renpho_relay.bin", 5),
    ):
      (self.build / relative).parent.mkdir(parents=True, exist_ok=True)
      (self.build / relative).write_bytes(b"x" * size)
    (self.build / "flasher_args.json").write_text(json.dumps(FLASHER_ARGS))
    (self.build / "flash_args").write_text("0x0 bootloader/bootloader.bin\n")

  def tearDown(self):
    self.directory.cleanup()

  def test_manifest_keeps_build_offsets_and_separate_parts(self):
    archive = package_release.package(self.build, self.out, "v1.2.3")
    manifest = json.loads((self.out / "firmware" / "manifest.json").read_text())
    self.assertEqual(
      manifest["parts"],
      [
        {"address": 0x0, "path": "bootloader/bootloader.bin", "size": 3},
        {"address": 0x8000, "path": "partition_table/partition-table.bin", "size": 2},
        {"address": 0x20000, "path": "renpho_relay.bin", "size": 5},
      ],
    )
    self.assertEqual(
      (manifest["chip"], manifest["flashMode"], manifest["flashFreq"], manifest["flashSize"], manifest["version"]),
      ("esp32s3", "dio", "80m", "16MB", "v1.2.3"),
    )
    with zipfile.ZipFile(archive) as bundle:
      names = set(bundle.namelist())
    prefix = "renpho-relay-firmware-v1.2.3/"
    for name in ("flasher_args.json", "flash_args", "manifest.json", "renpho_relay.bin",
                 "bootloader/bootloader.bin", "partition_table/partition-table.bin"):
      self.assertIn(prefix + name, names)

  def test_refuses_missing_image_and_unsafe_version(self):
    (self.build / "renpho_relay.bin").unlink()
    with self.assertRaisesRegex(ValueError, "missing or outside image for 0x20000"):
      package_release.package(self.build, self.out, "v1")
    with self.assertRaisesRegex(ValueError, "version must be"):
      package_release.package(self.build, self.out, "../v1")

  def test_refuses_image_path_outside_the_build(self):
    args = json.loads((self.build / "flasher_args.json").read_text())
    args["flash_files"]["0x20000"] = "../outside.bin"
    (self.build.parent / "outside.bin").write_bytes(b"x")
    (self.build / "flasher_args.json").write_text(json.dumps(args))
    with self.assertRaisesRegex(ValueError, "outside image"):
      package_release.package(self.build, self.out, "v1")


if __name__ == "__main__":
  unittest.main()
