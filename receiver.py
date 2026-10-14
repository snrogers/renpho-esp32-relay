# /// script
# requires-python = ">=3.12"
# ///
"""Reference HTTP receiver for the RENPHO relay: store, list, and report readings.

Standard library only. Readings go to a local SQLite file. The receiver stamps
each new reading with the time it arrives, because the relay has no clock.
"""

import argparse
import html
import json
import re
import sqlite3
import sys
import threading
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENDPOINT = "/api/scale-readings"
BODY_LIMIT = 64 * 1024
DEVICE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
EVENT_ID = re.compile(r"[0-9a-f]{64}")
HEX = re.compile(r"(?:[0-9a-fA-F]{2}){1,512}")
SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
  device_id         TEXT    NOT NULL,
  event_id          TEXT    NOT NULL,
  received_at       TEXT    NOT NULL,
  weight_grams      INTEGER NOT NULL,
  scale_measurement TEXT,
  PRIMARY KEY (device_id, event_id)
)
"""


class InvalidReading(ValueError):
  pass


def now_local() -> str:
  return datetime.now().astimezone().isoformat(timespec="seconds")


def packet_ok(value) -> bool:
  return (
    isinstance(value, dict)
    and isinstance(value.get("payloadHex"), str)
    and HEX.fullmatch(value["payloadHex"]) is not None
    and type(value.get("sequence")) is int
    and 0 <= value["sequence"] <= 255
    and type(value.get("unit")) is int
    and 0 <= value["unit"] <= 7
  )


def validate(reading) -> dict:
  if not isinstance(reading, dict):
    raise InvalidReading("body must be a JSON object")
  device_id = reading.get("deviceId")
  event_id = reading.get("eventId")
  weight = reading.get("weightGrams")
  if not isinstance(device_id, str) or not DEVICE_ID.fullmatch(device_id):
    raise InvalidReading("deviceId must be 1-128 of [A-Za-z0-9._:-]")
  if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
    raise InvalidReading("eventId must be 64 lowercase hexadecimal characters")
  if type(weight) is not int or weight <= 0:
    raise InvalidReading("weightGrams must be a positive integer")
  measurement = reading.get("scaleMeasurement")
  if measurement is not None:
    raw = measurement.get("rawPackets") if isinstance(measurement, dict) else None
    if (
      not isinstance(raw, list)
      or len(raw) != 2
      or not all(packet_ok(packet) for packet in raw)
      or raw[0]["payloadHex"].lower() != str(measurement.get("deviceInfoPayloadHex")).lower()
      or raw[1]["payloadHex"].lower() != str(measurement.get("measurementPayloadHex")).lower()
    ):
      raise InvalidReading("scaleMeasurement must hold the device-info and measurement packets")
  return {
    "device_id": device_id,
    "event_id": event_id,
    "scale_measurement": measurement,
    "weight_grams": weight,
  }


class Store:
  def __init__(self, path: Path):
    self._lock = threading.Lock()
    self._db = sqlite3.connect(path, check_same_thread=False)
    self._db.execute(SCHEMA)
    self._db.commit()

  def ingest(self, reading: dict) -> tuple[HTTPStatus, dict]:
    """Insert a new reading or accept a retry; never change a stored weight or time."""
    measurement = reading["scale_measurement"]
    with self._lock, self._db:
      row = self._db.execute(
        "SELECT weight_grams, scale_measurement FROM readings WHERE device_id = ? AND event_id = ?",
        (reading["device_id"], reading["event_id"]),
      ).fetchone()
      if row is None:
        self._db.execute(
          "INSERT INTO readings VALUES (?, ?, ?, ?, ?)",
          (
            reading["device_id"],
            reading["event_id"],
            now_local(),
            reading["weight_grams"],
            None if measurement is None else json.dumps(measurement, sort_keys=True),
          ),
        )
        status = "recorded"
      elif row[0] != reading["weight_grams"]:
        return HTTPStatus.CONFLICT, {"error": "eventId already stored with a different weight"}
      else:
        if row[1] is None and measurement is not None:
          # A weight-only record gains the packets that a later upload adds.
          self._db.execute(
            "UPDATE readings SET scale_measurement = ? WHERE device_id = ? AND event_id = ?",
            (json.dumps(measurement, sort_keys=True), reading["device_id"], reading["event_id"]),
          )
        status = "duplicate"
    return HTTPStatus.OK, {"eventId": reading["event_id"], "status": status}

  def readings(self) -> list[dict]:
    with self._lock:
      rows = self._db.execute(
        "SELECT device_id, event_id, received_at, weight_grams, scale_measurement"
        " FROM readings ORDER BY received_at DESC, rowid DESC"
      ).fetchall()
    return [
      {
        "deviceId": device_id,
        "eventId": event_id,
        "receivedAt": received_at,
        "scaleMeasurement": None if measurement is None else json.loads(measurement),
        "weightGrams": weight,
      }
      for device_id, event_id, received_at, weight, measurement in rows
    ]

  def close(self):
    self._db.close()


def pounds(grams: int) -> float:
  return grams / 453.59237


def page(readings: list[dict]) -> str:
  rows = "".join(
    f"<tr><td>{html.escape(r['receivedAt'])}</td><td>{pounds(r['weightGrams']):.1f}</td>"
    f"<td>{r['weightGrams'] / 1000:.2f}</td><td>{html.escape(r['deviceId'])}</td>"
    f"<td>{'yes' if r['scaleMeasurement'] else 'no'}</td></tr>"
    for r in readings
  ) or '<tr><td colspan="5">No readings yet. Step onto the scale.</td></tr>'
  return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scale readings</title>
<style>
body {{ font: 16px system-ui, sans-serif; margin: 2rem auto; max-width: 48rem; padding: 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #8884; padding: .4rem .6rem; text-align: left; }}
td:nth-child(2), td:nth-child(3) {{ font-variant-numeric: tabular-nums; }}
</style></head><body>
<h1>Scale readings</h1>
<table><thead><tr><th>Received</th><th>lb</th><th>kg</th><th>Relay</th><th>Packets</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>
"""


def make_handler(store: Store):
  class Handler(BaseHTTPRequestHandler):
    server_version = "renpho-receiver"

    def send(self, status: HTTPStatus, body: bytes, content_type: str):
      self.send_response(status)
      self.send_header("Content-Type", content_type)
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)

    def send_json(self, status: HTTPStatus, value):
      self.send(status, json.dumps(value).encode(), "application/json")

    def do_GET(self):
      if self.path == "/":
        self.send(HTTPStatus.OK, page(store.readings()).encode(), "text/html; charset=utf-8")
      elif self.path == ENDPOINT:
        self.send_json(HTTPStatus.OK, store.readings())
      else:
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
      if self.path != ENDPOINT:
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        return
      try:
        length = int(self.headers.get("Content-Length", ""))
      except ValueError:
        self.send_json(HTTPStatus.LENGTH_REQUIRED, {"error": "Content-Length required"})
        return
      if not 0 < length <= BODY_LIMIT:
        self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
        return
      try:
        reading = validate(json.loads(self.rfile.read(length)))
      except (InvalidReading, ValueError) as error:
        self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        return
      self.send_json(*store.ingest(reading))

  return Handler


def serve(args):
  store = Store(args.db)
  server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
  print(f"Receiving at http://{args.host}:{args.port}{ENDPOINT}; readings in {args.db}", flush=True)
  try:
    server.serve_forever()
  finally:
    server.server_close()
    store.close()


def list_readings(args):
  store = Store(args.db)
  try:
    for r in store.readings():
      print(f"{r['receivedAt']}  {pounds(r['weightGrams']):6.1f} lb  {r['weightGrams'] / 1000:6.2f} kg  {r['deviceId']}")
  finally:
    store.close()


def report(args):
  from morphoscan_body import BodyComposition, Profile, impedance_channels
  from morphoscan_protocol import Packet, PacketDecoder

  profile = Profile(
    age=args.age,
    athlete=args.athlete,
    bmi_standard=args.bmi_standard,
    height_cm=args.height_cm,
    sex=args.sex,
  )
  calculator = BodyComposition()
  store = Store(args.db)
  try:
    readings = store.readings()
  finally:
    store.close()
  for r in readings:
    result = {"eventId": r["eventId"], "receivedAt": r["receivedAt"], "weightGrams": r["weightGrams"]}
    if r["scaleMeasurement"] is None:
      result["estimationStatus"] = "no_packets"
    else:
      try:
        decoder = PacketDecoder()
        decoded = None
        for raw in r["scaleMeasurement"]["rawPackets"]:
          packet = Packet(bytes.fromhex(raw["payloadHex"]), raw["sequence"], raw["unit"])
          for _, _, value in decoder.decode(packet, None):
            if value["type"] in ("measurement", "history"):
              decoded = value
        if decoded is None:
          raise ValueError("packets hold no measurement")
        result["impedanceOhmsByFrequencyKhz"] = impedance_channels(decoded)
        result["bodyCompositionEstimates"] = calculator.calculate(decoded, profile)
        result["estimationStatus"] = "calculated_locally"
      except ValueError as error:
        result["estimationStatus"] = "error"
        result["error"] = str(error)
    result["profile"] = asdict(profile)
    print(json.dumps(result, allow_nan=False, sort_keys=True))


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument(
    "--db", type=Path, default=ROOT / "readings.sqlite3", help="SQLite file (default: %(default)s)"
  )
  commands = parser.add_subparsers(dest="command", required=True)
  server = commands.add_parser("serve", help="Accept readings from the relay over HTTP")
  server.add_argument("--host", default="0.0.0.0", help="Listen address (default: all interfaces)")
  server.add_argument("--port", type=int, default=8080)
  commands.add_parser("list", help="Print stored readings, newest first")
  estimates = commands.add_parser("report", help="Calculate body-composition estimates as JSON lines")
  estimates.add_argument("--age", type=int, required=True, help="Age in years, 10 through 80")
  estimates.add_argument("--height-cm", type=int, required=True, help="Height in whole centimetres")
  estimates.add_argument("--sex", choices=("female", "male"), required=True, help="Vendor model sex setting")
  estimates.add_argument("--athlete", action="store_true", help="Vendor athlete-mode setting")
  estimates.add_argument("--bmi-standard", choices=("asia", "china", "who"), default="who")
  args = parser.parse_args(argv)
  try:
    {"list": list_readings, "report": report, "serve": serve}[args.command](args)
  except KeyboardInterrupt:
    return 130
  except ValueError as error:
    print(f"receiver.py: {error}", file=sys.stderr)
    return 2
  return 0


if __name__ == "__main__":
  sys.exit(main())
