#!/bin/sh
set -eu

# Under WSL, Windows owns USB Serial/JTAG, so run the tool with Windows uv.
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
uv=${UV_EXE:-$(command -v uv.exe || true)}
if [ -z "$uv" ]; then
  echo "${0##*/}: uv.exe not found; install uv on Windows or set UV_EXE" >&2
  exit 2
fi

to_windows() {
  case $1 in
    /*) wslpath -w -- "$1" ;;
    *)  printf '%s\n' "$1" ;;
  esac
}

n=$#
expect=
i=0
while [ "$i" -lt "$n" ]; do
  arg=$1
  shift
  i=$((i + 1))
  if [ -n "$expect" ]; then
    set -- "$@" "$(to_windows "$arg")"
    expect=
    continue
  fi
  case $arg in
    --config|--build)
      set -- "$@" "$arg"
      expect=1
      ;;
    --config=*|--build=*)
      key=${arg%%=*}
      set -- "$@" "${key}=$(to_windows "${arg#*=}")"
      ;;
    *)
      set -- "$@" "$arg"
      ;;
  esac
done

if [ -n "$expect" ]; then
  echo "flash.sh: missing value for --config/--build" >&2
  exit 2
fi

exec "$uv" run --no-project --python 3.12 \
  --script "$(wslpath -w "$root/firmware/flash.py")" "$@"
