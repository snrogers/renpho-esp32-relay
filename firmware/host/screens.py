#!/usr/bin/env python3
"""Render the relay LCD screens to PNG files for the documentation.

The images come from the firmware renderer in firmware/core/render.c.
Each LCD pixel becomes a 2 x 2 block, for sharp images on high-density displays.
"""
import argparse
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HOST = Path(__file__).resolve().parent
ROOT = HOST.parent.parent
OUTPUT = ROOT / "docs" / "screens"
SCALE = 2
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_ppm(path):
  data = path.read_bytes()
  magic, width, height, maximum, pixels = data.split(maxsplit=4)
  if magic != b"P6" or maximum != b"255":
    raise ValueError(f"{path} is not an 8-bit P6 file")
  width, height = int(width), int(height)
  if len(pixels) != width * height * 3:
    raise ValueError(f"{path} has the wrong size")
  return width, height, pixels


def scale_rows(width, height, pixels):
  rows = []
  for y in range(height):
    row = pixels[y * width * 3:(y + 1) * width * 3]
    wide = b"".join(row[x:x + 3] * SCALE for x in range(0, len(row), 3))
    rows.extend([wide] * SCALE)
  return width * SCALE, height * SCALE, rows


def chunk(kind, body):
  return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def encode_png(width, height, rows):
  header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
  raw = b"".join(b"\x00" + row for row in rows)
  return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def decode_png(data):
  """Decode the 8-bit RGB, unfiltered PNG files that encode_png writes."""
  if not data.startswith(PNG_SIGNATURE):
    raise ValueError("not a PNG file")
  offset, header, compressed = len(PNG_SIGNATURE), None, b""
  while offset < len(data):
    (length,) = struct.unpack(">I", data[offset:offset + 4])
    kind, body = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
    offset += 12 + length
    if kind == b"IHDR":
      header = struct.unpack(">IIBBBBB", body)
    elif kind == b"IDAT":
      compressed += body
  if header is None or header[2:] != (8, 2, 0, 0, 0):
    raise ValueError("unsupported PNG format")
  width, height = header[:2]
  raw = zlib.decompress(compressed)
  stride = width * 3 + 1
  rows = [raw[y * stride:(y + 1) * stride] for y in range(height)]
  if len(raw) != stride * height or any(row[0] != 0 for row in rows):
    raise ValueError("unsupported PNG rows")
  return width, height, [row[1:] for row in rows]


def render():
  """Return {screen name: (width, height, rows)} from the firmware renderer."""
  subprocess.run(["make", "-s", "-C", str(HOST), "screens"], check=True)
  with tempfile.TemporaryDirectory() as tmp:
    names = subprocess.run(
        [str(HOST / "screens"), tmp], check=True, capture_output=True, text=True
    ).stdout.split()
    return {name: scale_rows(*read_ppm(Path(tmp) / f"{name}.ppm")) for name in names}


def stale(screens, output=OUTPUT):
  """Return the names of PNG files that are missing, extra, or show other pixels."""
  problems = []
  for name, image in screens.items():
    path = output / f"{name}.png"
    try:
      if decode_png(path.read_bytes()) != image:
        problems.append(path.name)
    except (OSError, ValueError, zlib.error):
      problems.append(path.name)
  known = {f"{name}.png" for name in screens}
  problems.extend(sorted(p.name for p in output.glob("*.png") if p.name not in known))
  return problems


def main():
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--check", action="store_true", help="fail if the PNG files differ from the renderer")
  args = parser.parse_args()
  screens = render()
  if args.check:
    problems = stale(screens)
    if problems:
      print("Stale screen images: " + ", ".join(problems), file=sys.stderr)
      print("Run firmware/host/screens.py to update them.", file=sys.stderr)
      return 1
    print(f"{len(screens)} screen images are current.")
    return 0
  OUTPUT.mkdir(parents=True, exist_ok=True)
  for name, image in screens.items():
    (OUTPUT / f"{name}.png").write_bytes(encode_png(*image))
    print(OUTPUT.relative_to(ROOT) / f"{name}.png")
  return 0


if __name__ == "__main__":
  sys.exit(main())
