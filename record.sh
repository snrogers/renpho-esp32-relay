#!/bin/sh
set -eu

# Under WSL, Windows owns the Bluetooth adapter, so record with Windows uv.
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
uv=${UV_EXE:-$(command -v uv.exe || true)}
if [ -z "$uv" ]; then
  echo "${0##*/}: uv.exe not found; install uv on Windows or set UV_EXE" >&2
  exit 2
fi
exec "$uv" run --no-project --python 3.12 \
  --script "$(wslpath -w "$root/morphoscan.py")" record "$@"
