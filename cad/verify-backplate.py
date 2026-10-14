"""Run python3 verify-backplate.py [--monkey]; requires the OpenSCAD skill."""

from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path.home() / ".agents/skills/openscad/scripts"))
from scad_mesh import bbox, non_manifold_edges, probe_volume, stl_triangles

root = Path(__file__).resolve().parent
assert sys.argv[1:] in ([], ["--monkey"]), "Usage: verify-backplate.py [--monkey]"
monkey = sys.argv[1:] == ["--monkey"]
stem = "esp32-backplate-monkey" if monkey else "esp32-backplate"
part = "engraved_backplate" if monkey else "backplate"
triangles = stl_triangles(root / f"{stem}.stl")
assert triangles and non_manifold_edges(triangles) == 0
print("PASS: watertight mesh")

adjacency = defaultdict(set)
for triangle in triangles:
  for a, b in zip(triangle, triangle[1:] + triangle[:1]):
    adjacency[a].add(b)
    adjacency[b].add(a)
seen = set()
pending = [next(iter(adjacency))]
while pending:
  vertex = pending.pop()
  if vertex not in seen:
    seen.add(vertex)
    pending.extend(adjacency[vertex] - seen)
assert len(seen) == len(adjacency)
print("PASS: one connected solid")

size = bbox(triangles)
assert all(abs(actual - expected) < 0.001
           for actual, expected in zip(size, (38.4, 22.33, 3.0)))
print(f"PASS: overall dimensions {size} mm")

# Independent coordinates transcribed from the official structural PDF.
# 36.4 - 1.98 = 34.42; 34.42 - 32 = 2.42.
points = [(2.42, -8.16), (2.42, 8.16), (34.42, -6.64), (34.42, 6.64)]
model = root / f"{stem}.scad"
for index, (x, y) in enumerate(points):
  for shift, clear in [(0, True), (0.5, False)]:
    volume = probe_volume(model, f"""
      intersection() {{
        {part}();
        translate([{x + shift}, {y}, -0.1])
          cylinder(d=2.0, h=3.2, $fn=48);
      }}
    """)
    assert (volume < 0.001) if clear else (volume > 0.1)
  print(f"PASS: mounting hole {index + 1} clears a 2 mm shank; shifted shank collides")

volume = probe_volume(model, f"""
  intersection() {{
    {part}();
    translate([5, -5, 2.1]) cube([26, 10, 0.9]);
  }}
""")
assert volume < 0.001
print("PASS: central underside clearance envelope is open")

if monkey:
  # The body of the supplied mark crosses this central probe on the underside.
  for z, expected in [(0.0, 0.0), (0.41, 0.036)]:
    volume = probe_volume(model, f"""
      intersection() {{
        engraved_backplate();
        translate([20.5, -3.0, {z}]) cube([0.6, 0.6, 0.1]);
      }}
    """)
    assert abs(volume - expected) < 0.001, (z, volume)
  print("PASS: engraving opens from underside; material remains above 0.4 mm")
print("Physical board fit, thread type, and screw engagement remain untested.")
