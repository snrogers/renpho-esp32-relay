import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
  "flash", Path(__file__).resolve().parent / "firmware" / "flash.py"
)
flash = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flash)

VALID = {
  "deviceId":     "relay-1",
  "receiverUrl":    "http://192.0.2.10:8080",
  "scaleAddress": "AA:BB:CC:DD:EE:FF",
  "wifiPassword": "secret",
  "wifiSsid":     "lan",
}


class ConfigTest(unittest.TestCase):
  def test_accepts_complete_config(self):
    self.assertEqual(flash.validate_config(dict(VALID)), VALID)

  def test_rejects_unknown_field(self):
    with self.assertRaisesRegex(flash.ToolError, "unexpected fields: extra"):
      flash.validate_config({**VALID, "extra": "value"})

  def test_scale_address_is_optional_and_may_be_empty(self):
    without = {k: v for k, v in VALID.items() if k != "scaleAddress"}
    self.assertEqual(flash.validate_config(without)["scaleAddress"], "")
    self.assertEqual(flash.validate_config({**VALID, "scaleAddress": ""})["scaleAddress"], "")

  def test_rejects_malformed_scale_address(self):
    with self.assertRaisesRegex(flash.ToolError, "scaleAddress must be empty or a BLE MAC"):
      flash.validate_config({**VALID, "scaleAddress": "not-a-mac"})

  def test_receiver_url_is_any_http_endpoint(self):
    for url in (
      "http://192.0.2.10:8080/api/scale-readings",
      "https://hooks.example.com/relay/a1b2",
      "https://example.com/hook?token=abc&to=me@example.com",
    ):
      self.assertEqual(flash.validate_config({**VALID, "receiverUrl": url})["receiverUrl"], url)

  def test_rejects_receiver_url_credentials_fragment_and_scheme(self):
    for url, message in (
      ("http://user:pw@host/hook", "credentials"),
      ("http://host/hook#part", "fragment"),
      ("ftp://host/hook", "http\\(s\\) URL"),
      ("http:///hook", "missing a host"),
    ):
      with self.assertRaisesRegex(flash.ToolError, message):
        flash.validate_config({**VALID, "receiverUrl": url})

  def test_rejects_missing_field(self):
    payload = dict(VALID)
    del payload["wifiSsid"]
    with self.assertRaisesRegex(flash.ToolError, "missing required fields: wifiSsid"):
      flash.validate_config(payload)


if __name__ == "__main__":
  unittest.main()
