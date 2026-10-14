import argparse
import importlib.util
import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
  "flash", Path(__file__).resolve().parent / "firmware" / "flash.py"
)
flash = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flash)


class Answers:
  def __init__(self, answers):
    self.answers = list(answers)
    self.prompts = []

  def __call__(self, prompt):
    self.prompts.append(prompt)
    return self.answers.pop(0)


class SetupTest(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.home = Path(self.directory.name)
    self.calls = []
    self.statuses = []
    patches = {
      "load_flasher_args": lambda build: {"_resolved": {}},
      "flash_command": lambda build, port, flasher: ["write-flash"],
      "run_esptool": self.fake_esptool,
      "reopen_after_reset": lambda port, timeout: mock.Mock(),
      "configure_device": lambda port, values, timeout: self.calls.append(("configure", values)) or {"event": "configured"},
      "status_device": lambda port, timeout: self.statuses.pop(0),
      "espressif_ports": lambda: [mock.Mock(device="COM9")],
    }
    for name, value in patches.items():
      patcher = mock.patch.object(flash, name, value)
      patcher.start()
      self.addCleanup(patcher.stop)
    for patcher in (mock.patch.object(flash.time, "sleep", lambda s: None), mock.patch.object(flash.Path, "home", lambda: self.home)):
      patcher.start()
      self.addCleanup(patcher.stop)

  def tearDown(self):
    self.directory.cleanup()

  def fake_esptool(self, command, cwd):
    self.calls.append(("esptool", command))
    if "read-flash" in command:
      Path(command[-1]).write_bytes(b"\xff" * flash.FLASH_BYTES)

  def run_setup(self, answers, secrets):
    args = argparse.Namespace(build="firmware/build", port=None, timeout=1.0, pair_seconds=0.0)
    ask, secret = Answers(answers), Answers(secrets)
    output = io.StringIO()
    with redirect_stdout(output):
      code = flash.cmd_setup(args, ask, secret)
    return code, output.getvalue(), ask

  def test_full_setup_backs_up_saves_flashes_configures_and_pairs(self):
    self.statuses = [
      {"event": "status", "wifiConnected": True, "scaleAddress": ""},
      {"event": "status", "wifiConnected": True, "scaleAddress": "B4:56:5D:5E:26:3E"},
    ]
    code, output, ask = self.run_setup(
      ["lan", "http://192.0.2.10:8080", "", "", "", "", "", ""], ["hunter2"]
    )
    self.assertEqual(code, 0)
    kinds = [call[0] for call in self.calls]
    self.assertEqual(kinds, ["esptool", "esptool", "configure"])
    backup_command = self.calls[0][1]
    self.assertEqual(backup_command[:4], ["--chip", "esp32s3", "--port", "COM9"])
    self.assertEqual(backup_command[4:7], ["read-flash", "0", "0x1000000"])
    backup = Path(backup_command[-1])
    self.assertEqual(backup.parent, self.home.resolve())
    self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
    self.assertEqual(self.calls[1][1], ["write-flash"])
    self.assertEqual(
      self.calls[2][1],
      {"deviceId": "relay-1", "receiverUrl": "http://192.0.2.10:8080", "scaleAddress": "",
       "wifiPassword": "hunter2", "wifiSsid": "lan"},
    )
    self.assertIn("Step onto the scale now", output)
    self.assertIn("Paired with scale B4:56:5D:5E:26:3E", output)
    self.assertNotIn("hunter2", output + "".join(ask.prompts))

  def test_invalid_settings_are_asked_again_and_the_password_can_be_kept(self):
    self.statuses = [{"event": "status", "wifiConnected": True, "scaleAddress": "AA:BB:CC:DD:EE:FF"}]
    code, output, _ = self.run_setup(
      ["lan", "http://host/api/scale-readings", "", "not-a-mac",
       "", "http://host:8080", "", "", "n", "y", ""],
      ["pw", ""],
    )
    self.assertEqual(code, 0)
    self.assertIn("Check the settings: scaleAddress must be empty or a BLE MAC", output)
    self.assertEqual(self.calls[1][1]["receiverUrl"], "http://host:8080")
    self.assertEqual(self.calls[1][1]["scaleAddress"], "")
    self.assertEqual(self.calls[1][1]["wifiPassword"], "pw")
    saved = self.home / "relay-config.json"
    self.assertEqual(json.loads(saved.read_text())["wifiPassword"], "pw")
    self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
    self.assertEqual([call[0] for call in self.calls], ["esptool", "configure"])

  def test_stops_when_wifi_does_not_connect(self):
    self.statuses = [{"event": "status", "wifiConnected": False, "scaleAddress": ""}] * 50
    with mock.patch.object(flash.time, "monotonic", side_effect=[0.0, 0.0, 100.0, 100.0]):
      code, output, _ = self.run_setup(["lan", "http://host:8080", "", "", "n", "n"], ["pw"])
    self.assertEqual(code, 1)
    self.assertIn("not on Wi-Fi yet", output)

  def test_refuses_to_overwrite_an_existing_backup_file(self):
    existing = self.home / "old.bin"
    existing.write_bytes(b"keep")
    with self.assertRaisesRegex(flash.ToolError, "already exists"):
      self.run_setup(["lan", "http://host:8080", "", "", "y", str(existing)], ["pw"])
    self.assertEqual(existing.read_bytes(), b"keep")
    self.assertEqual(self.calls, [])


if __name__ == "__main__":
  unittest.main()
