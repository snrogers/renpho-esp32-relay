import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = [ROOT / "README.md", ROOT / "firmware" / "README.md", ROOT / "cad" / "README.md"]


def slug(heading):
  """GitHub's anchor for a heading: lowercase, punctuation removed, spaces as hyphens."""
  return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(path):
  return {slug(h) for h in re.findall(r"^#{1,6} (.+)$", path.read_text(), re.MULTILINE)}


class ReadmeTest(unittest.TestCase):
  def test_every_section_link_points_to_a_heading(self):
    for doc in DOCS:
      for target, anchor in re.findall(r"\]\(([^)#\s]*)#([^)\s]+)\)", doc.read_text()):
        if target.startswith("http"):
          continue
        path = (doc.parent / target).resolve() if target else doc
        with self.subTest(doc=doc.relative_to(ROOT).as_posix(), link=f"{target}#{anchor}"):
          self.assertIn(anchor, anchors(path))

  def test_computer_tools_are_an_advanced_section_near_the_end(self):
    headings = re.findall(r"^## (.+)$", (ROOT / "README.md").read_text(), re.MULTILINE)
    self.assertIn("Advanced: computer tools", headings)
    self.assertNotIn("Computer tools", headings)
    self.assertNotIn("Local calculations", headings)
    self.assertGreater(headings.index("Advanced: computer tools"), headings.index("Releases"))
    self.assertEqual(headings[-1], "Publication and license")


if __name__ == "__main__":
  unittest.main()
