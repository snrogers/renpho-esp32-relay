import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import receiver

INFO_HEX = "aab37116206425010a250000000000000000000000000000000000000000"
MEASUREMENT_HEX = "a712345678250124f8000a03e807d00bb80fa0138817701b581f4023282710ffffffff000000"
EVENT_ID = "ab" * 32
READING = {"deviceId": "relay-1", "eventId": EVENT_ID, "weightGrams": 75000}
SCALE_MEASUREMENT = {
  "deviceInfoPayloadHex": INFO_HEX,
  "measurementPayloadHex": MEASUREMENT_HEX,
  "rawPackets": [
    {"payloadHex": INFO_HEX, "sequence": 0, "unit": 1},
    {"payloadHex": MEASUREMENT_HEX, "sequence": 1, "unit": 1},
  ],
  "sequence": 1,
  "unit": 1,
}


class ReceiverTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.db = Path(self.directory.name) / "readings.sqlite3"
    self.store = receiver.Store(self.db)
    self.server = ThreadingHTTPServer(("127.0.0.1", 0), receiver.make_handler(self.store))
    threading.Thread(target=self.server.serve_forever, daemon=True).start()
    self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

  def tearDown(self):
    self.server.shutdown()
    self.server.server_close()
    self.store.close()
    self.directory.cleanup()

  def post(self, body, path=receiver.ENDPOINT):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    request = urllib.request.Request(
      self.base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
      with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
      return error.code, json.loads(error.read())

  def get(self, path):
    with urllib.request.urlopen(self.base + path) as response:
      return response.status, response.headers["Content-Type"], response.read().decode()

  def test_records_new_reading_with_receipt_time_and_relay_shaped_response(self):
    status, body = self.post({**READING, "scaleMeasurement": SCALE_MEASUREMENT})
    self.assertEqual((status, body), (200, {"eventId": EVENT_ID, "status": "recorded"}))
    self.assertLess(len(json.dumps(body)), 511)
    [stored] = json.loads(self.get(receiver.ENDPOINT)[2])
    self.assertEqual(stored["weightGrams"], 75000)
    self.assertEqual(stored["scaleMeasurement"], SCALE_MEASUREMENT)
    self.assertIsNotNone(datetime.fromisoformat(stored["receivedAt"]).utcoffset())

  def test_retry_is_duplicate_and_keeps_the_first_receipt_time(self):
    self.post(READING)
    first = self.store.readings()[0]["receivedAt"]
    self.assertEqual(self.post(READING), (200, {"eventId": EVENT_ID, "status": "duplicate"}))
    self.assertEqual(len(self.store.readings()), 1)
    self.assertEqual(self.store.readings()[0]["receivedAt"], first)

  def test_weight_only_record_gains_packets_from_a_later_upload(self):
    self.post(READING)
    self.assertEqual(self.post({**READING, "scaleMeasurement": SCALE_MEASUREMENT})[1]["status"], "duplicate")
    self.assertEqual(self.store.readings()[0]["scaleMeasurement"], SCALE_MEASUREMENT)

  def test_conflicting_weight_for_the_same_event_is_rejected(self):
    self.post(READING)
    status, body = self.post({**READING, "weightGrams": 76000})
    self.assertEqual(status, 409)
    self.assertIn("different weight", body["error"])
    self.assertEqual(self.store.readings()[0]["weightGrams"], 75000)

  def test_invalid_requests_are_rejected_without_storing(self):
    cases = [
      b"not json",
      [],
      {**READING, "eventId": "A" * 64},
      {**READING, "deviceId": "bad id"},
      {**READING, "weightGrams": 0},
      {**READING, "weightGrams": "75000"},
      {**READING, "scaleMeasurement": {**SCALE_MEASUREMENT, "rawPackets": []}},
      {**READING, "scaleMeasurement": {**SCALE_MEASUREMENT, "deviceInfoPayloadHex": "00"}},
    ]
    for body in cases:
      with self.subTest(body=body):
        self.assertEqual(self.post(body)[0], 400)
    self.assertEqual(self.post(READING, path="/elsewhere")[0], 404)
    self.assertEqual(self.store.readings(), [])

  def test_page_lists_readings_in_pounds_and_kilograms(self):
    self.assertIn("No readings yet", self.get("/")[2])
    self.post(READING)
    status, content_type, text = self.get("/")
    self.assertEqual(status, 200)
    self.assertTrue(content_type.startswith("text/html"))
    self.assertIn("<td>165.3</td><td>75.00</td><td>relay-1</td>", text)

  def test_report_calculates_estimates_from_stored_packets(self):
    self.post({**READING, "scaleMeasurement": SCALE_MEASUREMENT})
    self.post({**READING, "eventId": "cd" * 32})
    output = io.StringIO()
    with redirect_stdout(output):
      code = receiver.main(
        ["--db", str(self.db), "report", "--age", "35", "--height-cm", "180", "--sex", "male"]
      )
    self.assertEqual(code, 0)
    results = {r["eventId"]: r for r in map(json.loads, output.getvalue().splitlines())}
    self.assertEqual(results["cd" * 32]["estimationStatus"], "no_packets")
    calculated = results[EVENT_ID]
    self.assertEqual(calculated["estimationStatus"], "calculated_locally", calculated.get("error"))
    self.assertIn("body_fat_percent", calculated["bodyCompositionEstimates"])


if __name__ == "__main__":
  unittest.main()
