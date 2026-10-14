import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class NoticeTest(unittest.TestCase):
  def test_license_is_the_unlicense(self):
    text = (ROOT / "LICENSE").read_text()
    self.assertTrue(text.startswith("This is free and unencumbered software released into the public domain."))

  def test_notice_lists_every_monkey_artifact_and_nothing_missing(self):
    listed = set(re.findall(r"^  (cad/\S+)$", (ROOT / "NOTICE").read_text(), re.MULTILINE))
    for path in listed:
      self.assertTrue((ROOT / path).is_file(), path)
    artifacts = {
      f"cad/{p.name}" for p in (ROOT / "cad").iterdir()
      if "monkey" in p.name and p.suffix != ".scad"
    }
    self.assertEqual(listed, artifacts)


if __name__ == "__main__":
  unittest.main()
