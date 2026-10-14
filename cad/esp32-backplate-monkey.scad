// Engraved variant of the 2 mm plate / 1 mm riser backplate.
// Engraving is on the exposed underside, mirrored in XY so the monkey
// reads correctly from outside the assembled backplate (tail on right).
// Print at Z=0 with risers up. Engraving recesses bridge at Z=0.4 mm.
// The narrowest artwork stroke is approximately 0.46 mm at this scale.
use <esp32-backplate.scad>

$fn = 64;

engraving_depth = 0.4;
logo_height     = 18;
plate_centre_x  = 18.2;
review_underside = true;

assert(engraving_depth > 0 && engraving_depth <= 0.4);
assert(logo_height > 0 && logo_height <= 18);

module monkey_mark() {
  translate([plate_centre_x, 0])
    mirror([1, 0, 0])
      resize([0, logo_height], auto = true)
        import("monkey-logo.svg", center = true, dpi = 96);
}

module engraved_backplate() {
  difference() {
    backplate();
    translate([0, 0, -0.01])
      linear_extrude(height = engraving_depth + 0.01)
        monkey_mark();
  }
}

// Review underside face-up in the GUI only. Fabrication exports retain Z=0.
if ($preview && review_underside)
  translate([0, 0, 3]) rotate([0, 180, 0]) engraved_backplate();
else
  engraved_backplate();
