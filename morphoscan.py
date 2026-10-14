# /// script
# requires-python = ">=3.12"
# dependencies = ["bleak==3.0.2"]
# ///
"""R-MSC01 Bluetooth recording on Windows; offline interpretation on Linux or Windows."""

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from morphoscan_protocol import FrameAssembler, PacketDecoder, acknowledge

ROOT = Path(__file__).resolve().parent
WRITE_UUID = "0000ffb1-0000-1000-8000-00805f9b34fb"
RECEIVE_UUIDS = (
  "0000ffb3-0000-1000-8000-00805f9b34fb",
  "0000ffb2-0000-1000-8000-00805f9b34fb",
)


class Journal:
  def __init__(self, path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    self.file = os.fdopen(descriptor, "w", encoding="utf-8")

  def record(self, event: str, **data):
    record = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **data}
    self.file.write(json.dumps(record, allow_nan=False, sort_keys=True) + "\n")
    self.file.flush()

  def sync(self):
    self.file.flush()
    os.fsync(self.file.fileno())

  def close(self):
    self.file.close()


def decoded_capture(path: Path):
  assemblers = {uuid: FrameAssembler() for uuid in RECEIVE_UUIDS}
  decoder = PacketDecoder()
  with path.open(encoding="utf-8") as source:
    for number, line in enumerate(source, 1):
      row = json.loads(line)
      if "hex" not in row or row.get("characteristic", "").lower() not in RECEIVE_UUIDS:
        continue
      characteristic = row["characteristic"].lower()
      assembler = assemblers[characteristic]
      try:
        packet = assembler.add(bytes.fromhex(row["hex"]))
        if packet is None:
          continue
        for source_number, _, decoded in decoder.decode(packet, number):
          yield {"line": source_number, **decoded}
      except ValueError as error:
        raise ValueError(f"{path}:{number}: {error}") from error


def replay(path: Path):
  for decoded in decoded_capture(path):
    print(json.dumps(decoded, sort_keys=True))


def interpret(path: Path, profile=None, output: Path | None = None):
  from morphoscan_body import BodyComposition, impedance_channels

  calculator = BodyComposition() if profile is not None else None
  journal = Journal(output) if output is not None else None
  seen = set()
  try:
    for decoded in decoded_capture(path):
      if decoded["type"] not in ("measurement", "history"):
        continue
      # Retransmissions are one physical result, not additional weigh-ins.
      identity = json.dumps(
        {
          key: value
          for key, value in decoded.items()
          if key not in ("line", "sequence")
        },
        sort_keys=True,
      )
      if identity in seen:
        continue
      seen.add(identity)
      report = {
        "algorithm": "MorphoScan 1.9.8 / WLA37",
        "device_time": decoded.get("device_time"),
        "impedance_ohms_by_frequency_khz": impedance_channels(decoded),
        "source_capture": str(path),
        "source_line": decoded["line"],
        "weight_kg": decoded["weight_kg"],
      }
      if calculator is None:
        report["estimation_status"] = "profile_required"
        report["required_profile_fields"] = ["age", "height_cm", "sex"]
      else:
        report["body_composition_estimates"] = calculator.calculate(decoded, profile)
        report["profile"] = asdict(profile)
        report["estimation_status"] = "calculated_locally"
        report["notes"] = [
          "Vendor BIA estimates, not diagnostic measurements.",
          "Vendor targets and thresholds are model outputs, not clinical recommendations.",
          "Muscle, water and protein quantities overlap; do not add them together.",
          "Segment percentages are relative to vendor reference values, not tissue percentages.",
        ]
      if journal is not None:
        journal.record("interpretation", **report)
        journal.sync()
      print(json.dumps(report, allow_nan=False, indent=2, sort_keys=True))
    if not seen:
      raise ValueError("Capture contains no complete final measurements")
  finally:
    if journal is not None:
      journal.close()


async def record(args):
  from bleak import BleakClient, BleakScanner

  settings = json.loads(args.device.read_text(encoding="utf-8"))
  address = settings["address"]
  print(
    f"Scanning for {settings['advertised_name']} ({address}); tap the scale to wake it.",
    flush=True,
  )
  device = await BleakScanner.find_device_by_address(address, timeout=args.scan_seconds)
  if device is None:
    raise RuntimeError(
      "Scale was not advertising during the scan. Wake it and run again."
    )
  path = args.output or ROOT / "captures" / (
    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%fZ") + ".jsonl"
  )
  journal = Journal(path)
  queue = asyncio.Queue()
  assemblers = {uuid: FrameAssembler() for uuid in RECEIVE_UUIDS}
  decoder = PacketDecoder()
  outgoing_sequence = 0
  measurements = 0

  def receive(characteristic, data):
    queue.put_nowait((characteristic.uuid.lower(), bytes(data)))

  def disconnected(client):
    queue.put_nowait((None, b""))

  def report_decode_error(error):
    journal.record("decode_error", message=str(error))
    journal.sync()
    print(f"Undecoded data preserved: {error}", file=sys.stderr, flush=True)

  try:
    journal.record(
      "session", address=address, acknowledgement_policy="device_info_and_live_only"
    )
    async with BleakClient(device, disconnected_callback=disconnected) as client:
      model = (
        (await client.read_gatt_char("00002a24-0000-1000-8000-00805f9b34fb"))
        .decode()
        .strip("\x00 ")
      )
      manufacturer = (
        (await client.read_gatt_char("00002a29-0000-1000-8000-00805f9b34fb"))
        .decode()
        .strip("\x00 ")
      )
      if (manufacturer, model) != ("ICOMON", "FG2320ULB"):
        raise RuntimeError(
          f"Refusing protocol writes to unsupported device {manufacturer!r} {model!r}"
        )
      write_characteristic = client.services.get_characteristic(WRITE_UUID)
      if write_characteristic is None or "write" not in write_characteristic.properties:
        raise RuntimeError(
          "Expected acknowledged-write characteristic FFB1 is unavailable"
        )
      journal.record("connected", manufacturer=manufacturer, model=model)
      for uuid in RECEIVE_UUIDS:
        await client.start_notify(uuid, receive)
      print(f"Connected. Recording to {path}", flush=True)
      print(
        "No profile writes, history acknowledgements, cloud access, or firmware commands.",
        flush=True,
      )
      deadline = asyncio.get_running_loop().time() + args.seconds
      while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
          break
        try:
          characteristic, frame = await asyncio.wait_for(queue.get(), remaining)
        except TimeoutError:
          break
        if characteristic is None:
          journal.record("disconnected")
          break
        journal.record("notification", characteristic=characteristic, hex=frame.hex())
        try:
          packet = assemblers[characteristic].add(frame)
          if packet is None:
            continue
        except ValueError as error:
          report_decode_error(error)
          continue
        decoded_packets = decoder.decode(packet, characteristic)
        while True:
          try:
            packet_characteristic, decoded_packet, decoded = next(decoded_packets)
          except StopIteration:
            break
          except ValueError as error:
            report_decode_error(error)
            break
          journal.record(
            "packet",
            characteristic=packet_characteristic,
            payload_hex=decoded_packet.payload.hex(),
            decoded=decoded,
          )
          # A live-reading ACK is only sent after its raw and decoded data reach disk.
          journal.sync()
          kind = decoded["type"]
          if kind == "device_info":
            print(
              "Device capabilities: "
              + json.dumps(decoded["capabilities"], sort_keys=True),
              flush=True,
            )
          elif kind in ("streaming", "measurement", "history"):
            print(json.dumps(decoded, sort_keys=True), flush=True)
            if kind == "measurement":
              measurements += 1
          if kind in ("device_info", "measurement"):
            reply = acknowledge(decoded_packet, outgoing_sequence)
            journal.record(
              "write_requested", characteristic=WRITE_UUID, hex=reply.hex()
            )
            await client.write_gatt_char(write_characteristic, reply, response=True)
            journal.record(
              "write_completed", characteristic=WRITE_UUID, hex=reply.hex()
            )
            outgoing_sequence = (outgoing_sequence + 1) & 255
          elif kind == "history":
            print(
              "Stored-history packet saved but not acknowledged; device-side retention is unverified.",
              flush=True,
            )
      journal.record("session_end", live_measurement_packets=measurements)
      journal.sync()
    print(
      f"Session ended: {measurements} live measurement packets. Capture: {path}",
      flush=True,
    )
  except Exception as error:
    journal.record("error", message=str(error))
    journal.sync()
    raise
  finally:
    journal.close()


def positive_seconds(value: str) -> float:
  number = float(value)
  if not 0 < number <= 86400:
    raise argparse.ArgumentTypeError("Duration must be between 0 and 86400 seconds")
  return number


def main():
  parser = argparse.ArgumentParser(
    description="Record and interpret R-MSC01 measurements locally, without a phone."
  )
  commands = parser.add_subparsers(dest="command", required=True)
  live = commands.add_parser(
    "record",
    help="Record one connection; acknowledge device info and live readings only",
  )
  live.add_argument("--device", type=Path, default=ROOT / "captures" / "device.json")
  live.add_argument(
    "--output",
    type=Path,
    help="New JSONL capture file; never overwrites an existing file",
  )
  live.add_argument("--scan-seconds", type=positive_seconds, default=120)
  live.add_argument("--seconds", type=positive_seconds, default=180)
  offline = commands.add_parser(
    "replay", help="Decode a saved capture without Bluetooth or any writes"
  )
  offline.add_argument("capture", type=Path)
  interpretation = commands.add_parser(
    "interpret",
    help="Label impedance channels and optionally calculate vendor estimates",
  )
  interpretation.add_argument("capture", type=Path)
  interpretation.add_argument("--age", type=int, help="Age in years, 10 through 80")
  interpretation.add_argument(
    "--athlete", action="store_true", help="Vendor athlete-mode setting"
  )
  interpretation.add_argument(
    "--bmi-standard", choices=("asia", "china", "who"), default="who"
  )
  interpretation.add_argument(
    "--height-cm", type=int, help="Height in whole centimetres"
  )
  interpretation.add_argument(
    "--sex", choices=("female", "male"), help="Vendor model sex setting"
  )
  interpretation.add_argument(
    "--output", type=Path, help="New private interpretation JSONL; never overwritten"
  )
  args = parser.parse_args()
  try:
    if args.command == "replay":
      replay(args.capture)
    elif args.command == "interpret":
      from morphoscan_body import Profile

      values = (args.age, args.height_cm, args.sex)
      profile = None
      if (
        any(value is not None for value in values)
        or args.athlete
        or args.bmi_standard != "who"
      ):
        if any(value is None for value in values):
          raise ValueError("Estimates require --age, --height-cm and --sex together")
        profile = Profile(
          age=args.age,
          athlete=args.athlete,
          bmi_standard=args.bmi_standard,
          height_cm=args.height_cm,
          sex=args.sex,
        )
      interpret(args.capture, profile, args.output)
    else:
      asyncio.run(record(args))
  except KeyboardInterrupt:
    print("Stopped.", file=sys.stderr)
    return 130
  except (OSError, RuntimeError, ValueError) as error:
    print(f"Error: {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
