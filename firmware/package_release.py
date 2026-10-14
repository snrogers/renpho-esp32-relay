"""Package an ESP-IDF build for download and for the web installer.

Usage: python firmware/package_release.py BUILD_DIR OUT_DIR VERSION

Writes OUT_DIR/firmware/ (the images, flasher_args.json, flash_args, and a
manifest.json for the web installer) and OUT_DIR/renpho-relay-firmware-VERSION.zip.
Offsets come from flasher_args.json; nothing is guessed. The parts are never
merged into one image, because a merged image would overwrite the config and
outbox partitions that sit between the partition table and the app.
"""

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

VERSION = re.compile(r"[A-Za-z0-9._-]{1,64}")


def package(build: Path, out: Path, version: str) -> Path:
  if not VERSION.fullmatch(version):
    raise ValueError("version must be 1-64 of [A-Za-z0-9._-]")
  flasher = json.loads((build / "flasher_args.json").read_text(encoding="utf-8"))
  files = flasher.get("flash_files")
  settings = flasher.get("flash_settings")
  chip = (flasher.get("extra_esptool_args") or {}).get("chip")
  if not isinstance(files, dict) or not files or not isinstance(settings, dict) or not chip:
    raise ValueError("flasher_args.json lacks flash_files, flash_settings, or chip")

  target = out / "firmware"
  if target.exists():
    shutil.rmtree(target)
  target.mkdir(parents=True)
  parts = []
  for offset, relative in sorted(files.items(), key=lambda item: int(item[0], 0)):
    source = (build / relative).resolve()
    if not source.is_relative_to(build.resolve()) or not source.is_file():
      raise ValueError(f"missing or outside image for {offset}: {relative}")
    (target / relative).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target / relative)
    parts.append({"address": int(offset, 0), "path": relative, "size": source.stat().st_size})
  shutil.copyfile(build / "flasher_args.json", target / "flasher_args.json")
  if (build / "flash_args").is_file():
    shutil.copyfile(build / "flash_args", target / "flash_args")

  manifest = {
    "chip": chip,
    "flashFreq": settings["flash_freq"],
    "flashMode": settings["flash_mode"],
    "flashSize": settings["flash_size"],
    "parts": parts,
    "version": version,
  }
  (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

  archive = out / f"renpho-relay-firmware-{version}.zip"
  with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(target.rglob("*")):
      if path.is_file():
        bundle.write(path, Path(f"renpho-relay-firmware-{version}") / path.relative_to(target))
  return archive


if __name__ == "__main__":
  if len(sys.argv) != 4:
    sys.exit(__doc__.strip().splitlines()[2])
  print(package(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
