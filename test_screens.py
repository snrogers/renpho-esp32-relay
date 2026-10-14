import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("screens", ROOT / "firmware" / "host" / "screens.py")
screens = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(screens)


class ScreensTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.rendered = screens.render()

  def test_every_display_state_is_rendered(self):
    self.assertEqual(
        set(self.rendered),
        {"setup", "pairing", "listening", "queued", "delivered", "storage-error"},
    )
    for width, height, rows in self.rendered.values():
      self.assertEqual((width, height, len(rows)), (172 * 2, 320 * 2, 640))

  def test_documentation_images_match_the_firmware_renderer(self):
    self.assertEqual(screens.stale(self.rendered), [])

  def test_readme_shows_every_screen(self):
    readme = (ROOT / "README.md").read_text()
    for name in self.rendered:
      self.assertIn(f'src="docs/screens/{name}.png"', readme)

  def test_png_round_trip(self):
    image = screens.scale_rows(2, 1, bytes([255, 0, 0, 0, 0, 255]))
    self.assertEqual(screens.decode_png(screens.encode_png(*image)), image)

  def test_stale_reports_changed_missing_and_extra_images(self):
    red = screens.scale_rows(1, 1, bytes([255, 0, 0]))
    blue = screens.scale_rows(1, 1, bytes([0, 0, 255]))
    with tempfile.TemporaryDirectory() as tmp:
      output = Path(tmp)
      (output / "same.png").write_bytes(screens.encode_png(*red))
      (output / "changed.png").write_bytes(screens.encode_png(*red))
      (output / "extra.png").write_bytes(screens.encode_png(*red))
      (output / "broken.png").write_bytes(b"not a png")
      problems = screens.stale(
          {"same": red, "changed": blue, "missing": red, "broken": red}, output)
    self.assertEqual(problems, ["changed.png", "missing.png", "broken.png", "extra.png"])


if __name__ == "__main__":
  unittest.main()
