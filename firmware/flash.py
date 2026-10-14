# /// script
# requires-python = ">=3.12"
# dependencies = ["esptool==5.4.0", "pyserial==3.5"]
# ///
"""Flash, provision, and inspect the ESP32-S3 RENPHO relay.

Reads ESP-IDF flasher_args.json (never guessed offsets). Sends configure
JSON over native USB serial from a private config file so Wi-Fi credentials
never appear in argv or logs.

Flashing preserves the durable outbox. On first boot, the firmware migrates
records from earlier outbox formats without changing their identities or
delivery states; never erase NVS to upgrade it. Each reading uploads the full
information/measurement packet pair to the receiver.

Grounded in:
- esptool 5.4.0 CLI/API: python -m esptool write-flash "@flash_args"
  https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/flashing-firmware.html
- esptool.main([...]) scripting:
  https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/scripting.html
- pyserial 3.5 serial.Serial / serial.tools.list_ports
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent

CONFIG_FIELDS = (
    "deviceId",
    "receiverUrl",
    "scaleAddress",
    "wifiPassword",
    "wifiSsid",
)
DEVICE_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
FIELD_MAX_BYTES = {
    "deviceId": 128,
    "receiverUrl": 256,
    "scaleAddress": 17,
    "wifiPassword": 64,
    "wifiSsid": 32,
}
ESPRESSIF_VID = 0x303A
LINE_LIMIT = 4096
MAC_PATTERN = re.compile(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
OPTIONAL_FIELDS = {"scaleAddress": ""}
SECRET_KEYS = frozenset({"wifiPassword"})
SERIAL_BAUD = 115200


class ToolError(Exception):
  pass


def fail(message: str, code: int = 2) -> None:
  print(message, file=sys.stderr)
  raise SystemExit(code)


def resolve_path(value: str | Path) -> Path:
  path = Path(value)
  if not path.is_absolute():
    path = REPO / path
  return path.resolve()


def redact(value: str, secrets: list[str]) -> str:
  redacted = value
  for secret in secrets:
    if secret and secret in redacted:
      redacted = redacted.replace(secret, "<redacted>")
  return redacted


def load_json_object(path: Path) -> dict[str, Any]:
  try:
    text = path.read_text(encoding="utf-8")
  except OSError as error:
    raise ToolError(f"cannot read {path}: {error.strerror or error}") from error
  try:
    payload = json.loads(text)
  except json.JSONDecodeError as error:
    raise ToolError(f"{path}: invalid JSON ({error.msg} at line {error.lineno})") from error
  if not isinstance(payload, dict):
    raise ToolError(f"{path}: expected a JSON object")
  return payload


def validate_receiver_url(url: str) -> None:
  parsed = urlparse(url)
  if parsed.scheme not in ("http", "https"):
    raise ToolError("receiverUrl must be an http(s) URL")
  if not parsed.netloc:
    raise ToolError("receiverUrl is missing a host")
  if parsed.username is not None or parsed.password is not None:
    raise ToolError("receiverUrl must not contain credentials")
  if parsed.fragment or "#" in url:
    raise ToolError("receiverUrl must not contain a fragment")


def validate_config(payload: dict[str, Any]) -> dict[str, str]:
  extra = sorted(set(payload) - set(CONFIG_FIELDS) - {"command"})
  if extra:
    raise ToolError(f"config has unexpected fields: {', '.join(extra)}")
  payload = {**OPTIONAL_FIELDS, **payload}
  missing = [name for name in CONFIG_FIELDS if name not in payload]
  if missing:
    raise ToolError(f"config is missing required fields: {', '.join(missing)}")
  values: dict[str, str] = {}
  for name in CONFIG_FIELDS:
    value = payload[name]
    if not isinstance(value, str):
      raise ToolError(f"{name} must be a string")
    encoded = value.encode("utf-8")
    if b"\x00" in encoded:
      raise ToolError(f"{name} must not contain NUL")
    limit = FIELD_MAX_BYTES[name]
    if len(encoded) > limit:
      raise ToolError(f"{name} exceeds {limit} UTF-8 bytes")
    if name not in ("scaleAddress", "wifiPassword") and value == "":
      raise ToolError(f"{name} must be a non-empty string")
    values[name] = value
  if not DEVICE_ID_PATTERN.fullmatch(values["deviceId"]):
    raise ToolError("deviceId must be 1..128 characters matching [A-Za-z0-9._:-]+")
  if values["scaleAddress"] and not MAC_PATTERN.fullmatch(values["scaleAddress"]):
    raise ToolError("scaleAddress must be empty or a BLE MAC (AA:BB:CC:DD:EE:FF)")
  validate_receiver_url(values["receiverUrl"])
  return values


def load_config(path: Path) -> dict[str, str]:
  return validate_config(load_json_object(path))


def config_public(values: dict[str, str]) -> dict[str, Any]:
  public = {name: values[name] for name in CONFIG_FIELDS if name not in SECRET_KEYS}
  public["wifiPasswordSet"] = bool(values.get("wifiPassword"))
  return public


def load_flasher_args(build: Path) -> dict[str, Any]:
  path = build / "flasher_args.json"
  if not path.is_file():
    raise ToolError(
        f"missing {path}; build the firmware with ESP-IDF first (default build dir firmware/build)"
    )
  payload = load_json_object(path)
  files = payload.get("flash_files")
  if not isinstance(files, dict) or not files:
    raise ToolError(f"{path}: missing flash_files; refusing to guess offsets")
  missing: list[str] = []
  resolved: dict[str, Path] = {}
  for offset, relative in sorted(files.items(), key=lambda item: int(str(item[0]), 0)):
    if not isinstance(relative, str):
      raise ToolError(f"{path}: flash_files[{offset}] is not a path")
    binary = (build / relative).resolve()
    if not binary.is_file():
      missing.append(f"{offset} -> {binary}")
    resolved[offset] = binary
  if missing:
    raise ToolError("missing flash images:\n  " + "\n  ".join(missing))
  payload["_resolved"] = resolved
  payload["_path"] = path
  return payload


def flash_command(build: Path, port: str, flasher: dict[str, Any]) -> list[str]:
  extra = flasher.get("extra_esptool_args") or {}
  chip = extra.get("chip", "esp32s3")
  before = str(extra.get("before", "default-reset")).replace("_", "-")
  after = str(extra.get("after", "hard-reset")).replace("_", "-")
  command = [
      "--chip",
      str(chip),
      "--port",
      port,
      "--baud",
      "460800",
      "--before",
      before,
      "--after",
      after,
      "write-flash",
  ]
  flash_args = build / "flash_args"
  if flash_args.is_file():
    command.append("@flash_args")
    return command
  write_args = flasher.get("write_flash_args")
  if isinstance(write_args, list):
    for item in write_args:
      text = str(item)
      if text.startswith("--"):
        text = text.replace("_", "-")
      command.append(text)
  resolved: dict[str, Path] = flasher["_resolved"]
  for offset, binary in resolved.items():
    command.extend([offset, str(binary)])
  return command


def run_esptool(command: list[str], cwd: Path) -> None:
  import esptool

  print("esptool", " ".join(command))
  previous = Path.cwd()
  try:
    os.chdir(cwd)
    esptool.main(command)
  except SystemExit as error:
    if error.code not in (0, None):
      raise ToolError(f"esptool failed with exit {error.code}") from error
  finally:
    os.chdir(previous)


def list_serial_ports():
  from serial.tools import list_ports

  return list(list_ports.comports())


def is_espressif(info) -> bool:
  vid = getattr(info, "vid", None)
  if vid == ESPRESSIF_VID:
    return True
  blob = " ".join(
      str(part)
      for part in (info.description, info.manufacturer, info.hwid)
      if part
  ).lower()
  return "espressif" in blob or "usb jtag" in blob or "usb serial/jtag" in blob


def format_port(info) -> str:
  vid = f"{info.vid:04X}" if info.vid is not None else "----"
  pid = f"{info.pid:04X}" if info.pid is not None else "----"
  mark = "espressif" if is_espressif(info) else "other"
  description = info.description or ""
  return f"{info.device}\t{vid}:{pid}\t{mark}\t{description}"


def espressif_ports():
  return [info for info in list_serial_ports() if is_espressif(info)]


def require_port(explicit: str | None) -> str:
  if explicit:
    return explicit
  found = espressif_ports()
  if not found:
    raise ToolError(
        "no Espressif USB serial device found; pass --port (native Windows COM port from WSL)"
    )
  if len(found) > 1:
    listing = "\n".join(format_port(info) for info in found)
    raise ToolError(f"ambiguous Espressif serial devices; pass --port:\n{listing}")
  return found[0].device


def wait_for_port(port: str, present: bool, timeout: float) -> None:
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    devices = {info.device for info in list_serial_ports()}
    if present == (port in devices):
      return
    time.sleep(0.15)
  state = "reappear" if present else "disappear"
  raise ToolError(f"timed out waiting for {port} to {state}")


def open_serial(port: str, timeout: float):
  import serial

  try:
    return serial.Serial(port=port, baudrate=SERIAL_BAUD, timeout=0.2)
  except serial.SerialException as error:
    raise ToolError(f"cannot open {port}: {error}") from error


def reopen_after_reset(port: str, timeout: float):
  try:
    wait_for_port(port, present=False, timeout=min(8.0, timeout))
  except ToolError:
    pass
  wait_for_port(port, present=True, timeout=timeout)
  time.sleep(0.4)
  deadline = time.monotonic() + timeout
  last_error = "port did not reopen"
  while time.monotonic() < deadline:
    try:
      return open_serial(port, timeout)
    except ToolError as error:
      last_error = str(error)
      time.sleep(0.2)
  raise ToolError(last_error)


def read_json_event(
    handle,
    wanted: set[str],
    timeout: float,
    secrets: list[str],
) -> dict[str, Any]:
  deadline = time.monotonic() + timeout
  buffer = bytearray()
  while time.monotonic() < deadline:
    chunk = handle.read(256)
    if not chunk:
      continue
    buffer.extend(chunk)
    while True:
      newline = buffer.find(b"\n")
      if newline < 0:
        if len(buffer) > LINE_LIMIT:
          buffer.clear()
        break
      raw = bytes(buffer[:newline])
      del buffer[: newline + 1]
      if len(raw) > LINE_LIMIT:
        continue
      try:
        text = raw.decode("utf-8").strip()
      except UnicodeDecodeError:
        continue
      if not text.startswith("{"):
        continue
      try:
        payload = json.loads(text)
      except json.JSONDecodeError:
        continue
      if not isinstance(payload, dict):
        continue
      event = payload.get("event")
      if event in wanted:
        return payload
      if event == "configuration_error":
        detail = redact(str(payload.get("error") or "configuration_error"), secrets)
        raise ToolError(detail)
  raise ToolError(f"timed out waiting for {sorted(wanted)} on USB serial")


def send_command(handle, payload: dict[str, Any]) -> None:
  line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
  handle.write(line.encode("utf-8"))
  handle.flush()


def configure_device(port: str, values: dict[str, str], timeout: float) -> dict[str, Any]:
  secrets = [values["wifiPassword"]]
  handle = None
  try:
    handle = open_serial(port, timeout)
    request = {"command": "configure", **values}
    send_command(handle, request)
    reply = read_json_event(handle, {"configured"}, timeout, secrets)
  except ToolError:
    raise
  except Exception as error:
    raise ToolError(redact(str(error), secrets)) from error
  finally:
    if handle is not None:
      handle.close()
  return reply


def status_device(port: str, timeout: float) -> dict[str, Any]:
  handle = None
  try:
    handle = open_serial(port, timeout)
    send_command(handle, {"command": "status"})
    return read_json_event(handle, {"status"}, timeout, [])
  finally:
    if handle is not None:
      handle.close()


def cmd_ports(_args: argparse.Namespace) -> int:
  ports = list_serial_ports()
  if not ports:
    print("no serial ports found", file=sys.stderr)
    return 1
  for info in ports:
    print(format_port(info))
  return 0


def cmd_inspect(args: argparse.Namespace) -> int:
  build = resolve_path(args.build)
  flasher = load_flasher_args(build)
  extra = flasher.get("extra_esptool_args") or {}
  print(f"build\t{build}")
  print(f"flasher_args\t{flasher['_path']}")
  print(f"chip\t{extra.get('chip', 'unknown')}")
  for offset, binary in flasher["_resolved"].items():
    print(f"image\t{offset}\t{binary}\t{binary.stat().st_size}")
  if args.config:
    values = load_config(resolve_path(args.config))
    public = config_public(values)
    print("config\tvalid")
    for name in sorted(public):
      print(f"config.{name}\t{public[name]}")
  else:
    print("config\tnot provided")
  return 0


def cmd_flash(args: argparse.Namespace) -> int:
  build = resolve_path(args.build)
  values = load_config(resolve_path(args.config))
  flasher = load_flasher_args(build)
  port = require_port(args.port)
  command = flash_command(build, port, flasher)
  run_esptool(command, build)
  handle = reopen_after_reset(port, args.timeout)
  handle.close()
  reply = configure_device(port, values, args.timeout)
  print(json.dumps({"event": reply.get("event", "configured")}, sort_keys=True))
  return 0


def cmd_configure(args: argparse.Namespace) -> int:
  values = load_config(resolve_path(args.config))
  port = require_port(args.port)
  reply = configure_device(port, values, args.timeout)
  print(json.dumps({"event": reply.get("event", "configured")}, sort_keys=True))
  return 0


def cmd_status(args: argparse.Namespace) -> int:
  port = require_port(args.port)
  reply = status_device(port, args.timeout)
  sanitized = {
      key: value
      for key, value in reply.items()
      if key not in SECRET_KEYS and "password" not in key.lower() and "ssid" != key
  }
  print(json.dumps(sanitized, sort_keys=True))
  return 0


FLASH_BYTES = 0x1000000
SETUP_PROMPTS = (
    ("wifiSsid", "Wi-Fi network name (2.4 GHz)", ""),
    ("receiverUrl", "Webhook URL, such as http://192.168.1.20:8080/api/scale-readings", ""),
    ("deviceId", "Relay name", "relay-1"),
    ("scaleAddress", "Scale address (Enter: pair with the first R-MSC01)", ""),
)


def yes(ask: Callable[[str], str], question: str, default: bool) -> bool:
  answer = ask(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
  return default if not answer else answer.startswith("y")


def choose_port(explicit: str | None, ask: Callable[[str], str]) -> str:
  if explicit:
    return explicit
  found = espressif_ports()
  if not found:
    raise ToolError("no Espressif USB serial device found; connect the board with a USB data cable")
  if len(found) == 1:
    print(f"Using {found[0].device}.")
    return found[0].device
  for number, info in enumerate(found, 1):
    print(f"{number}. {format_port(info)}")
  while True:
    answer = ask("Board port number: ").strip()
    if answer.isdigit() and 1 <= int(answer) <= len(found):
      return found[int(answer) - 1].device


def ask_config(ask: Callable[[str], str], secret: Callable[[str], str]) -> dict[str, str]:
  values = {name: default for name, _, default in SETUP_PROMPTS}
  password = None
  while True:
    for name, label, _ in SETUP_PROMPTS:
      if name == "scaleAddress":
        values[name] = ask(f"{label}: ").strip()  # Enter always means pair automatically.
        continue
      answer = ask(f"{label}" + (f" [{values[name]}]" if values[name] else "") + ": ").strip()
      values[name] = answer or values[name]
    keep = " (Enter: keep)" if password is not None else ""
    entered = secret(f"Wi-Fi password{keep}: ")
    password = entered if entered or password is None else password
    try:
      return validate_config({**values, "wifiPassword": password})
    except ToolError as error:
      print(f"Check the settings: {error}")


def save_private_json(path: Path, values: dict[str, str]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(values, handle, indent=2, sort_keys=True)
    handle.write("\n")


def wait_for_status(port: str, done: Callable[[dict[str, Any]], bool], seconds: float) -> dict[str, Any]:
  deadline = time.monotonic() + seconds
  reply: dict[str, Any] = {}
  while True:
    try:
      reply = status_device(port, 15.0)
      if done(reply):
        return reply
    except ToolError:
      pass
    if time.monotonic() >= deadline:
      return reply
    time.sleep(5.0)


def cmd_setup(
    args: argparse.Namespace,
    ask: Callable[[str], str] = input,
    secret: Callable[[str], str] = getpass.getpass,
) -> int:
  build = resolve_path(args.build)
  flasher = load_flasher_args(build)
  print("This installs the relay firmware and configures it. Disconnect the phone app from the scale.")
  port = choose_port(args.port, ask)
  values = ask_config(ask, secret)

  if yes(ask, "Back up the board flash first? Recommended before the first installation", True):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default = Path.home() / f"relay-backup-{stamp}.bin"
    path = Path(ask(f"Backup file [{default}]: ").strip() or default).expanduser().resolve()
    if path.exists():
      raise ToolError(f"{path} already exists; choose a new file name")
    run_esptool(["--chip", "esp32s3", "--port", port, "read-flash", "0", hex(FLASH_BYTES), str(path)], build)
    if path.stat().st_size != FLASH_BYTES:
      raise ToolError(f"backup {path} is incomplete; installation stopped")
    path.chmod(0o600)
    print(f"Backup saved: {path}. Keep it private; it can contain your Wi-Fi password.")

  if yes(ask, "Save these settings in a private file for later updates?", False):
    default = Path.home() / "relay-config.json"
    path = Path(ask(f"Settings file [{default}]: ").strip() or default).expanduser().resolve()
    save_private_json(path, values)
    print(f"Settings saved: {path}. Use --config {path} with flash or configure.")

  run_esptool(flash_command(build, port, flasher), build)
  reopen_after_reset(port, args.timeout).close()
  configure_device(port, values, args.timeout)
  print("Configured. Waiting for Wi-Fi...")
  reply = wait_for_status(port, lambda r: bool(r.get("wifiConnected")), 60.0)
  if not reply.get("wifiConnected"):
    print("The relay is not on Wi-Fi yet. Check the network name and password, then run status.")
    return 1
  print("Wi-Fi connected.")
  if reply.get("scaleAddress"):
    print(f"Paired with scale {reply['scaleAddress']}. Setup is complete.")
    return 0
  print("Step onto the scale now to pair it with the relay.")
  reply = wait_for_status(port, lambda r: bool(r.get("scaleAddress")), args.pair_seconds)
  if reply.get("scaleAddress"):
    print(f"Paired with scale {reply['scaleAddress']}. Setup is complete.")
    return 0
  print("No scale yet. The relay keeps looking; step onto the scale, then run status to check.")
  return 0


def add_common(parser: argparse.ArgumentParser, *, config: bool, port: bool) -> None:
  parser.add_argument(
      "--build",
      default="firmware/build",
      help="ESP-IDF build directory containing flasher_args.json (default: firmware/build, from repo root)",
  )
  parser.add_argument(
      "--timeout",
      type=float,
      default=30.0,
      help="seconds to wait for USB serial events after reset (default: 30)",
  )
  if config:
    parser.add_argument(
        "--config",
        required=True,
        help="private JSON with deviceId, receiverUrl, scaleAddress, wifiSsid, wifiPassword",
    )
  if port:
    parser.add_argument(
        "--port",
        help="serial device; required unless exactly one Espressif USB Serial/JTAG port exists",
    )


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
      prog="flash.py",
      formatter_class=argparse.RawDescriptionHelpFormatter,
      description="Flash and provision the Waveshare ESP32-S3-LCD-1.47 RENPHO relay.",
      epilog="""\
Private config JSON (never pass Wi-Fi secrets on the command line):
  {
    "deviceId": "relay-1",
    "receiverUrl": "http://192.0.2.10:8080/api/scale-readings",
    "wifiSsid": "<ssid>",
    "wifiPassword": "<from file only>"
  }

Build with ESP-IDF v5.5.2:
  idf.py -C firmware -DIDF_TARGET=esp32s3 build

From this WSL checkout:
  ./flash.sh inspect --config /path/to/relay-config.json
  ./flash.sh flash --config /path/to/relay-config.json
  ./flash.sh status

Use a 2.4 GHz Wi-Fi network. Keep the RENPHO phone app disconnected so the
relay can connect to the scale.
The relay persists up to 16 pending readings before acknowledging the scale.
It retains them through network failures; only a matching receiver success
marks a reading delivered. A full outbox refuses new readings rather than
overwriting unsent ones. The relay keeps no clock; the receiver timestamps
each reading when it arrives.

receiverUrl is the full URL that the relay POSTs each reading to.
scaleAddress is optional. Without it, the relay pairs with the first R-MSC01
that sends a valid scale packet and keeps that address; status shows it.
configure writes NVS and preserves the measurement outbox.
status is read-only. inspect needs no board.

From WSL, use ./flash.sh so native Windows Python owns the USB device.
""",
  )
  sub = parser.add_subparsers(dest="command", required=True)

  ports = sub.add_parser("ports", help="list serial ports and mark Espressif USB devices")
  ports.set_defaults(func=cmd_ports)

  inspect = sub.add_parser("inspect", help="validate build metadata and optional config without hardware")
  add_common(inspect, config=False, port=False)
  inspect.add_argument("--config", help="optional private config JSON to validate")
  inspect.set_defaults(func=cmd_inspect)

  flash = sub.add_parser("flash", help="esptool write-flash from flasher_args.json, then USB configure")
  add_common(flash, config=True, port=True)
  flash.set_defaults(func=cmd_flash)

  configure = sub.add_parser("configure", help="USB configure only; does not erase measurements")
  add_common(configure, config=True, port=True)
  configure.set_defaults(func=cmd_configure)

  setup = sub.add_parser("setup", help="guided install: backup, settings, firmware, Wi-Fi, scale pairing")
  add_common(setup, config=False, port=True)
  setup.add_argument(
      "--pair-seconds", type=float, default=180.0, help="seconds to wait for scale pairing (default: 180)"
  )
  setup.set_defaults(func=cmd_setup)

  status = sub.add_parser("status", help="read-only USB status JSON")
  add_common(status, config=False, port=True)
  status.set_defaults(func=cmd_status)
  return parser


def main(argv: list[str] | None = None) -> int:
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    return args.func(args)
  except ToolError as error:
    fail(str(error))
    return 2


if __name__ == "__main__":
  sys.exit(main())
